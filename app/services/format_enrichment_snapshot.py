"""Persist videos.list statistics as VideoSnapshot at enrichment time (bootstrap measurement)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.integrations.youtube.client import YouTubeVideoDetails
from app.models.orm import Video
from app.services.metrics import ensure_utc
from app.services.video_published_at import published_at_source_rank, PUBLISHED_AT_SOURCE_API
from app.services.video_snapshot_storage import (
    VideoSnapshotObservation,
    persist_video_snapshot,
)

FORMAT_ENRICHMENT_SNAPSHOT_SOURCE = "format_enrichment"


def format_enrichment_snapshot_run_id(video_id: str) -> str:
    return f"{FORMAT_ENRICHMENT_SNAPSHOT_SOURCE}:{video_id}"


def persist_format_enrichment_measurement(
    session: Session,
    *,
    video: Video,
    details: YouTubeVideoDetails,
    captured_at: datetime,
) -> tuple[bool, str]:
    """
    Insert one enrichment snapshot when API returned a definite viewCount.

    Returns (inserted, skip_reason). skip_reason is empty when inserted or duplicate.
    Idempotent: same (video_id, captured_at, source, run_id) → duplicate, not error.
    """
    if details.views_count is None:
        return False, "views_missing_from_api"

    channel_id = (details.channel_id or video.channel_id or "").strip()
    if not channel_id:
        return False, "missing_channel_id"

    pub = video.published_at
    pub_source = getattr(video, "published_at_source", None)
    if pub is not None and published_at_source_rank(pub_source) >= published_at_source_rank(
        PUBLISHED_AT_SOURCE_API,
    ):
        published_at = ensure_utc(pub)
    elif details.published_at is not None:
        published_at = ensure_utc(details.published_at)
    else:
        published_at = ensure_utc(pub) if pub is not None else None

    observation = VideoSnapshotObservation(
        video_id=video.id,
        channel_id=channel_id,
        captured_at=ensure_utc(captured_at),
        source=FORMAT_ENRICHMENT_SNAPSHOT_SOURCE,
        fetch_status="ok",
        run_id=format_enrichment_snapshot_run_id(video.id),
        published_at=published_at,
        views=int(details.views_count),
        likes=details.likes_count if details.likes_count is not None else None,
        comments=details.comments_count if details.comments_count is not None else None,
        raw_metadata={"measurement_kind": "format_enrichment_api"},
    )
    row, err, is_duplicate = persist_video_snapshot(session, observation)
    if err is not None:
        return False, f"validation:{err.message}"
    if row is None and is_duplicate:
        return False, "duplicate"
    return bool(row), ""
