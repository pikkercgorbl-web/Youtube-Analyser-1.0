"""Time-safe channel view baseline at T0 (Stage 1.10A)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

logger = logging.getLogger(__name__)

from app.integrations.youtube.client import ChannelVideoBrowseModel, YouTubeVideoDetails
from app.services.metrics import ensure_utc
from app.services.radar_candidate import RadarCandidate
from app.services.radar_candidate_analysis import _percentile
from app.services.radar_candidate_enrichment import SHORT_DURATION_SECONDS
from app.services.video_filter_service import parse_duration_text

BASELINE_SCHEMA_VERSION = "1.10A"
BASELINE_SOURCE = "innertube_videos_tab+youtube_videos_list"
VELOCITY_BASELINE_UNAVAILABLE = "unavailable"

DEFAULT_REQUESTED_HISTORY = 20
DEFAULT_MIN_USEFUL_HISTORY = 5
DEFAULT_TAB_FETCH_LIMIT = 60
DEFAULT_CHANNEL_REQUEST_DELAY_SECONDS = 0.25
DEFAULT_VALIDATION_MAX_PAGES_PER_CHANNEL = 6
DEFAULT_VALIDATION_MAX_SECONDS_PER_CHANNEL = 30.0
DEFAULT_VALIDATION_INNERTUBE_REQUEST_TIMEOUT = 15.0


@dataclass(frozen=True, slots=True)
class ChannelBaselineConfig:
    enabled: bool = True
    requested_history: int = DEFAULT_REQUESTED_HISTORY
    min_useful_history: int = DEFAULT_MIN_USEFUL_HISTORY
    tab_fetch_limit: int = DEFAULT_TAB_FETCH_LIMIT
    max_channel_requests: int | None = None
    channel_request_delay_seconds: float = DEFAULT_CHANNEL_REQUEST_DELAY_SECONDS
    max_pages_per_channel: int | None = None
    max_seconds_per_channel: float | None = None
    innertube_request_timeout: float | None = None


@dataclass
class ChannelBaselineRunStats:
    candidates: int = 0
    unique_channels: int = 0
    channel_baseline_requests: int = 0
    cache_hits: int = 0
    shorts_excluded: int = 0
    live_excluded: int = 0
    unknown_format_excluded: int = 0
    future_videos_excluded: int = 0
    candidate_self_excluded: int = 0
    excluded_future_tab_videos: int = 0
    retained_history_leakage_violations: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)
    runtime_seconds: float = 0.0
    channels_target_reached: int = 0
    channels_page_cap_reached: int = 0
    channels_timeout: int = 0
    channels_no_continuation: int = 0
    max_pages_observed: int = 0
    max_channel_elapsed_seconds: float = 0.0
    average_channel_elapsed_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class ChannelFetchMeta:
    pages_fetched: int = 0
    eligible_reference_count: int = 0
    excluded_short: int = 0
    excluded_live: int = 0
    excluded_future: int = 0
    elapsed_seconds: float = 0.0
    stop_reason: str = "no_continuation"
    fetch_status: str = "ok"


class ChannelBaselineClient(Protocol):
    async def get_channel_videos_tab(
        self,
        channel_id: str,
        *,
        max_results: int,
    ) -> tuple[str, list[ChannelVideoBrowseModel]]:
        ...

    async def iter_channel_videos_tab(
        self,
        channel_id: str,
        *,
        max_pages: int | None = None,
        request_timeout: float | None = None,
    ) -> AsyncIterator[list[ChannelVideoBrowseModel]]:
        ...

    def get_videos(self, video_ids: list[str]) -> list[YouTubeVideoDetails]:
        ...


@dataclass(frozen=True, slots=True)
class HistoryVideoRow:
    video_id: str
    views_count: int
    published_at: datetime
    duration_seconds: int | None
    content_format: str


def _is_live_browse(video: ChannelVideoBrowseModel) -> bool:
    blob = f"{video.duration_text} {video.published_text} {video.title}".upper()
    return "LIVE" in blob or "PREMIERE" in blob


def classify_history_format(
    *,
    duration_seconds: int | None,
    browse: ChannelVideoBrowseModel | None = None,
) -> str:
    if browse is not None and _is_live_browse(browse):
        return "live"
    if duration_seconds is None:
        return "unknown"
    if duration_seconds <= 0:
        if browse is not None and _is_live_browse(browse):
            return "live"
        return "unknown"
    if duration_seconds < SHORT_DURATION_SECONDS:
        return "short"
    return "regular"


def _ratio(numerator: float | int | None, denominator: float | int | None) -> float | None:
    if numerator is None or denominator is None:
        return None
    denom = float(denominator)
    if denom <= 0:
        return None
    return round(float(numerator) / denom, 4)


def compute_view_distribution(views: list[int]) -> dict[str, float | int | None]:
    if not views:
        return {
            "channel_history_count": 0,
            "channel_median_views": None,
            "channel_p75_views": None,
            "channel_p90_views": None,
            "channel_max_views": None,
        }
    sorted_views = sorted(float(v) for v in views)
    return {
        "channel_history_count": len(views),
        "channel_median_views": round(_percentile(sorted_views, 50), 4),
        "channel_p75_views": round(_percentile(sorted_views, 75), 4),
        "channel_p90_views": round(_percentile(sorted_views, 90), 4),
        "channel_max_views": int(max(views)),
    }


def build_eligible_history(
    *,
    browse_videos: list[ChannelVideoBrowseModel],
    details_by_id: dict[str, YouTubeVideoDetails],
    candidate_video_id: str,
    discovered_at: datetime,
    requested_count: int,
    exclusion_counts: dict[str, int],
) -> tuple[list[HistoryVideoRow], int]:
    """Filter channel uploads to time-safe regular history (no leakage)."""
    cutoff = ensure_utc(discovered_at)
    leakage = 0
    eligible: list[HistoryVideoRow] = []

    for browse in browse_videos:
        if browse.video_id == candidate_video_id:
            exclusion_counts["candidate_self_excluded"] = (
                exclusion_counts.get("candidate_self_excluded", 0) + 1
            )
            continue

        details = details_by_id.get(browse.video_id)
        duration = (
            details.duration_seconds
            if details is not None
            else parse_duration_text(browse.duration_text)
        )
        fmt = classify_history_format(duration_seconds=duration, browse=browse)
        if fmt == "short":
            exclusion_counts["shorts_excluded"] = exclusion_counts.get("shorts_excluded", 0) + 1
            continue
        if fmt == "live":
            exclusion_counts["live_excluded"] = exclusion_counts.get("live_excluded", 0) + 1
            continue
        if fmt == "unknown":
            exclusion_counts["unknown_format_excluded"] = (
                exclusion_counts.get("unknown_format_excluded", 0) + 1
            )
            continue

        if details is None or details.published_at is None:
            exclusion_counts["unknown_format_excluded"] = (
                exclusion_counts.get("unknown_format_excluded", 0) + 1
            )
            continue

        published_at = ensure_utc(details.published_at)
        if published_at >= cutoff:
            leakage += 1
            exclusion_counts["future_videos_excluded"] = (
                exclusion_counts.get("future_videos_excluded", 0) + 1
            )
            continue

        views = details.views_count if details.views_count > 0 else browse.views_count
        eligible.append(
            HistoryVideoRow(
                video_id=browse.video_id,
                views_count=max(0, views),
                published_at=published_at,
                duration_seconds=duration,
                content_format=fmt,
            ),
        )

    eligible.sort(key=lambda row: row.published_at, reverse=True)
    return eligible[:requested_count], leakage


def resolve_baseline_status(
    *,
    eligible_count: int,
    requested_count: int,
    min_useful: int,
    fetch_failed: bool,
    channel_missing: bool,
) -> str:
    if fetch_failed:
        return "failed"
    if channel_missing:
        return "channel_unavailable"
    if eligible_count < min_useful:
        return "insufficient_history"
    if eligible_count < requested_count:
        return "partial"
    return "ok"


def build_candidate_baseline_features(
    *,
    candidate: RadarCandidate,
    eligible_history: list[HistoryVideoRow],
    config: ChannelBaselineConfig,
    status: str,
    found_count: int,
    leakage_count: int,
    collected_at: datetime,
) -> dict[str, Any]:
    views = [row.views_count for row in eligible_history]
    distribution = compute_view_distribution(views)
    candidate_views = candidate.discovery_views
    median = distribution["channel_median_views"]
    p75 = distribution["channel_p75_views"]

    subs = candidate.final_subscribers
    if subs is None:
        subs = candidate.discovery_subscribers or None
    subscriber_status = candidate.subscriber_fetch_status or (
        "discovery" if candidate.discovery_subscribers else "unavailable"
    )

    return {
        "channel_baseline_status": status,
        "channel_baseline_requested_count": config.requested_history,
        "channel_baseline_found_count": found_count,
        "channel_baseline_eligible_count": len(eligible_history),
        "channel_baseline_leakage_violations": leakage_count,
        "channel_history_count": distribution["channel_history_count"],
        "channel_median_views": median,
        "channel_p75_views": p75,
        "channel_p90_views": distribution["channel_p90_views"],
        "channel_max_views": distribution["channel_max_views"],
        "views_vs_channel_median": _ratio(candidate_views, median),
        "views_vs_channel_p75": _ratio(candidate_views, p75),
        "channel_median_early_vph": None,
        "channel_p75_early_vph": None,
        "channel_p90_early_vph": None,
        "vph_vs_channel_median": None,
        "vph_vs_channel_p75": None,
        "velocity_baseline_status": VELOCITY_BASELINE_UNAVAILABLE,
        "channel_subscribers_at_t0": subs,
        "subscriber_status": subscriber_status,
        "channel_baseline_source": BASELINE_SOURCE,
        "channel_baseline_collected_at": collected_at.isoformat(),
        "channel_baseline_history_cutoff": ensure_utc(candidate.discovered_at).isoformat(),
        "channel_view_baseline_available": len(views) >= config.min_useful_history,
        "channel_velocity_baseline_available": False,
    }


def apply_baseline_features_to_candidate(candidate: RadarCandidate, features: dict[str, Any]) -> None:
    for key, value in features.items():
        setattr(candidate, key, value)


def assert_leakage_invariant(history: list[HistoryVideoRow], discovered_at: datetime) -> int:
    cutoff = ensure_utc(discovered_at)
    violations = sum(1 for row in history if row.published_at >= cutoff)
    return violations


@dataclass
class _ChannelCacheEntry:
    browse_videos: list[ChannelVideoBrowseModel]
    details_by_id: dict[str, YouTubeVideoDetails]
    fetch_failed: bool = False
    fetch_meta: ChannelFetchMeta | None = None


def _channel_fetch_status(
    *,
    eligible_count: int,
    requested_count: int,
    min_useful: int,
    fetch_failed: bool,
) -> str:
    if fetch_failed:
        return "failed"
    if eligible_count < min_useful:
        return "insufficient_history"
    if eligible_count < requested_count:
        return "partial"
    return "ok"


def _log_channel_baseline(
    *,
    channel_id: str,
    meta: ChannelFetchMeta,
) -> None:
    logger.info(
        "[CHANNEL_BASELINE] channel=%s pages=%s eligible=%s excluded_short=%s "
        "excluded_live=%s excluded_future=%s elapsed=%.1fs status=%s stop=%s",
        channel_id,
        meta.pages_fetched,
        meta.eligible_reference_count,
        meta.excluded_short,
        meta.excluded_live,
        meta.excluded_future,
        meta.elapsed_seconds,
        meta.fetch_status,
        meta.stop_reason,
    )


def _aggregate_channel_fetch_stats(
    stats: ChannelBaselineRunStats,
    meta: ChannelFetchMeta,
) -> None:
    stats.max_pages_observed = max(stats.max_pages_observed, meta.pages_fetched)
    stats.max_channel_elapsed_seconds = max(
        stats.max_channel_elapsed_seconds,
        meta.elapsed_seconds,
    )
    reason = meta.stop_reason
    if reason == "target_reached":
        stats.channels_target_reached += 1
    elif reason == "page_cap":
        stats.channels_page_cap_reached += 1
    elif reason == "channel_timeout":
        stats.channels_timeout += 1
    elif reason == "no_continuation":
        stats.channels_no_continuation += 1


async def _fetch_channel_cache_entry(
    client: ChannelBaselineClient,
    channel_id: str,
    *,
    tab_fetch_limit: int,
    config: ChannelBaselineConfig,
    reference_candidate: RadarCandidate | None,
) -> _ChannelCacheEntry:
    iter_fn = getattr(client, "iter_channel_videos_tab", None)
    if iter_fn is None:
        try:
            _, browse_videos = await client.get_channel_videos_tab(
                channel_id,
                max_results=tab_fetch_limit,
            )
        except Exception:
            return _ChannelCacheEntry(browse_videos=[], details_by_id={}, fetch_failed=True)

        video_ids = [video.video_id for video in browse_videos]
        details_list = await asyncio.to_thread(client.get_videos, video_ids)
        details_by_id = {item.video_id: item for item in details_list}
        return _ChannelCacheEntry(browse_videos=browse_videos, details_by_id=details_by_id)

    started_mono = time.monotonic()
    browse_videos: list[ChannelVideoBrowseModel] = []
    details_by_id: dict[str, YouTubeVideoDetails] = {}
    seen_ids: set[str] = set()
    pages_fetched = 0
    stop_reason = "no_continuation"
    fetch_failed = False
    per_page_exclusions: dict[str, int] = {}
    eligible_reference: list[HistoryVideoRow] = []

    def _elapsed() -> float:
        return time.monotonic() - started_mono

    def _timeout_exceeded() -> bool:
        limit = config.max_seconds_per_channel
        return limit is not None and _elapsed() > limit

    try:
        page_iter = iter_fn(
            channel_id,
            max_pages=None,
            request_timeout=config.innertube_request_timeout,
        )
        async for page_videos in page_iter:
            if _timeout_exceeded():
                stop_reason = "channel_timeout"
                logger.info(
                    "[CHANNEL_BASELINE] channel=%s stop=channel_timeout elapsed=%.1fs",
                    channel_id,
                    _elapsed(),
                )
                break

            pages_fetched += 1
            new_ids: list[str] = []
            for video in page_videos:
                if video.video_id in seen_ids:
                    continue
                seen_ids.add(video.video_id)
                browse_videos.append(video)
                new_ids.append(video.video_id)
                if len(browse_videos) >= tab_fetch_limit:
                    stop_reason = "tab_fetch_limit"
                    break

            if new_ids:
                details_list = await asyncio.to_thread(client.get_videos, new_ids)
                for item in details_list:
                    details_by_id[item.video_id] = item

            if _timeout_exceeded():
                stop_reason = "channel_timeout"
                break

            if reference_candidate is not None:
                per_page_exclusions = {}
                eligible_reference, _ = build_eligible_history(
                    browse_videos=browse_videos,
                    details_by_id=details_by_id,
                    candidate_video_id=reference_candidate.video_id,
                    discovered_at=reference_candidate.discovered_at,
                    requested_count=config.requested_history,
                    exclusion_counts=per_page_exclusions,
                )
                if len(eligible_reference) >= config.requested_history:
                    stop_reason = "target_reached"
                    logger.info(
                        "[CHANNEL_BASELINE] channel=%s stop=target_reached eligible=%s",
                        channel_id,
                        len(eligible_reference),
                    )
                    break

            if len(browse_videos) >= tab_fetch_limit:
                break

            if (
                config.max_pages_per_channel is not None
                and pages_fetched >= config.max_pages_per_channel
            ):
                stop_reason = "page_cap"
                logger.info(
                    "[CHANNEL_BASELINE] channel=%s stop=page_cap pages=%s",
                    channel_id,
                    pages_fetched,
                )
                break
    except Exception:
        fetch_failed = True
        stop_reason = "fetch_error"
        logger.info(
            "[CHANNEL_BASELINE] channel=%s stop=fetch_error elapsed=%.1fs",
            channel_id,
            _elapsed(),
        )

    elapsed = _elapsed()
    fetch_status = _channel_fetch_status(
        eligible_count=len(eligible_reference),
        requested_count=config.requested_history,
        min_useful=config.min_useful_history,
        fetch_failed=fetch_failed and not browse_videos,
    )
    meta = ChannelFetchMeta(
        pages_fetched=pages_fetched,
        eligible_reference_count=len(eligible_reference),
        excluded_short=per_page_exclusions.get("shorts_excluded", 0),
        excluded_live=per_page_exclusions.get("live_excluded", 0),
        excluded_future=per_page_exclusions.get("future_videos_excluded", 0),
        elapsed_seconds=round(elapsed, 2),
        stop_reason=stop_reason,
        fetch_status=fetch_status,
    )
    _log_channel_baseline(channel_id=channel_id, meta=meta)

    return _ChannelCacheEntry(
        browse_videos=browse_videos,
        details_by_id=details_by_id,
        fetch_failed=fetch_failed and not browse_videos,
        fetch_meta=meta,
    )


async def collect_channel_baselines_for_candidates(
    candidates: list[RadarCandidate],
    client: ChannelBaselineClient,
    *,
    config: ChannelBaselineConfig | None = None,
) -> ChannelBaselineRunStats:
    """Attach channel view baselines to candidates (validation / pilot only)."""
    cfg = config or ChannelBaselineConfig()
    stats = ChannelBaselineRunStats(candidates=len(candidates))
    if not cfg.enabled:
        return stats

    started = datetime.now(timezone.utc)
    cache: dict[str, _ChannelCacheEntry] = {}
    channel_ids_ordered: list[str] = []
    seen_channels: set[str] = set()
    for candidate in candidates:
        channel_id = (candidate.channel_id or "").strip()
        if not channel_id or channel_id in seen_channels:
            continue
        seen_channels.add(channel_id)
        channel_ids_ordered.append(channel_id)
    stats.unique_channels = len(channel_ids_ordered)

    local_exclusions = {
        "shorts_excluded": 0,
        "live_excluded": 0,
        "unknown_format_excluded": 0,
        "future_videos_excluded": 0,
        "candidate_self_excluded": 0,
    }

    requests_made = 0
    channel_elapsed_samples: list[float] = []
    for candidate in candidates:
        channel_id = (candidate.channel_id or "").strip()
        if not channel_id:
            features = build_candidate_baseline_features(
                candidate=candidate,
                eligible_history=[],
                config=cfg,
                status="channel_unavailable",
                found_count=0,
                leakage_count=0,
                collected_at=datetime.now(timezone.utc),
            )
            apply_baseline_features_to_candidate(candidate, features)
            stats.status_counts["channel_unavailable"] = (
                stats.status_counts.get("channel_unavailable", 0) + 1
            )
            continue

        if channel_id not in cache:
            if cfg.max_channel_requests is not None and requests_made >= cfg.max_channel_requests:
                features = build_candidate_baseline_features(
                    candidate=candidate,
                    eligible_history=[],
                    config=cfg,
                    status="failed",
                    found_count=0,
                    leakage_count=0,
                    collected_at=datetime.now(timezone.utc),
                )
                apply_baseline_features_to_candidate(candidate, features)
                stats.status_counts["failed"] = stats.status_counts.get("failed", 0) + 1
                continue

            cache[channel_id] = await _fetch_channel_cache_entry(
                client,
                channel_id,
                tab_fetch_limit=cfg.tab_fetch_limit,
                config=cfg,
                reference_candidate=candidate,
            )
            requests_made += 1
            stats.channel_baseline_requests += 1
            if cache[channel_id].fetch_meta is not None:
                _aggregate_channel_fetch_stats(stats, cache[channel_id].fetch_meta)  # type: ignore[arg-type]
                channel_elapsed_samples.append(cache[channel_id].fetch_meta.elapsed_seconds)  # type: ignore[union-attr]
            if cfg.channel_request_delay_seconds > 0:
                await asyncio.sleep(cfg.channel_request_delay_seconds)
        else:
            stats.cache_hits += 1

        entry = cache[channel_id]
        per_candidate_exclusions: dict[str, int] = {}
        eligible, leakage = build_eligible_history(
            browse_videos=entry.browse_videos,
            details_by_id=entry.details_by_id,
            candidate_video_id=candidate.video_id,
            discovered_at=candidate.discovered_at,
            requested_count=cfg.requested_history,
            exclusion_counts=per_candidate_exclusions,
        )
        for key, value in per_candidate_exclusions.items():
            local_exclusions[key] = local_exclusions.get(key, 0) + value
        stats.excluded_future_tab_videos += leakage
        stats.retained_history_leakage_violations += assert_leakage_invariant(
            eligible,
            candidate.discovered_at,
        )

        status = resolve_baseline_status(
            eligible_count=len(eligible),
            requested_count=cfg.requested_history,
            min_useful=cfg.min_useful_history,
            fetch_failed=entry.fetch_failed,
            channel_missing=not entry.browse_videos and not entry.fetch_failed,
        )
        features = build_candidate_baseline_features(
            candidate=candidate,
            eligible_history=eligible,
            config=cfg,
            status=status,
            found_count=len(entry.browse_videos),
            leakage_count=leakage,
            collected_at=datetime.now(timezone.utc),
        )
        apply_baseline_features_to_candidate(candidate, features)
        stats.status_counts[status] = stats.status_counts.get(status, 0) + 1

    stats.shorts_excluded = local_exclusions["shorts_excluded"]
    stats.live_excluded = local_exclusions["live_excluded"]
    stats.unknown_format_excluded = local_exclusions["unknown_format_excluded"]
    stats.future_videos_excluded = local_exclusions["future_videos_excluded"]
    stats.candidate_self_excluded = local_exclusions["candidate_self_excluded"]
    stats.runtime_seconds = (datetime.now(timezone.utc) - started).total_seconds()
    if channel_elapsed_samples:
        stats.average_channel_elapsed_seconds = round(
            sum(channel_elapsed_samples) / len(channel_elapsed_samples),
            2,
        )
    return stats


def build_pilot_quality_report(
    *,
    keyword: str,
    candidates: list[RadarCandidate],
    stats: ChannelBaselineRunStats,
) -> dict[str, Any]:
    history_counts: list[int] = []
    views_baseline_ok = 0
    relative_views_ok = 0
    velocity_ok = 0

    for candidate in candidates:
        count = getattr(candidate, "channel_history_count", None)
        if count is not None:
            history_counts.append(int(count))
        if getattr(candidate, "channel_view_baseline_available", False):
            views_baseline_ok += 1
        if getattr(candidate, "views_vs_channel_median", None) is not None:
            relative_views_ok += 1
        if getattr(candidate, "channel_velocity_baseline_available", False):
            velocity_ok += 1

    sorted_counts = sorted(float(c) for c in history_counts)
    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "keyword": keyword,
        "candidate_count": len(candidates),
        "unique_channels": stats.unique_channels,
        "baseline_status_counts": dict(sorted(stats.status_counts.items())),
        "median_history_count": round(_percentile(sorted_counts, 50), 4) if sorted_counts else None,
        "p10_history_count": round(_percentile(sorted_counts, 10), 4) if sorted_counts else None,
        "p50_history_count": round(_percentile(sorted_counts, 50), 4) if sorted_counts else None,
        "p90_history_count": round(_percentile(sorted_counts, 90), 4) if sorted_counts else None,
        "views_baseline_coverage": views_baseline_ok,
        "relative_views_coverage": relative_views_ok,
        "velocity_baseline_coverage": velocity_ok,
        "velocity_baseline_note": (
            "Channel view baseline is available. Comparable historical velocity baseline "
            "is not yet available (no time-safe early-age snapshots for past uploads)."
        ),
        "cache_hits": stats.cache_hits,
        "channel_baseline_requests": stats.channel_baseline_requests,
        "runtime_seconds": round(stats.runtime_seconds, 2),
        "excluded_future_tab_videos": stats.excluded_future_tab_videos,
        "retained_history_leakage_violations": stats.retained_history_leakage_violations,
        "leakage_violations": stats.retained_history_leakage_violations,
        "format_exclusions": {
            "shorts_excluded": stats.shorts_excluded,
            "live_excluded": stats.live_excluded,
            "unknown_format_excluded": stats.unknown_format_excluded,
            "future_videos_excluded": stats.future_videos_excluded,
            "candidate_self_excluded": stats.candidate_self_excluded,
        },
        "channel_fetch_guards": {
            "channels_target_reached": stats.channels_target_reached,
            "channels_page_cap_reached": stats.channels_page_cap_reached,
            "channels_timeout": stats.channels_timeout,
            "channels_no_continuation": stats.channels_no_continuation,
            "max_pages_observed": stats.max_pages_observed,
            "max_channel_elapsed_seconds": stats.max_channel_elapsed_seconds,
            "average_channel_elapsed_seconds": stats.average_channel_elapsed_seconds,
        },
    }
