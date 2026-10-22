"""Manual SavedVideo metrics refresh via YouTube Data API (Stage 1.22C.2)."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import Channel, SavedVideo, SavedVideoObservation, Video, VideoSnapshot
from app.services.metrics import ensure_utc, utc_now
from app.services.revisit_executor import RevisitExecutorConfig, VideoBatchFetchClient, execute_snapshot_capture_requests
from app.services.saved_research import (
    VIDEO_ABSENCE_MESSAGE,
    SavedResearchArchivedError,
    SavedVideoNotFoundError,
    _apply_video_observation_row,
    _load_attention_snapshot,
    _winner_map,
    families_for_video,
)
from app.services.snapshot_collection_policy import SnapshotCaptureRequest
from app.services.video_snapshot_storage import find_snapshot_by_capture_run_key

MANUAL_SAVED_VIDEO_REFRESH_SOURCE = "manual_saved_video_refresh"
MANUAL_RUN_ID_PREFIX = f"{MANUAL_SAVED_VIDEO_REFRESH_SOURCE}:"
MANUAL_REFRESH_COOLDOWN = timedelta(minutes=5)
MANUAL_REFRESH_LEASE = timedelta(minutes=3)
MANUAL_CHECKPOINT_AGE_HOURS = 0


class SavedVideoManualRefreshError(Exception):
    pass


class SavedVideoManualRefreshCooldownError(SavedVideoManualRefreshError):
    def __init__(self, *, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"manual refresh cooldown ({retry_after_seconds}s remaining)")


class SavedVideoManualRefreshInProgressError(SavedVideoManualRefreshError):
    pass


class SavedVideoManualRefreshYouTubeError(SavedVideoManualRefreshError):
    pass


class SavedVideoManualRefreshVideoMissingError(SavedVideoManualRefreshError):
    pass


@dataclass(frozen=True, slots=True)
class SavedVideoManualRefreshResult:
    item: SavedVideo
    capture_run_id: str
    measured_at: datetime
    snapshot_id: int
    metrics_source: str
    idempotent: bool
    cooldown_seconds: int


def generate_manual_capture_run_id(*, now: datetime | None = None) -> str:
    reference = ensure_utc(now or utc_now())
    stamp = reference.strftime("%Y%m%dT%H%M%SZ")
    return f"{MANUAL_RUN_ID_PREFIX}{stamp}_{secrets.token_hex(4)}"


def is_manual_observation_run_id(run_id: str | None) -> bool:
    return bool(run_id and run_id.startswith(MANUAL_RUN_ID_PREFIX))


def _normalize_capture_run_id(run_id: str | None) -> str:
    if run_id is None or not run_id.strip():
        return generate_manual_capture_run_id()
    value = run_id.strip()
    if not value.startswith(MANUAL_RUN_ID_PREFIX):
        value = f"{MANUAL_RUN_ID_PREFIX}{value}"
    if len(value) > 128:
        raise ValueError("capture_run_id too long")
    return value


def _last_manual_refresh_at(session: Session, saved_video_id: int) -> datetime | None:
    row = session.scalar(
        select(SavedVideoObservation.observed_at)
        .where(
            SavedVideoObservation.saved_video_id == saved_video_id,
            SavedVideoObservation.attention_run_id.like(f"{MANUAL_RUN_ID_PREFIX}%"),
        )
        .order_by(SavedVideoObservation.observed_at.desc(), SavedVideoObservation.id.desc())
        .limit(1),
    )
    return ensure_utc(row) if row is not None else None


def _cooldown_remaining_seconds(last_at: datetime | None, *, now: datetime) -> int:
    if last_at is None:
        return 0
    elapsed = (ensure_utc(now) - ensure_utc(last_at)).total_seconds()
    remaining = int(MANUAL_REFRESH_COOLDOWN.total_seconds() - elapsed)
    return max(0, remaining)


def _lock_saved_video(session: Session, item_id: int) -> SavedVideo:
    row = session.execute(
        select(SavedVideo).where(SavedVideo.id == item_id).with_for_update(),
    ).scalar_one_or_none()
    if row is None:
        raise SavedVideoNotFoundError()
    if row.archived_at is not None:
        raise SavedResearchArchivedError("Saved video is archived")
    return row


def _attention_presence(session: Session, video_id: str) -> tuple[bool, list[dict[str, str]]]:
    result = _load_attention_snapshot(session)
    if result is None:
        return False, []
    present = video_id in _winner_map(result)
    families = families_for_video(result, video_id) if present else []
    return present, families


def build_manual_observation_payload(
    *,
    session: Session,
    video_id: str,
    snapshot: VideoSnapshot,
    capture_run_id: str,
) -> dict[str, Any]:
    present, families = _attention_presence(session, video_id)
    captured_at = ensure_utc(snapshot.captured_at)
    payload: dict[str, Any] = {
        "observation_kind": MANUAL_SAVED_VIDEO_REFRESH_SOURCE,
        "capture_run_id": capture_run_id,
        "metrics_source": "youtube_data_api",
        "video_snapshot_id": snapshot.id,
        "snapshot_source": snapshot.source,
        "snapshot_run_id": snapshot.run_id,
        "snapshot_captured_at": captured_at.isoformat(),
        "video_present_in_attention": present,
        "absence_message": None if present else VIDEO_ABSENCE_MESSAGE,
        "monitoring_snapshot_available": True,
        "family_memberships": families,
        "views": snapshot.views,
        "vph": snapshot.vph,
        "subscriber_count": snapshot.subscribers,
    }
    return payload


def refresh_saved_video_metrics(
    session: Session,
    item_id: int,
    youtube_client: VideoBatchFetchClient,
    *,
    capture_run_id: str | None = None,
) -> SavedVideoManualRefreshResult:
    now = utc_now()
    run_id = _normalize_capture_run_id(capture_run_id)

    row = _lock_saved_video(session, item_id)

    existing_obs = session.scalar(
        select(SavedVideoObservation.id).where(
            SavedVideoObservation.saved_video_id == row.id,
            SavedVideoObservation.attention_run_id == run_id,
        ),
    )
    if existing_obs is not None:
        snap = find_snapshot_by_capture_run_key(
            session,
            video_id=row.video_id,
            source=MANUAL_SAVED_VIDEO_REFRESH_SOURCE,
            run_id=run_id,
        )
        if snap is None:
            raise SavedVideoManualRefreshError("observation exists without snapshot")
        remaining = _cooldown_remaining_seconds(_last_manual_refresh_at(session, row.id), now=now)
        return SavedVideoManualRefreshResult(
            item=row,
            capture_run_id=run_id,
            measured_at=ensure_utc(snap.captured_at),
            snapshot_id=snap.id,
            metrics_source="youtube_data_api",
            idempotent=True,
            cooldown_seconds=remaining,
        )

    if row.manual_refresh_lease_until is not None and ensure_utc(row.manual_refresh_lease_until) > now:
        raise SavedVideoManualRefreshInProgressError()

    remaining = _cooldown_remaining_seconds(_last_manual_refresh_at(session, row.id), now=now)
    if remaining > 0:
        raise SavedVideoManualRefreshCooldownError(retry_after_seconds=remaining)

    row.manual_refresh_lease_until = now + MANUAL_REFRESH_LEASE
    session.flush()

    video = session.get(Video, row.video_id)
    if video is None:
        row.manual_refresh_lease_until = None
        session.flush()
        raise SavedVideoManualRefreshVideoMissingError()

    channel_id = (video.channel_id or row.frozen_channel_id or "").strip() or None
    subs_map: dict[str, int] = {}
    if channel_id:
        channel = session.get(Channel, channel_id)
        if channel is not None and channel.subscribers_count and channel.subscribers_count > 0:
            subs_map[channel_id] = int(channel.subscribers_count)

    request = SnapshotCaptureRequest(
        video_id=row.video_id,
        channel_id=channel_id,
        checkpoint_age_hours=MANUAL_CHECKPOINT_AGE_HOURS,
        reason="due",
        requested_at=now,
        current_age_hours=0.0,
        source=MANUAL_SAVED_VIDEO_REFRESH_SOURCE,
        run_id=run_id,
    )

    outcome = execute_snapshot_capture_requests(
        [request],
        youtube_client,
        session,
        config=RevisitExecutorConfig(batch_size=1),
        subscribers_by_channel_id=subs_map,
    )
    if not outcome.results:
        row.manual_refresh_lease_until = None
        session.flush()
        raise SavedVideoManualRefreshYouTubeError("no capture result")

    capture_result = outcome.results[0]
    if capture_result.status in ("fetch_failed", "missing", "validation_failed", "persistence_failed"):
        row.manual_refresh_lease_until = None
        session.flush()
        if capture_result.status == "missing":
            raise SavedVideoManualRefreshVideoMissingError()
        raise SavedVideoManualRefreshYouTubeError(capture_result.error or capture_result.status)

    snapshot = find_snapshot_by_capture_run_key(
        session,
        video_id=row.video_id,
        source=MANUAL_SAVED_VIDEO_REFRESH_SOURCE,
        run_id=run_id,
    )
    if snapshot is None or snapshot.id is None:
        row.manual_refresh_lease_until = None
        session.flush()
        raise SavedVideoManualRefreshYouTubeError("snapshot not persisted")

    measured_at = ensure_utc(snapshot.captured_at)
    payload = build_manual_observation_payload(
        session=session,
        video_id=row.video_id,
        snapshot=snapshot,
        capture_run_id=run_id,
    )
    obs = _apply_video_observation_row(
        saved_video_id=row.id,
        run_id=run_id,
        observed_at=measured_at,
        payload=payload,
    )
    session.add(obs)
    row.latest_observed_at = measured_at
    row.updated_at = now
    row.manual_refresh_lease_until = None
    session.flush()

    cooldown = _cooldown_remaining_seconds(measured_at, now=now)
    return SavedVideoManualRefreshResult(
        item=row,
        capture_run_id=run_id,
        measured_at=measured_at,
        snapshot_id=snapshot.id,
        metrics_source="youtube_data_api",
        idempotent=capture_result.status == "duplicate",
        cooldown_seconds=cooldown if cooldown > 0 else int(MANUAL_REFRESH_COOLDOWN.total_seconds()),
    )
