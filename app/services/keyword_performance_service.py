"""Keyword performance metrics from persisted discovery data (Stage 1.16A / 1.18B)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.orm import KeywordDiscoveryHit, KeywordScanRun, TargetKeyword, VideoSnapshot
from app.services.keyword_performance_evaluation import (
    AttributionMode,
    EvidenceDetail,
    GlobalBreakoutBundle,
    KeywordBatchAggregates,
    KeywordEvaluationContext,
    KeywordEvaluationOptions,
    build_global_breakout_bundle,
    evaluate_keywords_batch,
    make_evaluation_context,
)
from app.services.keyword_schedule_state import _overdue_seconds, get_keyword_schedule_state, is_keyword_due
from app.services.metrics import ensure_utc, utc_now
from app.services.monitoring_tier_budget_policy import MonitoringTier, assign_monitoring_tiers
from app.services.monitoring_video_source import load_monitored_video_states


@dataclass(frozen=True, slots=True)
class KeywordPerformanceMetrics:
    keyword_id: int
    keyword: str
    scan_count: int
    first_scan_at: datetime | None
    last_scan_at: datetime | None
    discovery_hit_count: int
    unique_video_count: int
    unique_channel_count: int
    within_keyword_duplicate_hit_count: int
    cross_keyword_duplicate_count: int
    already_known_video_count: int
    duplicate_hit_count: int
    duplicate_rate: float | None
    regular_video_count: int
    short_count: int
    live_count: int
    qualification_passed_count: int
    qualification_rejected_count: int
    qualification_pass_rate: float | None
    persisted_for_monitoring_count: int
    monitored_video_count: int
    videos_with_snapshot_count: int
    videos_with_snapshot_24h_count: int
    videos_with_snapshot_48h_count: int
    videos_with_snapshot_72h_count: int
    current_tier_a_count: int | None
    current_tier_b_count: int | None
    current_tier_c_count: int | None
    t24_outcome_count: int
    t48_outcome_count: int
    t72_outcome_count: int
    confirmed_breakout_count: int
    videos_per_scan: float | None
    unique_videos_per_scan: float | None
    unique_channels_per_scan: float | None
    persisted_videos_per_scan: float | None
    qualification_passed_per_scan: float | None
    lifecycle_status: str | None = None
    source_type: str | None = None
    last_checked: datetime | None = None
    next_scan_at: datetime | None = None
    scan_interval_seconds: int | None = None
    is_due: bool | None = None
    overdue_seconds: float | None = None
    scheduling_hint: str | None = None
    # Stage 1.18B — evaluation context (also on list envelope)
    evaluated_at: datetime | None = None
    attribution_mode: str | None = None
    window_from: datetime | None = None
    window_to: datetime | None = None
    ranking_version: str | None = None
    global_eligible_video_count: int | None = None
    horizon_hours: int | None = None
    horizon_snapshot_tolerance_hours: int | None = None
    new_to_corpus_video_count: int | None = None
    shared_video_count: int | None = None
    exclusive_first_discovery_count: int | None = None
    attributed_video_count: int | None = None
    monitorable_video_count: int | None = None
    breakout_eligible_video_count: int | None = None
    breakout_ranked_video_count: int | None = None
    top_decile_breakout_count: int | None = None
    top_decile_breakout_rate: float | None = None
    median_vph_at_discovery: float | None = None
    p90_vph_at_discovery: float | None = None
    median_current_vph: float | None = None
    observed_72h_video_count: int | None = None
    missing_72h_video_count: int | None = None
    median_absolute_view_growth_72h: float | None = None
    evidence_status: str | None = None
    evidence_detail: EvidenceDetail | None = None


@dataclass(frozen=True, slots=True)
class KeywordPerformanceListResult:
    context: KeywordEvaluationContext
    items: list[KeywordPerformanceMetrics]


def _time_filter_hit(column, from_ts: datetime | None, to_ts: datetime | None):
    clauses = []
    if from_ts is not None:
        clauses.append(column >= ensure_utc(from_ts))
    if to_ts is not None:
        clauses.append(column <= ensure_utc(to_ts))
    return clauses


def _time_filter_scan(column, from_ts: datetime | None, to_ts: datetime | None):
    return _time_filter_hit(column, from_ts, to_ts)


def _snapshot_coverage(session: Session, video_ids: set[str]) -> tuple[int, int, int, int]:
    if not video_ids:
        return 0, 0, 0, 0
    rows = session.execute(
        select(
            VideoSnapshot.video_id,
            func.max(VideoSnapshot.age_hours),
        )
        .where(VideoSnapshot.video_id.in_(video_ids))
        .group_by(VideoSnapshot.video_id),
    ).all()
    any_snap = len(rows)
    at_24 = sum(1 for _vid, age in rows if age is not None and age >= 24.0)
    at_48 = sum(1 for _vid, age in rows if age is not None and age >= 48.0)
    at_72 = sum(1 for _vid, age in rows if age is not None and age >= 72.0)
    return any_snap, at_24, at_48, at_72


def _optional_tier_counts(session: Session, video_ids: set[str]) -> tuple[int, int, int] | None:
    if not video_ids:
        return 0, 0, 0
    states = [s for s in load_monitored_video_states(session) if s.video_id in video_ids]
    if not states:
        return 0, 0, 0
    from app.services.monitoring_tier_budget_policy import TierCandidateInput

    inputs = [
        TierCandidateInput(
            video_id=s.video_id,
            channel_id=s.channel_id,
            raw_vph=s.raw_vph,
            age_hours=s.age_hours,
            baseline_status=s.channel_velocity_baseline_status,
            vph_vs_channel_median=s.vph_vs_channel_median,
        )
        for s in states
    ]
    decisions = assign_monitoring_tiers(inputs)
    a = sum(1 for d in decisions if d.tier == MonitoringTier.A)
    b = sum(1 for d in decisions if d.tier == MonitoringTier.B)
    c = sum(1 for d in decisions if d.tier == MonitoringTier.C)
    return a, b, c


def _per_scan(value: int, scan_count: int) -> float | None:
    return round(value / scan_count, 4) if scan_count else None


def _batch_to_metrics(
    agg: KeywordBatchAggregates,
    keyword: TargetKeyword,
    context: KeywordEvaluationContext,
    schedule_fields: dict,
) -> KeywordPerformanceMetrics:
    return KeywordPerformanceMetrics(
        keyword_id=agg.keyword_id,
        keyword=agg.keyword,
        scan_count=agg.scan_count,
        first_scan_at=agg.first_scan_at,
        last_scan_at=agg.last_scan_at,
        discovery_hit_count=agg.discovery_hit_count,
        unique_video_count=agg.unique_video_count,
        unique_channel_count=agg.unique_channel_count,
        within_keyword_duplicate_hit_count=agg.within_keyword_duplicate_hit_count,
        cross_keyword_duplicate_count=agg.cross_keyword_duplicate_count,
        already_known_video_count=agg.already_known_video_count,
        duplicate_hit_count=agg.duplicate_hit_count,
        duplicate_rate=agg.duplicate_rate,
        regular_video_count=agg.regular_video_count,
        short_count=agg.short_count,
        live_count=agg.live_count,
        qualification_passed_count=agg.qualification_passed_count,
        qualification_rejected_count=agg.qualification_rejected_count,
        qualification_pass_rate=agg.qualification_pass_rate,
        persisted_for_monitoring_count=agg.persisted_for_monitoring_count,
        monitored_video_count=agg.monitored_video_count,
        videos_with_snapshot_count=agg.videos_with_snapshot_count,
        videos_with_snapshot_24h_count=agg.videos_with_snapshot_24h_count,
        videos_with_snapshot_48h_count=agg.videos_with_snapshot_48h_count,
        videos_with_snapshot_72h_count=agg.videos_with_snapshot_72h_count,
        current_tier_a_count=agg.current_tier_a_count,
        current_tier_b_count=agg.current_tier_b_count,
        current_tier_c_count=agg.current_tier_c_count,
        t24_outcome_count=0,
        t48_outcome_count=0,
        t72_outcome_count=agg.observed_72h_video_count,
        confirmed_breakout_count=agg.top_decile_breakout_count,
        videos_per_scan=_per_scan(agg.discovery_hit_count, agg.scan_count),
        unique_videos_per_scan=_per_scan(agg.unique_video_count, agg.scan_count),
        unique_channels_per_scan=_per_scan(agg.unique_channel_count, agg.scan_count),
        persisted_videos_per_scan=_per_scan(agg.persisted_for_monitoring_count, agg.scan_count),
        qualification_passed_per_scan=_per_scan(agg.qualification_passed_count, agg.scan_count),
        lifecycle_status=schedule_fields.get("lifecycle_status"),
        source_type=schedule_fields.get("source_type"),
        last_checked=schedule_fields.get("last_checked"),
        next_scan_at=schedule_fields.get("next_scan_at"),
        scan_interval_seconds=schedule_fields.get("scan_interval_seconds"),
        is_due=schedule_fields.get("is_due"),
        overdue_seconds=schedule_fields.get("overdue_seconds"),
        scheduling_hint=schedule_fields.get("scheduling_hint"),
        evaluated_at=context.evaluated_at,
        attribution_mode=context.attribution_mode,
        window_from=context.window_from,
        window_to=context.window_to,
        ranking_version=context.ranking_version,
        global_eligible_video_count=context.global_eligible_video_count,
        horizon_hours=context.horizon_hours,
        horizon_snapshot_tolerance_hours=context.horizon_snapshot_tolerance_hours,
        new_to_corpus_video_count=agg.new_to_corpus_video_count,
        shared_video_count=agg.shared_video_count,
        exclusive_first_discovery_count=agg.exclusive_first_discovery_count,
        attributed_video_count=agg.attributed_video_count,
        monitorable_video_count=agg.monitorable_video_count,
        breakout_eligible_video_count=agg.breakout_eligible_video_count,
        breakout_ranked_video_count=agg.breakout_ranked_video_count,
        top_decile_breakout_count=agg.top_decile_breakout_count,
        top_decile_breakout_rate=agg.top_decile_breakout_rate,
        median_vph_at_discovery=agg.median_vph_at_discovery,
        p90_vph_at_discovery=agg.p90_vph_at_discovery,
        median_current_vph=agg.median_current_vph,
        observed_72h_video_count=agg.observed_72h_video_count,
        missing_72h_video_count=agg.missing_72h_video_count,
        median_absolute_view_growth_72h=agg.median_absolute_view_growth_72h,
        evidence_status=agg.evidence_status,
        evidence_detail=agg.evidence_detail,
    )


def _schedule_fields(session: Session, keyword: TargetKeyword) -> dict:
    schedule = get_keyword_schedule_state(session, keyword.id)
    if schedule is None:
        return _schedule_fields_fast(keyword, utc_now())
    return {
        "lifecycle_status": schedule.lifecycle_status,
        "source_type": schedule.source_type,
        "last_checked": schedule.last_checked,
        "next_scan_at": schedule.next_scan_at,
        "scan_interval_seconds": schedule.scan_interval_seconds,
        "is_due": schedule.is_due,
        "overdue_seconds": schedule.overdue_seconds,
        "scheduling_hint": schedule.scheduling_hint,
    }


def _schedule_fields_fast(keyword: TargetKeyword, reference: datetime) -> dict:
    """List batch path — no per-keyword scan count queries."""
    due = is_keyword_due(keyword, now=reference)
    overdue = _overdue_seconds(keyword.next_scan_at, reference) if due else 0.0
    return {
        "lifecycle_status": keyword.lifecycle_status,
        "source_type": keyword.source_type,
        "last_checked": keyword.last_checked,
        "next_scan_at": keyword.next_scan_at,
        "scan_interval_seconds": keyword.scan_interval_seconds,
        "is_due": due,
        "overdue_seconds": overdue,
        "scheduling_hint": None,
    }


def evaluate_keyword_performance_batch(
    session: Session,
    keyword_records: list[TargetKeyword],
    *,
    from_timestamp: datetime | None = None,
    to_timestamp: datetime | None = None,
    attribution_mode: AttributionMode = "all_hits",
    include_current_tiers: bool = False,
    include_breakout: bool = True,
    include_delayed: bool = True,
    evaluated_at: datetime | None = None,
    breakout_bundle: GlobalBreakoutBundle | None = None,
) -> KeywordPerformanceListResult:
    reference = evaluated_at or utc_now()
    options = KeywordEvaluationOptions(
        include_breakout=include_breakout,
        include_delayed=include_delayed,
    )
    bundle = breakout_bundle
    if options.include_breakout:
        if bundle is None:
            bundle = build_global_breakout_bundle(session, evaluated_at=reference)
        breakout_map = bundle.breakout_map
        global_n = bundle.global_eligible_video_count
        states_by_id = bundle.states_by_id
    else:
        breakout_map = {}
        global_n = 0
        states_by_id = None

    context = make_evaluation_context(
        global_eligible_video_count=global_n if options.include_breakout else 0,
        attribution_mode=attribution_mode,
        window_from=from_timestamp,
        window_to=to_timestamp,
        evaluated_at=reference,
    )

    batch = evaluate_keywords_batch(
        session,
        keyword_records,
        context=context,
        breakout_map=breakout_map,
        include_current_tiers=include_current_tiers,
        options=options,
        monitoring_states_by_id=states_by_id,
    )
    items: list[KeywordPerformanceMetrics] = []
    for keyword in keyword_records:
        agg = batch.get(keyword.id)
        if agg is None:
            continue
        items.append(
            _batch_to_metrics(agg, keyword, context, _schedule_fields_fast(keyword, reference)),
        )
    return KeywordPerformanceListResult(context=context, items=items)


def get_keyword_performance(
    session: Session,
    keyword_id: int,
    *,
    from_timestamp: datetime | None = None,
    to_timestamp: datetime | None = None,
    include_current_tiers: bool = False,
    include_breakout: bool = True,
    include_delayed: bool = True,
    attribution_mode: AttributionMode = "all_hits",
) -> KeywordPerformanceMetrics | None:
    keyword = session.get(TargetKeyword, keyword_id)
    if keyword is None:
        return None
    result = evaluate_keyword_performance_batch(
        session,
        [keyword],
        from_timestamp=from_timestamp,
        to_timestamp=to_timestamp,
        attribution_mode=attribution_mode,
        include_current_tiers=include_current_tiers,
        include_breakout=include_breakout,
        include_delayed=include_delayed,
    )
    if not result.items:
        return None
    return result.items[0]


def list_keyword_performance(
    session: Session,
    *,
    limit: int = 100,
    from_timestamp: datetime | None = None,
    to_timestamp: datetime | None = None,
    include_current_tiers: bool = False,
    include_breakout: bool = True,
    include_delayed: bool = True,
    attribution_mode: AttributionMode = "all_hits",
) -> KeywordPerformanceListResult:
    keyword_records = list(
        session.scalars(
            select(TargetKeyword).order_by(TargetKeyword.id.asc()).limit(max(1, limit)),
        ).all(),
    )
    return evaluate_keyword_performance_batch(
        session,
        keyword_records,
        from_timestamp=from_timestamp,
        to_timestamp=to_timestamp,
        attribution_mode=attribution_mode,
        include_current_tiers=include_current_tiers,
        include_breakout=include_breakout,
        include_delayed=include_delayed,
    )


# Legacy helper: list returns items only for callers expecting list[KeywordPerformanceMetrics]
def list_keyword_performance_items(
    session: Session,
    **kwargs,
) -> list[KeywordPerformanceMetrics]:
    return list_keyword_performance(session, **kwargs).items
