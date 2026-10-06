"""One-shot automatic discovery cycle orchestration (Stage 1.15A)."""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import Video
from app.services.discovered_video_batch import batch_persist_discovered_videos
from app.services.keyword_discovery_metrics_storage import (
    mark_hits_persisted_for_monitoring,
    persist_keyword_discovery_hits,
    persist_keyword_scan_run,
)
from app.services.discovery_keyword_scan import KeywordDiscoveryScanResult, scan_keyword_for_discovery
from app.services.discovery_keyword_selection import select_discovery_keywords
from app.services.explosive_channels_service import ExplosiveChannelsService
from app.services.metrics import utc_now
from app.services.keyword_lifecycle_service import apply_post_scan_schedule

logger = logging.getLogger(__name__)

DEFAULT_KEYWORD_BATCH_SIZE = 5
CycleStatus = Literal["ok", "partial", "failed", "dry_run"]


class DiscoveryYoutubeClient(Protocol):
    """Reserved for future non-InnerTube discovery paths."""


@dataclass
class DiscoveryKeywordSummary:
    keyword_id: int
    keyword: str
    started_at: datetime
    finished_at: datetime
    runtime_seconds: float
    raw_candidates: int
    unique_candidates: int
    persisted_videos: int
    updated_videos: int
    qualification_passed: int
    qualification_rejected: int
    duplicate_candidates: int
    explosive_hits: int
    errors: tuple[str, ...] = ()
    status: Literal["ok", "failed"] = "ok"


@dataclass
class DiscoveryCycleSummary:
    run_id: str
    started_at: datetime
    finished_at: datetime | None = None
    runtime_seconds: float = 0.0
    selected_keyword_count: int = 0
    completed_keyword_count: int = 0
    failed_keyword_count: int = 0
    raw_candidate_count: int = 0
    unique_video_count: int = 0
    duplicate_occurrence_count: int = 0
    persisted_video_count: int = 0
    updated_video_count: int = 0
    qualification_passed_count: int = 0
    qualification_rejected_count: int = 0
    regular_video_count: int = 0
    short_count: int = 0
    live_count: int = 0
    error_count: int = 0
    cycle_status: CycleStatus = "ok"
    keyword_summaries: tuple[DiscoveryKeywordSummary, ...] = ()


@dataclass
class DiscoveryCycleOutcome:
    summary: DiscoveryCycleSummary


@dataclass(frozen=True, slots=True)
class DiscoveryCycleConfig:
    keyword_batch_size: int = DEFAULT_KEYWORD_BATCH_SIZE
    max_pages_per_keyword: int = 100
    register_explosive_channels: bool = True
    profile: bool = False


def generate_discovery_run_id(*, now: datetime | None = None) -> str:
    reference = now or utc_now()
    stamp = reference.strftime("%Y%m%dT%H%M%SZ")
    return f"discovery_{stamp}_{secrets.token_hex(4)}"


def _log_keyword_summary(row: DiscoveryKeywordSummary) -> None:
    logger.info(
        "[DISCOVERY_KEYWORD] keyword=%s raw=%s unique=%s persisted=%s qualified=%s "
        "rejected=%s duration=%s status=%s",
        row.keyword,
        row.raw_candidates,
        row.unique_candidates,
        row.persisted_videos,
        row.qualification_passed,
        row.qualification_rejected,
        row.runtime_seconds,
        row.status,
    )


def log_discovery_cycle_summary(summary: DiscoveryCycleSummary) -> None:
    logger.info(
        "[DISCOVERY_CYCLE] run_id=%s keywords=%s completed=%s failed=%s raw=%s unique=%s "
        "persisted=%s qualified=%s rejected=%s duplicates=%s duration=%s status=%s",
        summary.run_id,
        summary.selected_keyword_count,
        summary.completed_keyword_count,
        summary.failed_keyword_count,
        summary.raw_candidate_count,
        summary.unique_video_count,
        summary.persisted_video_count,
        summary.qualification_passed_count,
        summary.qualification_rejected_count,
        summary.duplicate_occurrence_count,
        summary.runtime_seconds,
        summary.cycle_status,
    )


def _resolve_cycle_status(
    *,
    dry_run: bool,
    completed: int,
    failed: int,
    selected: int,
) -> CycleStatus:
    if dry_run:
        return "dry_run"
    if selected == 0:
        return "ok"
    if failed >= selected:
        return "failed"
    if failed > 0:
        return "partial"
    return "ok"


async def run_discovery_cycle_async(
    session: Session,
    *,
    youtube_client: DiscoveryYoutubeClient | None = None,
    config: DiscoveryCycleConfig | None = None,
    dry_run: bool = False,
    run_id: str | None = None,
) -> DiscoveryCycleOutcome:
    _ = youtube_client
    cfg = config or DiscoveryCycleConfig()
    if dry_run:
        cfg = DiscoveryCycleConfig(
            keyword_batch_size=cfg.keyword_batch_size,
            max_pages_per_keyword=cfg.max_pages_per_keyword,
            register_explosive_channels=False,
            profile=cfg.profile,
        )

    from app.services.discovery_cycle_profiling import DiscoveryProfiler, set_active_profiler

    profiler: DiscoveryProfiler | None = None
    if cfg.profile:
        profiler = DiscoveryProfiler()
        set_active_profiler(profiler)
        profiler.attach_sql_listener(session.get_bind())

    started_perf = time.perf_counter()
    started_at = utc_now()
    cycle_run_id = run_id or generate_discovery_run_id(now=started_at)

    bootstrap_ctx = profiler.phase("cycle_bootstrap") if profiler else nullcontext()
    with bootstrap_ctx:
        select_ctx = profiler.phase("keyword_selection") if profiler else nullcontext()
        with select_ctx:
            keywords = select_discovery_keywords(session, batch_size=cfg.keyword_batch_size)
        upload_period = ExplosiveChannelsService().get_upload_period(session)

    summary = DiscoveryCycleSummary(
        run_id=cycle_run_id,
        started_at=started_at,
        selected_keyword_count=len(keywords),
    )

    cycle_persisted_ids: set[str] = set()
    cycle_video_ids_seen: set[str] = set()
    unique_seen_ids: set[str] = set()
    keyword_summaries: list[DiscoveryKeywordSummary] = []
    # Immutable snapshot at cycle start — never updated when new videos insert mid-cycle.
    video_ids_existing_before_cycle: frozenset[str] = frozenset()
    if not dry_run:
        db_ctx = profiler.phase("database") if profiler else nullcontext()
        with db_ctx:
            video_ids_existing_before_cycle = frozenset(session.scalars(select(Video.id)).all())

    for record in keywords:
        kw_started = utc_now()
        kw_started_perf = time.perf_counter()
        scan: KeywordDiscoveryScanResult | None = None
        try:
            kw_ctx = profiler.phase("per_keyword_total") if profiler else nullcontext()
            with kw_ctx:
                scan = await scan_keyword_for_discovery(
                    session,
                    keyword=record.keyword,
                    keyword_id=record.id,
                    upload_period=upload_period,
                    register_explosive_channels=cfg.register_explosive_channels,
                    max_pages=cfg.max_pages_per_keyword,
                )
        except Exception as exc:
            summary.failed_keyword_count += 1
            summary.error_count += 1
            kw_finished = utc_now()
            kw_runtime = round(time.perf_counter() - kw_started_perf, 3)
            if not dry_run:
                persist_keyword_scan_run(
                    session,
                    keyword_id=record.id,
                    discovery_run_id=cycle_run_id,
                    started_at=kw_started,
                    finished_at=kw_finished,
                    status="failed",
                    raw_candidates=0,
                    unique_candidates=0,
                    within_keyword_duplicate_candidates=0,
                    cross_keyword_duplicate_candidates=0,
                    persisted_videos=0,
                    qualification_passed=0,
                    qualification_rejected=0,
                    error_summary=str(exc),
                    runtime_seconds=kw_runtime,
                )
                apply_post_scan_schedule(
                    session,
                    record.id,
                    finished_at=kw_finished,
                    scan_succeeded=False,
                )
            keyword_summaries.append(
                DiscoveryKeywordSummary(
                    keyword_id=record.id,
                    keyword=record.keyword,
                    started_at=kw_started,
                    finished_at=kw_finished,
                    runtime_seconds=kw_runtime,
                    raw_candidates=0,
                    unique_candidates=0,
                    persisted_videos=0,
                    updated_videos=0,
                    qualification_passed=0,
                    qualification_rejected=0,
                    duplicate_candidates=0,
                    explosive_hits=0,
                    errors=(str(exc),),
                    status="failed",
                ),
            )
            continue

        assert scan is not None
        keyword_failed = scan.error is not None
        if keyword_failed:
            summary.failed_keyword_count += 1
            summary.error_count += 1
        else:
            summary.completed_keyword_count += 1

        summary.raw_candidate_count += scan.raw_candidate_count
        summary.qualification_passed_count += scan.qualification_passed_count
        summary.qualification_rejected_count += scan.qualification_rejected_count

        kw_persisted = 0
        kw_updated = 0
        kw_duplicates = 0
        cross_keyword_dup = 0
        persisted_for_monitoring_ids: set[str] = set()

        if not dry_run:
            persist_ctx = profiler.phase("database") if profiler else nullcontext()
            with persist_ctx:
                cross_keyword_dup, _ = persist_keyword_discovery_hits(
                    session,
                    keyword_id=record.id,
                    discovery_run_id=cycle_run_id,
                    discovered_at=kw_started,
                    scan=scan,
                    cycle_video_ids_seen=cycle_video_ids_seen,
                    video_ids_existing_before_cycle=video_ids_existing_before_cycle,
                )

        for video in scan.unique_videos:
            unique_seen_ids.add(video.video_id)
            if video.is_short:
                summary.short_count += 1
            elif video.is_live:
                summary.live_count += 1
            else:
                summary.regular_video_count += 1

        if not dry_run:
            persist_results, kw_duplicates_from_batch = batch_persist_discovered_videos(
                session,
                scan.unique_videos,
                discovery_keyword=record.keyword,
                cycle_persisted_ids=cycle_persisted_ids,
            )
            kw_duplicates += kw_duplicates_from_batch
            summary.duplicate_occurrence_count += kw_duplicates_from_batch
            for outcome in persist_results:
                if outcome.outcome == "inserted":
                    summary.persisted_video_count += 1
                    kw_persisted += 1
                    persisted_for_monitoring_ids.add(outcome.video_id)
                elif outcome.outcome == "updated":
                    summary.updated_video_count += 1
                    kw_updated += 1
                    persisted_for_monitoring_ids.add(outcome.video_id)
        else:
            for video in scan.unique_videos:
                if video.video_id in cycle_persisted_ids:
                    summary.duplicate_occurrence_count += 1
                    kw_duplicates += 1
                    continue
                cycle_persisted_ids.add(video.video_id)

        if not dry_run:
            mark_hits_persisted_for_monitoring(
                session,
                keyword_id=record.id,
                discovery_run_id=cycle_run_id,
                video_ids=persisted_for_monitoring_ids,
            )
            within_keyword_dup = max(0, scan.raw_candidate_count - len(scan.unique_videos))
            persist_keyword_scan_run(
                session,
                keyword_id=record.id,
                discovery_run_id=cycle_run_id,
                started_at=kw_started,
                finished_at=utc_now(),
                status="failed" if keyword_failed else "ok",
                raw_candidates=scan.raw_candidate_count,
                unique_candidates=len(scan.unique_videos),
                within_keyword_duplicate_candidates=within_keyword_dup,
                cross_keyword_duplicate_candidates=cross_keyword_dup,
                persisted_videos=kw_persisted + kw_updated,
                qualification_passed=scan.qualification_passed_count,
                qualification_rejected=scan.qualification_rejected_count,
                error_summary=scan.error,
                runtime_seconds=round(time.perf_counter() - kw_started_perf, 3),
            )
            kw_finished = utc_now()
            apply_post_scan_schedule(
                session,
                record.id,
                finished_at=kw_finished,
                scan_succeeded=not keyword_failed,
            )

        kw_summary = DiscoveryKeywordSummary(
            keyword_id=record.id,
            keyword=record.keyword,
            started_at=kw_started,
            finished_at=utc_now(),
            runtime_seconds=round(time.perf_counter() - kw_started_perf, 3),
            raw_candidates=scan.raw_candidate_count,
            unique_candidates=len(scan.unique_videos),
            persisted_videos=kw_persisted,
            updated_videos=kw_updated,
            qualification_passed=scan.qualification_passed_count,
            qualification_rejected=scan.qualification_rejected_count,
            duplicate_candidates=kw_duplicates,
            explosive_hits=scan.explosive_hits,
            errors=(scan.error,) if scan.error else (),
            status="failed" if keyword_failed else "ok",
        )
        keyword_summaries.append(kw_summary)
        _log_keyword_summary(kw_summary)

        if profiler and scan is not None:
            from app.services.discovery_cycle_profiling import build_keyword_profile

            innertube_n = int(scan.innertube_metrics_summary.get("request_count", 0))
            html_n = int(scan.filter_metrics_summary.get("html_fallback_count", 0))
            profiler.record_http_innertube(
                innertube_n,
                max_duration_ms=float(scan.innertube_metrics_summary.get("max_duration_ms", 0.0)),
            )
            profiler.record_http_html_fallback(html_n)
            channel_n = int(scan.profile_phase_seconds.get("channel_homepage_fetches", 0))
            profiler.record_http_channel(channel_n)
            phases = scan.profile_phase_seconds
            profiler.add_phase("per_keyword_fetch", phases.get("fetch", 0.0))
            profiler.add_phase("per_keyword_parse", phases.get("parse", 0.0))
            profiler.add_phase("per_keyword_qualification", phases.get("qualification", 0.0))
            profiler.add_phase("per_keyword_channel", phases.get("channel_enrichment", 0.0))
            profiler.add_phase("per_keyword_database", phases.get("database", 0.0))
            format_passed = int(scan.filter_metrics_summary.get("discovered_videos", 0)) - int(
                scan.filter_metrics_summary.get("format_skips", 0),
            )
            profiler.record_keyword_profile(
                build_keyword_profile(
                    keyword_id=record.id,
                    keyword=record.keyword,
                    started_at=kw_started,
                    duration_seconds=kw_summary.runtime_seconds,
                    phase_seconds=phases,
                    raw_candidates=scan.raw_candidate_count,
                    unique_candidates=len(scan.unique_videos),
                    format_passed=max(0, format_passed),
                    qualification_passed=scan.qualification_passed_count,
                    qualification_rejected=scan.qualification_rejected_count,
                    unique_channels=int(scan.filter_metrics_summary.get("unique_channels", 0)),
                    html_fallback_count=html_n,
                    innertube_requests=innertube_n,
                    status=kw_summary.status,
                    errors=kw_summary.errors,
                ),
            )

    commit_ctx = profiler.phase("db_flush_commit") if profiler else nullcontext()
    with commit_ctx:
        if not dry_run:
            session.commit()
        elif dry_run:
            session.rollback()
        else:
            session.commit()

    summary.unique_video_count = len(unique_seen_ids)
    summary.keyword_summaries = tuple(keyword_summaries)
    summary.finished_at = utc_now()
    summary.runtime_seconds = round(time.perf_counter() - started_perf, 3)
    summary.cycle_status = _resolve_cycle_status(
        dry_run=dry_run,
        completed=summary.completed_keyword_count,
        failed=summary.failed_keyword_count,
        selected=summary.selected_keyword_count,
    )

    log_discovery_cycle_summary(summary)

    if profiler:
        with profiler.phase("cycle_summary"):
            profiler.print_summary(total_cycle_seconds=summary.runtime_seconds)
        profiler.detach_sql_listener()
        set_active_profiler(None)

    return DiscoveryCycleOutcome(summary=summary)


def run_discovery_cycle(
    session: Session,
    *,
    youtube_client: DiscoveryYoutubeClient | None = None,
    config: DiscoveryCycleConfig | None = None,
    dry_run: bool = False,
    run_id: str | None = None,
) -> DiscoveryCycleOutcome:
    """Synchronous entrypoint (runs asyncio loop for InnerTube discovery)."""
    return asyncio.run(
        run_discovery_cycle_async(
            session,
            youtube_client=youtube_client,
            config=config,
            dry_run=dry_run,
            run_id=run_id,
        ),
    )
