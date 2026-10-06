"""Single-keyword discovery scan for automatic cycles (Stage 1.15A)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.integrations.youtube.client import (
    VideoSearchModel,
    YouTubeApiError,
    filter_radar_videos_by_format,
    iter_radar_search_pages,
)
from app.integrations.youtube.innertube_metrics import InnerTubeMetrics
from app.services.explosive_channels_radar_worker import (
    MAX_PAGES,
    SEARCH_PAGE_DELAY_SECONDS,
    TARGET_VIDEOS_COUNT,
    get_radar_blacklist_words,
    get_radar_content_filters,
)
from app.services.explosive_channels_service import ExplosiveChannelsService
from app.services.radar_qualification_context import load_radar_qualification_context
from app.services.radar_candidate import (
    DISCOVERY_SOURCE_HTML_FALLBACK,
    DISCOVERY_SOURCE_INNERTUBE,
    QUALIFICATION_PASSED,
    QUALIFICATION_REJECTED,
    RadarCandidate,
    apply_signal_snapshot,
    apply_subscriber_enrichment,
    apply_video_outcomes,
)
from app.services.radar_filter_metrics import RadarFilterMetrics

logger = logging.getLogger(__name__)


@dataclass
class KeywordDiscoveryScanResult:
    keyword: str
    keyword_id: int | None = None
    started_at: float = 0.0
    finished_at: float = 0.0
    pages_scanned: int = 0
    raw_candidate_count: int = 0
    unique_videos: list[VideoSearchModel] = field(default_factory=list)
    candidates: list[RadarCandidate] = field(default_factory=list)
    qualification_passed_count: int = 0
    qualification_rejected_count: int = 0
    explosive_hits: int = 0
    error: str | None = None
    filter_metrics_summary: dict[str, int | dict[str, int]] = field(default_factory=dict)
    innertube_metrics_summary: dict[str, int | float] = field(default_factory=dict)
    profile_phase_seconds: dict[str, float] = field(default_factory=dict)


async def scan_keyword_for_discovery(
    session: Session,
    *,
    keyword: str,
    keyword_id: int | None = None,
    upload_period: str,
    register_explosive_channels: bool = True,
    max_pages: int = MAX_PAGES,
    search_page_delay_seconds: float = SEARCH_PAGE_DELAY_SECONDS,
) -> KeywordDiscoveryScanResult:
    """Run InnerTube discovery for one keyword; optional ExplosiveChannel registration."""
    started = time.perf_counter()
    result = KeywordDiscoveryScanResult(
        keyword=keyword,
        keyword_id=keyword_id,
        started_at=started,
    )
    service = ExplosiveChannelsService()
    qualification_context = load_radar_qualification_context(session, upload_period=upload_period)
    innertube_metrics = InnerTubeMetrics.empty()
    filter_metrics = RadarFilterMetrics.empty()
    subscriber_cache: dict[str, int | None] = {}
    unique_by_id: dict[str, VideoSearchModel] = {}
    keyword_candidates: list[RadarCandidate] = []
    phase_seconds: dict[str, float] = {
        "fetch": 0.0,
        "parse": 0.0,
        "qualification": 0.0,
        "channel_enrichment": 0.0,
        "database": 0.0,
        "other": 0.0,
        "channel_homepage_fetches": 0.0,
    }
    from app.services.discovery_cycle_profiling import active_profiler

    profiler = active_profiler()
    sql_count_before = profiler.sql_statement_count() if profiler else 0

    try:
        next_fetch_at = time.perf_counter()
        async for page_batch in iter_radar_search_pages(
            keyword,
            sort_by_upload_date=True,
            max_pages=max_pages,
            innertube_metrics=innertube_metrics,
        ):
            phase_seconds["fetch"] += time.perf_counter() - next_fetch_at
            parse_started = time.perf_counter()
            result.pages_scanned += 1
            page_videos = page_batch.videos
            filter_metrics.record_discovered(len(page_videos))
            if page_batch.renderer_counts.get("htmlFallback", 0) > 0:
                filter_metrics.record_html_fallback()

            content_filters = get_radar_content_filters()
            filtered_videos = filter_radar_videos_by_format(page_videos, content_filters)
            filter_metrics.record_format_skip(len(page_videos) - len(filtered_videos))

            if not filtered_videos:
                phase_seconds["parse"] += time.perf_counter() - parse_started
                if result.pages_scanned >= max_pages:
                    break
                delay_started = time.perf_counter()
                await asyncio.sleep(search_page_delay_seconds)
                phase_seconds["other"] += time.perf_counter() - delay_started
                next_fetch_at = time.perf_counter()
                continue

            discovery_source = (
                DISCOVERY_SOURCE_HTML_FALLBACK
                if page_batch.renderer_counts.get("htmlFallback", 0) > 0
                else DISCOVERY_SOURCE_INNERTUBE
            )
            page_candidates = [
                RadarCandidate.from_video_search(
                    video,
                    keyword=keyword,
                    discovery_source=discovery_source,
                )
                for video in filtered_videos
            ]
            for candidate in page_candidates:
                apply_signal_snapshot(candidate)
            phase_seconds["parse"] += time.perf_counter() - parse_started

            cache_size_before = len(subscriber_cache)
            qual_started = time.perf_counter()
            process_result = await service.process_radar_videos(
                session,
                filtered_videos,
                log_rejections=False,
                filter_title_language=True,
                upload_period=upload_period,
                qualification_context=qualification_context,
                blacklist_words=get_radar_blacklist_words(),
                subscriber_cache=subscriber_cache,
                filter_metrics=filter_metrics,
                collect_video_outcomes=True,
                register_channels=register_explosive_channels,
            )
            qual_elapsed = time.perf_counter() - qual_started
            subscriber_seconds = process_result.subscriber_fetch_seconds
            phase_seconds["qualification"] += max(0.0, qual_elapsed - subscriber_seconds)
            phase_seconds["channel_enrichment"] += subscriber_seconds
            phase_seconds["channel_homepage_fetches"] += process_result.subscriber_fetch_count
            phase_seconds["subscriber_fetch_delay_seconds"] = (
                phase_seconds.get("subscriber_fetch_delay_seconds", 0.0)
                + process_result.subscriber_fetch_count
                * process_result.subscriber_fetch_delay_seconds
            )

            apply_video_outcomes(page_candidates, list(process_result.video_outcomes))
            apply_subscriber_enrichment(page_candidates, subscriber_cache)
            keyword_candidates.extend(page_candidates)
            result.explosive_hits += len(process_result.hits)

            for video in filtered_videos:
                result.raw_candidate_count += 1
                unique_by_id.setdefault(video.video_id, video)

            passed_on_page = process_result.passed_count
            if passed_on_page >= TARGET_VIDEOS_COUNT:
                break
            if result.pages_scanned >= max_pages:
                break
            delay_started = time.perf_counter()
            await asyncio.sleep(search_page_delay_seconds)
            phase_seconds["other"] += time.perf_counter() - delay_started
            next_fetch_at = time.perf_counter()

    except YouTubeApiError as exc:
        result.error = str(exc)
        logger.exception("Discovery scan failed for keyword=%r", keyword)

    result.unique_videos = list(unique_by_id.values())
    result.candidates = keyword_candidates
    for candidate in keyword_candidates:
        if candidate.qualification_state == QUALIFICATION_PASSED:
            result.qualification_passed_count += 1
        elif candidate.qualification_state == QUALIFICATION_REJECTED:
            result.qualification_rejected_count += 1

    if profiler and profiler.sql_statement_count() > sql_count_before:
        new_records = profiler.sql_records[sql_count_before:]
        phase_seconds["database"] = round(sum(r.duration_seconds for r in new_records), 4)

    result.profile_phase_seconds = phase_seconds
    result.innertube_metrics_summary = innertube_metrics.to_summary_dict()
    result.filter_metrics_summary = filter_metrics.to_summary_dict()
    result.finished_at = time.perf_counter()
    return result
