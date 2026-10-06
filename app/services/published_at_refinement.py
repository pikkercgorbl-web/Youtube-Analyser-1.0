"""Refine Video.published_at via videos.list for Radar / Attention / monitoring pools."""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.youtube.client import YouTubeVideoDetails
from app.models.orm import AttentionPatternVideoRow, AttentionVideoWinnerRow, Video
from app.services.attention_read_model import get_latest_attention_run
from app.services.metrics import calc_vph, ensure_utc, utc_now
from app.services.monitoring_video_source import load_monitored_video_states
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
from app.services.video_format_from_api import chunk_video_ids
from app.services.video_published_at import PUBLISHED_AT_SOURCE_API, apply_api_published_at


class VideosListClient(Protocol):
    def get_videos(self, video_ids: list[str]) -> list[object]:
        ...


def _needs_published_at_refinement(video: Video) -> bool:
    src = getattr(video, "published_at_source", None)
    return src != PUBLISHED_AT_SOURCE_API


def collect_attention_snapshot_video_ids(session: Session) -> set[str]:
    run = get_latest_attention_run(session)
    if run is None:
        return set()
    run_id = run.run_id
    ids: set[str] = set()
    ids.update(
        session.scalars(
            select(AttentionVideoWinnerRow.video_id).where(AttentionVideoWinnerRow.run_id == run_id),
        ).all(),
    )
    ids.update(
        session.scalars(
            select(AttentionPatternVideoRow.video_id).where(AttentionPatternVideoRow.run_id == run_id),
        ).all(),
    )
    return ids


def collect_active_monitoring_video_ids(session: Session, *, now: datetime | None = None) -> set[str]:
    reference = ensure_utc(now or utc_now())
    states = load_monitored_video_states(session, now=reference)
    return {row.video_id for row in states}


def collect_refinement_pool_video_ids(session: Session, *, now: datetime | None = None) -> set[str]:
    pool = collect_attention_snapshot_video_ids(session) | collect_active_monitoring_video_ids(
        session,
        now=now,
    )
    if not pool:
        return set()
    rows = session.scalars(select(Video).where(Video.id.in_(pool))).all()
    return {row.id for row in rows if _needs_published_at_refinement(row)}


def _refinement_priority(video: Video, *, now: datetime) -> tuple:
    pub = ensure_utc(video.published_at)
    age_h = max((now - pub).total_seconds() / 3600.0, 0.0)
    # Inside Channel Momentum capture window [18, 30] first.
    in_momentum_window = 18.0 <= age_h <= 30.0
    band = 0 if in_momentum_window else 1
    tie = zlib.crc32(video.id.encode("utf-8"))
    return (band, age_h if in_momentum_window else -pub.timestamp(), tie)


def select_published_at_refinement_video_ids(
    session: Session,
    candidate_ids: set[str] | frozenset[str],
    *,
    limit: int,
    now: datetime | None = None,
) -> list[str]:
    reference = ensure_utc(now or utc_now())
    if limit <= 0 or not candidate_ids:
        return []
    rows = list(session.scalars(select(Video).where(Video.id.in_(candidate_ids))).all())
    eligible = [row for row in rows if _needs_published_at_refinement(row)]
    eligible.sort(key=lambda v: _refinement_priority(v, now=reference))
    return [row.id for row in eligible[:limit]]


@dataclass
class PublishedAtRefinementPlan:
    pool_video_count: int = 0
    attention_snapshot_video_count: int = 0
    monitoring_active_video_count: int = 0
    selected_video_count: int = 0
    api_batches: int = 0
    daily_budget_limit: int = 0
    daily_budget_remaining: int = 0
    deferred_to_next_day: int = 0
    video_ids_planned: tuple[str, ...] = ()
    dry_run: bool = True
    notes: dict[str, object] = field(default_factory=dict)


@dataclass
class PublishedAtRefinementApplyReport(PublishedAtRefinementPlan):
    videos_updated: int = 0
    videos_unchanged: int = 0
    videos_missing: int = 0
    videos_failed: int = 0
    quota_exhausted: bool = False
    http_batches_executed: int = 0
    budget_units_reserved: int = 0
    pool_remaining_after: int | None = None
    daily_budget_remaining_after: int | None = None
    before_after_samples: list[dict] = field(default_factory=list)


def plan_published_at_refinement(
    session: Session,
    *,
    now: datetime | None = None,
) -> PublishedAtRefinementPlan:
    reference = ensure_utc(now or utc_now())
    daily_limit = unknown_format_enrichment_settings.unknown_format_enrichment_daily_video_limit
    remaining = remaining_id_units(
        session,
        budget_kind=BUDGET_KIND_VIDEOS_LIST,
        daily_limit=daily_limit,
        now=reference,
    )
    attention_ids = collect_attention_snapshot_video_ids(session)
    monitoring_ids = collect_active_monitoring_video_ids(session, now=reference)
    pool = collect_refinement_pool_video_ids(session, now=reference)
    selected = select_published_at_refinement_video_ids(
        session,
        pool,
        limit=remaining,
        now=reference,
    )
    batches = (len(selected) + VIDEOS_LIST_BATCH_SIZE - 1) // VIDEOS_LIST_BATCH_SIZE if selected else 0
    return PublishedAtRefinementPlan(
        pool_video_count=len(pool),
        attention_snapshot_video_count=len(attention_ids & pool),
        monitoring_active_video_count=len(monitoring_ids & pool),
        selected_video_count=len(selected),
        api_batches=batches,
        daily_budget_limit=daily_limit,
        daily_budget_remaining=remaining,
        deferred_to_next_day=max(0, len(pool) - len(selected)),
        video_ids_planned=tuple(selected),
        dry_run=True,
        notes={
            "confirmed_regular_included": True,
            "selection_rule": "published_at_source != api_snippet; format confirmation does not exclude",
        },
    )


def apply_published_at_refinement(
    session: Session,
    youtube_client: VideosListClient,
    *,
    dry_run: bool = True,
    now: datetime | None = None,
    max_samples: int = 10,
) -> PublishedAtRefinementApplyReport:
    reference = ensure_utc(now or utc_now())
    plan = plan_published_at_refinement(session, now=reference)
    report = PublishedAtRefinementApplyReport(
        pool_video_count=plan.pool_video_count,
        attention_snapshot_video_count=plan.attention_snapshot_video_count,
        monitoring_active_video_count=plan.monitoring_active_video_count,
        selected_video_count=plan.selected_video_count,
        api_batches=plan.api_batches,
        daily_budget_limit=plan.daily_budget_limit,
        daily_budget_remaining=plan.daily_budget_remaining,
        deferred_to_next_day=plan.deferred_to_next_day,
        video_ids_planned=plan.video_ids_planned,
        dry_run=dry_run,
        notes=dict(plan.notes),
    )
    if not plan.video_ids_planned:
        return report

    daily_limit = plan.daily_budget_limit
    for batch in chunk_video_ids(list(plan.video_ids_planned), batch_size=VIDEOS_LIST_BATCH_SIZE):
        if dry_run:
            report.http_batches_executed += 1
            continue

        reservation = try_reserve_id_units(
            session,
            budget_kind=BUDGET_KIND_VIDEOS_LIST,
            unit_count=len(batch),
            daily_limit=daily_limit,
            now=reference,
        )
        report.budget_units_reserved += reservation.reserved
        batch = batch[: reservation.reserved]
        if not batch:
            break
        session.commit()

        details_by_id: dict[str, YouTubeVideoDetails] = {}
        try:
            raw = youtube_client.get_videos(batch)
            report.http_batches_executed += 1
            record_http_requests(
                session,
                budget_kind=BUDGET_KIND_VIDEOS_LIST,
                request_count=1,
                now=reference,
            )
            for item in raw:
                if isinstance(item, YouTubeVideoDetails):
                    details_by_id[item.video_id] = item
        except Exception as exc:
            session.rollback()
            report.notes["last_error"] = str(exc)
            from app.integrations.youtube.client import YouTubeApiError

            if isinstance(exc, YouTubeApiError) or "quota" in str(exc).lower():
                report.quota_exhausted = True
                report.videos_failed += len(batch)
            else:
                report.videos_failed += len(batch)
            break

        for vid in batch:
            row = session.get(Video, vid)
            details = details_by_id.get(vid)
            if row is None:
                report.videos_missing += 1
                continue
            if details is None:
                report.videos_missing += 1
                continue
            before_pub = ensure_utc(row.published_at)
            before_vph = calc_vph(int(row.views_count or 0), before_pub, now=reference)
            apply_api_published_at(row, details.published_at)
            after_pub = ensure_utc(row.published_at)
            if after_pub != before_pub:
                report.videos_updated += 1
                if len(report.before_after_samples) < max_samples:
                    after_vph = calc_vph(int(row.views_count or 0), after_pub, now=reference)
                    report.before_after_samples.append(
                        {
                            "video_id": vid,
                            "published_at_before": before_pub.isoformat(),
                            "published_at_after": after_pub.isoformat(),
                            "vph_before": before_vph,
                            "vph_after": after_vph,
                        },
                    )
            else:
                report.videos_unchanged += 1
        session.commit()

    if not dry_run:
        report.pool_remaining_after = len(collect_refinement_pool_video_ids(session, now=reference))
        report.daily_budget_remaining_after = remaining_id_units(
            session,
            budget_kind=BUDGET_KIND_VIDEOS_LIST,
            daily_limit=daily_limit,
            now=reference,
        )
    return report
