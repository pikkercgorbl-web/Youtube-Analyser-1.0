"""Refine Video.content_format=UNKNOWN via batched videos.list (Stage 2). Not used during Attention refresh."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.orm import Video, VideoFormat, VideoFormatEnrichmentAttempt
from app.services.radar_api_budget import (
    BUDGET_KIND_VIDEOS_LIST,
    record_http_requests,
    remaining_id_units,
    try_reserve_id_units,
)
from app.services.unknown_format_enrichment_config import (
    VIDEOS_LIST_BATCH_SIZE,
    unknown_format_enrichment_settings,
)
from app.services.video_format_batch_apply import apply_format_details_for_batch
from app.services.video_format_from_api import chunk_video_ids


class VideosListClient(Protocol):
    def get_videos(self, video_ids: list[str]) -> list[object]:
        ...


@dataclass
class UnknownFormatEnrichmentResult:
    selected: int = 0
    api_batches: int = 0
    updated: int = 0
    unchanged_unknown: int = 0
    skipped_already_fetched: int = 0
    skipped_daily_budget: int = 0
    daily_budget_limit: int = 0
    daily_budget_used_before: int = 0
    dry_run: bool = False
    video_ids_planned: tuple[str, ...] = ()
    updates_by_format: dict[str, int] = field(default_factory=dict)


def _utc_day_start(now: datetime | None = None) -> datetime:
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return reference.replace(hour=0, minute=0, second=0, microsecond=0)


def count_daily_format_enrichment_attempts(session: Session, *, now: datetime | None = None) -> int:
    start = _utc_day_start(now)
    return int(
        session.scalar(
            select(func.count())
            .select_from(VideoFormatEnrichmentAttempt)
            .where(VideoFormatEnrichmentAttempt.last_attempt_at >= start),
        )
        or 0,
    )


from app.services.format_enrichment_attempts import record_format_enrichment_attempt  # noqa: F401 — re-export

def select_unknown_video_ids_for_enrichment(
    session: Session,
    *,
    limit: int | None = None,
    exclude_video_ids: set[str] | frozenset[str] | None = None,
    now: datetime | None = None,
) -> list[str]:
    daily_limit = (
        limit
        if limit is not None
        else unknown_format_enrichment_settings.unknown_format_enrichment_daily_video_limit
    )
    if daily_limit <= 0:
        return []
    remaining = remaining_id_units(
        session,
        budget_kind=BUDGET_KIND_VIDEOS_LIST,
        daily_limit=daily_limit,
        now=now,
    )
    if remaining <= 0:
        return []

    exclude = exclude_video_ids or frozenset()
    stmt = (
        select(Video.id, VideoFormatEnrichmentAttempt.last_attempt_at)
        .outerjoin(
            VideoFormatEnrichmentAttempt,
            VideoFormatEnrichmentAttempt.video_id == Video.id,
        )
        .where(Video.content_format == VideoFormat.UNKNOWN)
        .order_by(
            VideoFormatEnrichmentAttempt.last_attempt_at.asc().nulls_first(),
            Video.published_at.desc(),
        )
    )
    rows = session.execute(stmt).all()
    out: list[str] = []
    for vid, _last in rows:
        if vid in exclude:
            continue
        out.append(vid)
        if len(out) >= remaining:
            break
    return out


def apply_unknown_format_enrichment(
    session: Session,
    youtube_client: VideosListClient,
    *,
    exclude_video_ids: set[str] | frozenset[str] | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> UnknownFormatEnrichmentResult:
    daily_limit = (
        limit
        if limit is not None
        else unknown_format_enrichment_settings.unknown_format_enrichment_daily_video_limit
    )
    used_before = daily_limit - remaining_id_units(
        session,
        budget_kind=BUDGET_KIND_VIDEOS_LIST,
        daily_limit=daily_limit,
        now=now,
    )
    exclude = frozenset(exclude_video_ids or ())
    video_ids = select_unknown_video_ids_for_enrichment(
        session,
        limit=daily_limit,
        exclude_video_ids=exclude,
        now=now,
    )
    result = UnknownFormatEnrichmentResult(
        selected=len(video_ids),
        dry_run=dry_run,
        video_ids_planned=tuple(video_ids),
        daily_budget_limit=daily_limit,
        daily_budget_used_before=used_before,
        skipped_daily_budget=max(0, daily_limit - used_before - len(video_ids)),
    )
    if not video_ids:
        return result

    stamp = now or datetime.now(timezone.utc)
    for batch in chunk_video_ids(video_ids, batch_size=VIDEOS_LIST_BATCH_SIZE):
        to_fetch = [vid for vid in batch if vid not in exclude]
        result.skipped_already_fetched += len(batch) - len(to_fetch)
        if not to_fetch:
            continue
        if dry_run:
            result.api_batches += 1
            continue
        reservation = try_reserve_id_units(
            session,
            budget_kind=BUDGET_KIND_VIDEOS_LIST,
            unit_count=len(to_fetch),
            daily_limit=daily_limit,
            now=stamp,
        )
        to_fetch = to_fetch[: reservation.reserved]
        if not to_fetch:
            break
        from app.integrations.youtube.client import YouTubeVideoDetails

        details_by_id: dict[str, YouTubeVideoDetails] = {}
        try:
            details_list = youtube_client.get_videos(to_fetch)
            record_http_requests(session, budget_kind=BUDGET_KIND_VIDEOS_LIST, request_count=1, now=stamp)
            result.api_batches += 1
            for details in details_list:
                if isinstance(details, YouTubeVideoDetails):
                    details_by_id[details.video_id] = details
        except Exception:
            apply_format_details_for_batch(session, to_fetch, {}, attempted_at=stamp)
            continue
        apply_report = apply_format_details_for_batch(session, to_fetch, details_by_id, attempted_at=stamp)
        result.updated += (
            apply_report.confirmed_regular + apply_report.stream + apply_report.short
        )
        for outcome in apply_report.outcomes_by_video_id.values():
            if outcome.startswith("updated_") or outcome == "unchanged":
                result.updates_by_format[outcome] = result.updates_by_format.get(outcome, 0) + 1

    session.flush()
    return result
