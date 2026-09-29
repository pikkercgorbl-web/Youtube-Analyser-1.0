"""In-memory radar candidate representation for one keyword scan (Stage 1.1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from app.integrations.youtube.client import VideoSearchModel
from app.services.metrics import utc_now

QualificationState = Literal["pending", "passed", "rejected", "parse_error"]
DiscoverySource = Literal["innertube", "html_fallback"]
SubscriberFetchStatus = Literal[
    "discovery",
    "homepage_fetched",
    "unavailable",
    "not_attempted",
]
ContentFormat = Literal["regular", "short", "live", "unknown"]
EnrichmentStatus = Literal["ok", "partial", "failed"]

QUALIFICATION_PENDING: QualificationState = "pending"
QUALIFICATION_PASSED: QualificationState = "passed"
QUALIFICATION_REJECTED: QualificationState = "rejected"
QUALIFICATION_PARSE_ERROR: QualificationState = "parse_error"

DISCOVERY_SOURCE_INNERTUBE: DiscoverySource = "innertube"
DISCOVERY_SOURCE_HTML_FALLBACK: DiscoverySource = "html_fallback"


@dataclass
class RadarCandidate:
    """A format-passing discovered video eligible for existing qualification."""

    video_id: str
    channel_id: str
    keyword: str
    discovery_source: DiscoverySource
    discovered_at: datetime
    video_title: str
    channel_title: str
    discovery_views: int = 0
    discovery_subscribers: int = 0
    discovery_published_text: str = ""
    published_text: str = ""
    views: int = 0
    subscribers: int | None = None
    is_short: bool = False
    is_live: bool = False
    content_renderer: str = "videoRenderer"
    format_passed: bool = True
    final_subscribers: int | None = None
    subscriber_fetch_status: SubscriberFetchStatus | None = None
    published_at: datetime | None = None
    age_hours_at_t0: float | None = None
    vph_at_t0: float | None = None
    views_per_subscriber_at_t0: float | None = None
    duration_seconds: int | None = None
    content_format: ContentFormat | None = None
    enrichment_status: EnrichmentStatus | None = None
    qualification_state: QualificationState = QUALIFICATION_PENDING
    first_failure_reason: str | None = None
    viral_coefficient: float | None = None
    vph: float | None = None
    video_age_days: float | None = None
    # Stage 1.10A channel baseline (validation T0 only; unset when baseline disabled)
    channel_baseline_status: str | None = None
    channel_baseline_requested_count: int | None = None
    channel_baseline_found_count: int | None = None
    channel_baseline_eligible_count: int | None = None
    channel_baseline_leakage_violations: int | None = None
    channel_history_count: int | None = None
    channel_median_views: float | None = None
    channel_p75_views: float | None = None
    channel_p90_views: float | None = None
    channel_max_views: float | None = None
    views_vs_channel_median: float | None = None
    views_vs_channel_p75: float | None = None
    channel_median_early_vph: float | None = None
    channel_p75_early_vph: float | None = None
    channel_p90_early_vph: float | None = None
    vph_vs_channel_median: float | None = None
    vph_vs_channel_p75: float | None = None
    velocity_baseline_status: str | None = None
    channel_subscribers_at_t0: int | None = None
    subscriber_status: str | None = None
    channel_baseline_source: str | None = None
    channel_baseline_collected_at: str | None = None
    channel_baseline_history_cutoff: str | None = None
    channel_view_baseline_available: bool | None = None
    channel_velocity_baseline_available: bool | None = None

    def __post_init__(self) -> None:
        """Mirror legacy fields for callers that still construct candidates directly."""
        if self.views == 0 and self.discovery_views > 0:
            self.views = self.discovery_views
        elif self.discovery_views == 0 and self.views > 0:
            self.discovery_views = self.views
        if self.subscribers is None and self.discovery_subscribers > 0:
            self.subscribers = self.discovery_subscribers
        elif self.discovery_subscribers == 0 and self.subscribers not in (None, 0):
            self.discovery_subscribers = int(self.subscribers or 0)
        if not self.discovery_published_text and self.published_text:
            self.discovery_published_text = self.published_text
        elif not self.published_text and self.discovery_published_text:
            self.published_text = self.discovery_published_text

    @classmethod
    def from_video_search(
        cls,
        video: VideoSearchModel,
        *,
        keyword: str,
        discovery_source: DiscoverySource,
        discovered_at: datetime | None = None,
    ) -> RadarCandidate:
        discovery_views = max(video.views_count, 0)
        discovery_subscribers = max(video.subscribers_count, 0)
        discovery_published_text = video.published_text
        return cls(
            video_id=video.video_id,
            channel_id=video.channel_id,
            keyword=keyword,
            discovery_source=discovery_source,
            discovered_at=discovered_at or utc_now(),
            video_title=video.title,
            channel_title=video.channel_title or "",
            discovery_views=discovery_views,
            discovery_subscribers=discovery_subscribers,
            discovery_published_text=discovery_published_text,
            published_text=discovery_published_text,
            views=discovery_views,
            subscribers=discovery_subscribers,
            is_short=video.is_short,
            is_live=video.is_live,
            content_renderer=video.content_renderer,
        )


def apply_signal_snapshot(candidate: RadarCandidate) -> None:
    """Calculate observability signals from raw candidate fields (Stage 1.2)."""
    try:
        subscribers = candidate.subscribers
        if subscribers is not None and subscribers > 0:
            candidate.viral_coefficient = round(candidate.views / subscribers, 2)
        else:
            candidate.viral_coefficient = None
    except Exception:
        candidate.viral_coefficient = None

    try:
        from app.services.explosive_channels_service import calc_vph_from_published_text

        candidate.vph = calc_vph_from_published_text(
            candidate.views,
            candidate.published_text,
        )
    except Exception:
        candidate.vph = None

    try:
        from app.services.video_filter_service import parse_relative_time_to_days

        age_days = parse_relative_time_to_days(candidate.published_text)
        candidate.video_age_days = float(age_days) if age_days >= 0 else None
    except Exception:
        candidate.video_age_days = None


@dataclass(frozen=True, slots=True)
class RadarVideoOutcome:
    """Qualification result for one candidate video."""

    video_id: str
    qualification_state: QualificationState
    first_failure_reason: str | None = None


def apply_video_outcomes(
    candidates: list[RadarCandidate],
    outcomes: list[RadarVideoOutcome],
) -> None:
    """Attach qualification outcomes to candidates matched by video_id."""
    by_video_id = {candidate.video_id: candidate for candidate in candidates}
    for outcome in outcomes:
        candidate = by_video_id.get(outcome.video_id)
        if candidate is None:
            continue
        candidate.qualification_state = outcome.qualification_state
        candidate.first_failure_reason = outcome.first_failure_reason


def apply_subscriber_enrichment(
    candidates: list[RadarCandidate],
    subscriber_cache: dict[str, int | None],
) -> None:
    """
    Attach final subscriber values from qualification enrichment cache.

    Does not mutate immutable discovery fields or qualification outcomes.
    """
    for candidate in candidates:
        if candidate.discovery_subscribers > 0:
            candidate.final_subscribers = candidate.discovery_subscribers
            candidate.subscriber_fetch_status = "discovery"
            continue

        channel_id = candidate.channel_id
        if not channel_id:
            candidate.final_subscribers = None
            candidate.subscriber_fetch_status = "unavailable"
            continue

        if channel_id not in subscriber_cache:
            candidate.final_subscribers = None
            candidate.subscriber_fetch_status = "not_attempted"
            continue

        fetched = subscriber_cache.get(channel_id)
        if fetched is not None and fetched > 0:
            candidate.final_subscribers = fetched
            candidate.subscriber_fetch_status = "homepage_fetched"
        else:
            candidate.final_subscribers = None
            candidate.subscriber_fetch_status = "unavailable"


def build_candidate_summary(
    keyword: str,
    candidates: list[RadarCandidate],
) -> dict[str, Any]:
    """Aggregate candidate qualification states for structured logging."""
    passed_count = 0
    rejected_count = 0
    parse_error_count = 0
    pending_count = 0
    rejection_reasons: dict[str, int] = {}

    for candidate in candidates:
        if candidate.qualification_state == QUALIFICATION_PASSED:
            passed_count += 1
        elif candidate.qualification_state == QUALIFICATION_PARSE_ERROR:
            parse_error_count += 1
        elif candidate.qualification_state == QUALIFICATION_REJECTED:
            rejected_count += 1
            if candidate.first_failure_reason:
                reason = candidate.first_failure_reason
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
        else:
            pending_count += 1

    signal_availability = {
        "viral_coefficient": 0,
        "vph": 0,
        "video_age_days": 0,
    }
    signal_ranges: dict[str, dict[str, float]] = {}

    for candidate in candidates:
        for signal_name in ("viral_coefficient", "vph", "video_age_days"):
            value = getattr(candidate, signal_name)
            if value is None:
                continue
            signal_availability[signal_name] += 1
            bounds = signal_ranges.setdefault(signal_name, {"min": value, "max": value})
            bounds["min"] = min(bounds["min"], value)
            bounds["max"] = max(bounds["max"], value)

    summary: dict[str, Any] = {
        "keyword": keyword,
        "candidate_count": len(candidates),
        "passed_count": passed_count,
        "rejected_count": rejected_count,
        "parse_error_count": parse_error_count,
        "rejection_reasons": dict(sorted(rejection_reasons.items())),
        "signal_availability": signal_availability,
    }
    if signal_ranges:
        summary["signal_ranges"] = {
            name: dict(sorted(bounds.items()))
            for name, bounds in sorted(signal_ranges.items())
        }

    rejected_samples: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate.qualification_state != QUALIFICATION_REJECTED:
            continue
        if candidate.viral_coefficient is None and candidate.vph is None:
            continue
        rejected_samples.append(
            {
                "video_id": candidate.video_id,
                "views": candidate.views,
                "subscribers": candidate.subscribers,
                "viral_coefficient": candidate.viral_coefficient,
                "vph": candidate.vph,
                "video_age_days": candidate.video_age_days,
                "first_failure_reason": candidate.first_failure_reason,
            },
        )
        if len(rejected_samples) >= 5:
            break
    if rejected_samples:
        summary["rejected_signal_samples"] = rejected_samples

    if pending_count:
        summary["pending_count"] = pending_count
    return summary
