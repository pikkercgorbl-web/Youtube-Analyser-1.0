"""Published-at provenance and merge policy for Video rows."""

from __future__ import annotations

from datetime import datetime

from app.models.orm import Video
from app.services.metrics import ensure_utc

PUBLISHED_AT_SOURCE_INNERTUBE = "innertube_relative"
PUBLISHED_AT_SOURCE_API = "api_snippet"

_SOURCE_RANK = {
    PUBLISHED_AT_SOURCE_INNERTUBE: 0,
    PUBLISHED_AT_SOURCE_API: 1,
}


def published_at_source_rank(source: str | None) -> int:
    if not source:
        return _SOURCE_RANK[PUBLISHED_AT_SOURCE_INNERTUBE]
    return _SOURCE_RANK.get(source, _SOURCE_RANK[PUBLISHED_AT_SOURCE_INNERTUBE])


def published_at_usable_for_momentum(video: Video) -> bool:
    """Channel Momentum age-aligned VPH requires API snippet precision."""
    return published_at_source_rank(getattr(video, "published_at_source", None)) >= _SOURCE_RANK[
        PUBLISHED_AT_SOURCE_API
    ]


def apply_innertube_published_at(video: Video, published_at: datetime) -> None:
    """Set publish time from InnerTube relative text (approximate)."""
    incoming = ensure_utc(published_at)
    existing_rank = published_at_source_rank(getattr(video, "published_at_source", None))
    if existing_rank >= _SOURCE_RANK[PUBLISHED_AT_SOURCE_API]:
        return
    video.published_at = incoming
    video.published_at_source = PUBLISHED_AT_SOURCE_INNERTUBE


def apply_api_published_at(video: Video, published_at: datetime) -> None:
    """Set publish time from videos.list snippet.publishedAt (exact)."""
    video.published_at = ensure_utc(published_at)
    video.published_at_source = PUBLISHED_AT_SOURCE_API
