"""Post-discovery T0 enrichment for validation candidates (Stage 1.8 Step 3)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from app.integrations.youtube.client import YouTubeVideoDetails
from app.services.metrics import ensure_utc
from app.services.radar_candidate import RadarCandidate

ContentFormat = Literal["regular", "short", "live", "unknown"]
EnrichmentStatus = Literal["ok", "partial", "failed"]

SHORT_DURATION_SECONDS = 60


class VideoDetailsClient(Protocol):
    def get_videos(self, video_ids: list[str]) -> list[YouTubeVideoDetails]:
        ...


def calc_age_hours_at_t0(
    discovered_at: datetime,
    published_at: datetime,
) -> float:
    """Hours between exact publish time and individual discovery timestamp."""
    discovered = ensure_utc(discovered_at)
    published = ensure_utc(published_at)
    return (discovered - published).total_seconds() / 3600.0


def calc_vph_at_t0(discovery_views: int, age_hours_at_t0: float | None) -> float | None:
    if age_hours_at_t0 is None or age_hours_at_t0 <= 0:
        return None
    return round(discovery_views / age_hours_at_t0, 2)


def calc_views_per_subscriber_at_t0(
    discovery_views: int,
    final_subscribers: int | None,
) -> float | None:
    if final_subscribers is None or final_subscribers <= 0:
        return None
    return round(discovery_views / final_subscribers, 2)


def classify_content_format(
    candidate: RadarCandidate,
    duration_seconds: int | None,
) -> ContentFormat:
    if candidate.is_live:
        return "live"
    if duration_seconds is not None and 0 < duration_seconds < SHORT_DURATION_SECONDS:
        return "short"
    if candidate.is_short:
        return "short"
    if duration_seconds is not None and duration_seconds >= SHORT_DURATION_SECONDS:
        return "regular"
    return "unknown"


def _apply_failed_enrichment(candidate: RadarCandidate) -> None:
    candidate.published_at = None
    candidate.age_hours_at_t0 = None
    candidate.vph_at_t0 = None
    candidate.views_per_subscriber_at_t0 = None
    candidate.duration_seconds = None
    candidate.content_format = classify_content_format(candidate, None)
    candidate.enrichment_status = "failed"


def enrich_single_candidate(
    candidate: RadarCandidate,
    details: YouTubeVideoDetails | None,
) -> None:
    """Apply API enrichment to one candidate without mutating discovery fields."""
    discovery_views = candidate.discovery_views
    discovered_at = candidate.discovered_at
    discovery_subscribers = candidate.discovery_subscribers
    discovery_published_text = candidate.discovery_published_text

    if details is None:
        _apply_failed_enrichment(candidate)
    else:
        candidate.published_at = details.published_at
        candidate.duration_seconds = details.duration_seconds
        candidate.content_format = classify_content_format(
            candidate,
            details.duration_seconds,
        )

        try:
            age_hours = calc_age_hours_at_t0(discovered_at, details.published_at)
        except Exception:
            age_hours = None

        candidate.age_hours_at_t0 = round(age_hours, 4) if age_hours is not None else None
        candidate.vph_at_t0 = calc_vph_at_t0(discovery_views, age_hours)
        candidate.views_per_subscriber_at_t0 = calc_views_per_subscriber_at_t0(
            discovery_views,
            candidate.final_subscribers,
        )

        has_published_at = details.published_at is not None
        has_duration = details.duration_seconds is not None
        has_valid_age = age_hours is not None and age_hours > 0

        if has_published_at and has_duration and has_valid_age:
            candidate.enrichment_status = "ok"
        elif has_published_at or has_duration:
            candidate.enrichment_status = "partial"
        else:
            candidate.enrichment_status = "failed"

    candidate.discovery_views = discovery_views
    candidate.discovered_at = discovered_at
    candidate.discovery_subscribers = discovery_subscribers
    candidate.discovery_published_text = discovery_published_text


def enrich_radar_candidates(
    candidates: list[RadarCandidate],
    youtube_client: VideoDetailsClient,
) -> dict[str, int]:
    """
    Fetch exact publish time and duration via YouTube Data API.

    Mutates enrichment fields only. Discovery T0 fields remain unchanged.
    Returns diagnostics including missing_video_count (requested but not returned).
    """
    if not candidates:
        return {"missing_video_count": 0}

    video_ids = list(dict.fromkeys(candidate.video_id for candidate in candidates if candidate.video_id))
    details_by_id: dict[str, YouTubeVideoDetails] = {}
    try:
        for details in youtube_client.get_videos(video_ids):
            details_by_id[details.video_id] = details
    except Exception:
        for candidate in candidates:
            _apply_failed_enrichment(candidate)
        return {"missing_video_count": 0}

    missing_video_count = 0
    for candidate in candidates:
        if candidate.video_id and candidate.video_id not in details_by_id:
            missing_video_count += 1
        enrich_single_candidate(candidate, details_by_id.get(candidate.video_id))

    return {"missing_video_count": missing_video_count}
