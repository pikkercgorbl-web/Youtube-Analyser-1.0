"""Persisted videos.list format confirmation for publishable Radar targets (Stage 2.3)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import VideoFormat, VideoFormatEnrichmentAttempt
from app.services.historical_video_format_verification import OUTCOME_CONFIRMED_REGULAR

_PUBLISHABLE_OUTCOMES = frozenset({OUTCOME_CONFIRMED_REGULAR})


def load_api_format_confirmed_video_ids(
    session: Session,
    video_ids: list[str] | tuple[str, ...] | None = None,
) -> frozenset[str]:
    stmt = select(VideoFormatEnrichmentAttempt.video_id).where(
        VideoFormatEnrichmentAttempt.last_outcome.in_(_PUBLISHABLE_OUTCOMES),
    )
    if video_ids:
        stmt = stmt.where(VideoFormatEnrichmentAttempt.video_id.in_(list(video_ids)))
    return frozenset(session.scalars(stmt).all())


def video_format_publishable(
    *,
    content_format: VideoFormat,
    video_id: str,
    confirmed_ids: frozenset[str],
) -> bool:
    if content_format in (VideoFormat.SHORT, VideoFormat.LIVE, VideoFormat.UNKNOWN):
        return False
    if content_format in (VideoFormat.MEDIUM, VideoFormat.LONG):
        return video_id in confirmed_ids
    return False


def filter_publishable_winner_video_ids(
    session: Session,
    winner_video_ids: list[str],
    *,
    content_format_by_id: dict[str, VideoFormat],
) -> frozenset[str]:
    confirmed = load_api_format_confirmed_video_ids(session, winner_video_ids)
    return frozenset(
        vid
        for vid in winner_video_ids
        if video_format_publishable(
            content_format=content_format_by_id[vid],
            video_id=vid,
            confirmed_ids=confirmed,
        )
    )


def video_id_publishable_with_confirmed_set(
    *,
    content_format: VideoFormat,
    video_id: str,
    confirmed_ids: frozenset[str],
) -> bool:
    """Radar MEDIUM/LONG targets require persisted confirmed_regular."""
    return video_format_publishable(
        content_format=content_format,
        video_id=video_id,
        confirmed_ids=confirmed_ids,
    )
