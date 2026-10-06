"""Batch revisit executor: capture requests → VideoSnapshots (Stage 1.13B)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol, Sequence

from sqlalchemy.orm import Session

from app.integrations.youtube.client import YouTubeVideoDetails
from app.services.metrics import utc_now
from app.services.radar_candidate_enrichment import SHORT_DURATION_SECONDS
from app.services.snapshot_collection_policy import SnapshotCaptureRequest
from app.services.video_snapshot_storage import (
    VideoSnapshotObservation,
    derive_snapshot_metrics,
    find_snapshot_by_capture_run_key,
    persist_video_snapshot,
)

ExecutionStatus = Literal[
    "inserted",
    "duplicate",
    "missing",
    "fetch_failed",
    "validation_failed",
    "persistence_failed",
]

DEFAULT_BATCH_SIZE = 50


class VideoBatchFetchClient(Protocol):
    def get_videos(self, video_ids: list[str]) -> list[YouTubeVideoDetails]:
        ...


@dataclass(frozen=True, slots=True)
class RevisitExecutorConfig:
    batch_size: int = DEFAULT_BATCH_SIZE


@dataclass(frozen=True, slots=True)
class SnapshotCaptureExecutionResult:
    video_id: str
    channel_id: str | None
    checkpoint_age_hours: int
    reason: str
    run_id: str
    requested_at: datetime
    captured_at: datetime | None
    status: ExecutionStatus
    snapshot_id: int | None = None
    age_hours: float | None = None
    views: int | None = None
    vph: float | None = None
    error: str | None = None


@dataclass
class RevisitExecutionSummary:
    input_request_count: int = 0
    unique_request_count: int = 0
    duplicate_request_count: int = 0
    batch_count: int = 0
    successful_batch_count: int = 0
    failed_batch_count: int = 0
    requested_video_count: int = 0
    returned_video_count: int = 0
    inserted_snapshot_count: int = 0
    duplicate_snapshot_count: int = 0
    missing_video_count: int = 0
    validation_failed_count: int = 0
    persistence_failed_count: int = 0
    fetch_failed_count: int = 0
    total_failed_count: int = 0
    runtime_seconds: float = 0.0
    status_counts: dict[str, int] = field(default_factory=dict)
    batch_errors: tuple[str, ...] = ()


@dataclass
class RevisitExecutionOutcome:
    results: list[SnapshotCaptureExecutionResult]
    summary: RevisitExecutionSummary


def _request_dedupe_key(request: SnapshotCaptureRequest) -> tuple[str, int, str]:
    return (request.video_id, request.checkpoint_age_hours, request.run_id)


def deduplicate_capture_requests(
    requests: Sequence[SnapshotCaptureRequest],
) -> tuple[list[SnapshotCaptureRequest], int, int]:
    input_count = len(requests)
    seen: set[tuple[str, int, str]] = set()
    unique: list[SnapshotCaptureRequest] = []
    for request in sorted(requests, key=lambda row: _request_dedupe_key(row)):
        key = _request_dedupe_key(request)
        if key in seen:
            continue
        seen.add(key)
        unique.append(request)
    duplicate_count = input_count - len(unique)
    return unique, input_count, duplicate_count


def _chunk_video_ids(video_ids: list[str], batch_size: int) -> list[list[str]]:
    chunks: list[list[str]] = []
    for index in range(0, len(video_ids), batch_size):
        chunks.append(video_ids[index : index + batch_size])
    return chunks


def _classify_format(duration_seconds: int) -> tuple[str | None, bool | None, bool | None]:
    if duration_seconds <= 0:
        return "unknown", None, None
    if duration_seconds < SHORT_DURATION_SECONDS:
        return "short", True, False
    return "regular", False, False


def _details_to_observation(
    *,
    details: YouTubeVideoDetails,
    request: SnapshotCaptureRequest,
    captured_at: datetime,
    subscribers: int | None,
) -> VideoSnapshotObservation:
    content_format, is_short, is_live = _classify_format(details.duration_seconds)
    views = details.views_count if details.views_count >= 0 else None
    likes = details.likes_count if details.likes_count >= 0 else None
    comments = details.comments_count if details.comments_count >= 0 else None
    channel_id = (details.channel_id or request.channel_id or "").strip()
    return VideoSnapshotObservation(
        video_id=details.video_id,
        channel_id=channel_id,
        captured_at=captured_at,
        source=request.source,
        run_id=request.run_id,
        published_at=details.published_at,
        views=views,
        likes=likes,
        comments=comments,
        subscribers=subscribers,
        content_format=content_format,
        is_short=is_short,
        is_live=is_live,
        fetch_status="ok",
        raw_metadata=_raw_metadata_for_request(request),
    )


def _raw_metadata_for_request(request: SnapshotCaptureRequest) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "checkpoint_age_hours": request.checkpoint_age_hours,
        "capture_reason": request.reason,
        "requested_at": request.requested_at.isoformat(),
    }
    if request.outcome_target_at is not None:
        meta["capture_purpose"] = "keyword_delayed_outcome"
        meta["outcome_target_at"] = request.outcome_target_at.isoformat()
    return meta


def _result_from_request(
    request: SnapshotCaptureRequest,
    *,
    status: ExecutionStatus,
    captured_at: datetime | None = None,
    snapshot_id: int | None = None,
    age_hours: float | None = None,
    views: int | None = None,
    vph: float | None = None,
    error: str | None = None,
) -> SnapshotCaptureExecutionResult:
    return SnapshotCaptureExecutionResult(
        video_id=request.video_id,
        channel_id=request.channel_id,
        checkpoint_age_hours=request.checkpoint_age_hours,
        reason=request.reason,
        run_id=request.run_id,
        requested_at=request.requested_at,
        captured_at=captured_at,
        status=status,
        snapshot_id=snapshot_id,
        age_hours=age_hours,
        views=views,
        vph=vph,
        error=error,
    )


def execute_snapshot_capture_requests(
    requests: Sequence[SnapshotCaptureRequest],
    youtube_client: VideoBatchFetchClient,
    session: Session,
    *,
    config: RevisitExecutorConfig | None = None,
    subscribers_by_channel_id: dict[str, int] | None = None,
) -> RevisitExecutionOutcome:
    """
    Execute approved capture requests (no tier planning, no scheduling loop).

    Subscribers: optional preloaded map only; no per-video channel API calls.
    """
    started = time.perf_counter()
    cfg = config or RevisitExecutorConfig()
    subs_map = subscribers_by_channel_id or {}

    unique_requests, input_count, duplicate_request_count = deduplicate_capture_requests(requests)
    summary = RevisitExecutionSummary(
        input_request_count=input_count,
        unique_request_count=len(unique_requests),
        duplicate_request_count=duplicate_request_count,
    )

    requests_by_video: dict[str, list[SnapshotCaptureRequest]] = {}
    for request in unique_requests:
        requests_by_video.setdefault(request.video_id, []).append(request)

    ordered_video_ids = sorted(requests_by_video.keys())
    summary.requested_video_count = len(ordered_video_ids)
    video_batches = _chunk_video_ids(ordered_video_ids, cfg.batch_size)
    summary.batch_count = len(video_batches)

    details_by_id: dict[str, YouTubeVideoDetails] = {}
    batch_errors: list[str] = []
    failed_video_ids: set[str] = set()

    for batch_index, batch_ids in enumerate(video_batches):
        try:
            batch_details = youtube_client.get_videos(batch_ids)
            summary.successful_batch_count += 1
            for item in batch_details:
                details_by_id[item.video_id] = item
        except Exception as exc:
            summary.failed_batch_count += 1
            message = f"batch={batch_index}: {exc}"
            batch_errors.append(message)
            failed_video_ids.update(batch_ids)

    summary.returned_video_count = len(details_by_id)
    results: list[SnapshotCaptureExecutionResult] = []

    for request in unique_requests:
        if request.video_id in failed_video_ids:
            summary.fetch_failed_count += 1
            results.append(
                _result_from_request(request, status="fetch_failed", error="batch_fetch_failed"),
            )
            continue

        existing = find_snapshot_by_capture_run_key(
            session,
            video_id=request.video_id,
            source=request.source,
            run_id=request.run_id,
        )
        if existing is not None:
            summary.duplicate_snapshot_count += 1
            results.append(
                _result_from_request(
                    request,
                    status="duplicate",
                    captured_at=existing.captured_at,
                    snapshot_id=existing.id,
                    age_hours=existing.age_hours,
                    views=existing.views,
                    vph=existing.vph,
                ),
            )
            continue

        details = details_by_id.get(request.video_id)
        if details is None:
            summary.missing_video_count += 1
            results.append(_result_from_request(request, status="missing"))
            continue

        captured_at = utc_now()
        subscribers = subs_map.get(details.channel_id) if details.channel_id else None
        if subscribers is not None and subscribers <= 0:
            subscribers = None

        try:
            observation = _details_to_observation(
                details=details,
                request=request,
                captured_at=captured_at,
                subscribers=subscribers,
            )
        except ValueError as exc:
            summary.validation_failed_count += 1
            results.append(
                _result_from_request(request, status="validation_failed", error=str(exc)),
            )
            continue

        if not observation.channel_id:
            summary.validation_failed_count += 1
            results.append(
                _result_from_request(
                    request,
                    status="validation_failed",
                    error="channel_id missing",
                ),
            )
            continue

        try:
            _row, validation_error, is_duplicate = persist_video_snapshot(session, observation)
        except Exception as exc:
            summary.persistence_failed_count += 1
            results.append(
                _result_from_request(
                    request,
                    status="persistence_failed",
                    captured_at=captured_at,
                    error=str(exc),
                ),
            )
            continue

        if validation_error is not None:
            summary.validation_failed_count += 1
            results.append(
                _result_from_request(
                    request,
                    status="validation_failed",
                    captured_at=captured_at,
                    error=validation_error.message,
                ),
            )
            continue

        age_hours, vph, _ = derive_snapshot_metrics(
            views=observation.views,
            published_at=observation.published_at,
            captured_at=captured_at,
            subscribers=observation.subscribers,
        )

        if is_duplicate:
            summary.duplicate_snapshot_count += 1
            existing_after = find_snapshot_by_capture_run_key(
                session,
                video_id=request.video_id,
                source=request.source,
                run_id=request.run_id,
            )
            results.append(
                _result_from_request(
                    request,
                    status="duplicate",
                    captured_at=captured_at,
                    snapshot_id=existing_after.id if existing_after else None,
                    age_hours=age_hours,
                    views=observation.views,
                    vph=vph,
                ),
            )
            continue

        summary.inserted_snapshot_count += 1
        stored = find_snapshot_by_capture_run_key(
            session,
            video_id=request.video_id,
            source=request.source,
            run_id=request.run_id,
        )
        results.append(
            _result_from_request(
                request,
                status="inserted",
                captured_at=captured_at,
                snapshot_id=stored.id if stored is not None else None,
                age_hours=age_hours,
                views=observation.views,
                vph=vph,
            ),
        )

    summary.total_failed_count = (
        summary.fetch_failed_count
        + summary.missing_video_count
        + summary.validation_failed_count
        + summary.persistence_failed_count
    )
    summary.runtime_seconds = round(time.perf_counter() - started, 3)
    summary.batch_errors = tuple(batch_errors)
    status_counts: dict[str, int] = {}
    for result in results:
        status_counts[result.status] = status_counts.get(result.status, 0) + 1
    summary.status_counts = status_counts

    results.sort(key=lambda row: (row.video_id, row.checkpoint_age_hours, row.run_id))
    return RevisitExecutionOutcome(results=results, summary=summary)
