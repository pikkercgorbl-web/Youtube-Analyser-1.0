"""Operational read model for runtime health (Stage 1.19B)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models.orm import (
    DiscoveryWorkerState,
    KeywordDiscoveryHit,
    KeywordScanRun,
    MonitoringCycleRun,
    MonitoringWorkerState,
    OutcomeCaptureWorkerState,
    TargetKeyword,
    VideoSnapshot,
)
from app.services.discovery_worker_lock import (
    DEFAULT_STALE_LOCK_MINUTES,
    DISCOVERY_STATUS_RUNNING,
    DISCOVERY_STATUS_STOPPED,
    DISCOVERY_WORKER_STATE_ROW_ID,
)
from app.services.monitoring_worker_lock import MONITORING_WORKER_STATE_ROW_ID
from app.services.discovery_worker_runtime import DEFAULT_DISCOVERY_WORKER_INTERVAL_SECONDS
from app.services.delayed_outcome_capture_config import DEFAULT_OUTCOME_CAPTURE_INTERVAL_SECONDS
from app.services.delayed_outcome_capture_planner import plan_delayed_outcome_capture
from app.services.monitoring_cycle import DEFAULT_MONITORING_WORKER_INTERVAL_SECONDS
from app.services.outcome_capture_cycle_run_storage import get_latest_outcome_capture_cycle_run
from app.services.outcome_capture_worker_lock import (
    OUTCOME_CAPTURE_WORKER_STATE_ROW_ID,
    OUTCOME_STATUS_RUNNING,
)
from app.services.worker_activity_policy import (
    STALE_ACTIVITY_MISSED_INTERVALS,
    classify_worker_activity,
    stale_activity_threshold_seconds,
)
from app.services.keyword_performance_evaluation import (
    HORIZON_HOURS,
    HORIZON_SNAPSHOT_TOLERANCE_HOURS,
    KeywordVideoBaseline,
    _first_discovery_owner,
    _first_hit_per_keyword_video,
    load_snapshots_for_horizon,
    match_horizon_outcome,
)
from app.services.keyword_scheduling_policy import LIFECYCLE_ARCHIVED
from app.services.metrics import ensure_utc, utc_now
from app.services.monitoring_api_service import get_monitoring_overview, get_monitoring_worker_status
from app.services.monitoring_cycle_run_storage import get_latest_monitoring_cycle_run, list_monitoring_cycle_runs

ActivityState = Literal["active_recently", "stale_activity", "unknown", "error"]
OutcomeAttributionMode = Literal["all_hits", "first_discovery"]

_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|authorization|bearer|token|secret|password)\s*[:=]\s*\S+"),
    re.compile(r"(?i)AIza[0-9A-Za-z_-]{20,}"),
)

_MAX_ERROR_LEN = 400


def _sanitize_error(text: str | None) -> str | None:
    if not text or not str(text).strip():
        return None
    cleaned = str(text).strip()
    for pattern in _SECRET_PATTERNS:
        cleaned = pattern.sub("[redacted]", cleaned)
    if len(cleaned) > _MAX_ERROR_LEN:
        cleaned = cleaned[: _MAX_ERROR_LEN - 3] + "..."
    return cleaned


@dataclass(frozen=True, slots=True)
class WorkerActivityBlock:
    lock_status: str | None
    lock_holder: str | None
    lock_acquired_at: datetime | None
    last_activity_at: datetime | None
    activity_state: ActivityState
    expected_interval_seconds: int
    stale_lock_minutes: int
    liveness_note: str


@dataclass(frozen=True, slots=True)
class DiscoveryCycleSummaryOps:
    discovery_run_id: str
    started_at: datetime | None
    finished_at: datetime | None
    runtime_seconds: float | None
    keywords_scanned: int
    raw_candidates: int
    unique_candidates: int
    persisted_videos: int
    qualification_passed: int
    qualification_rejected: int
    keyword_scan_failures: int
    error_summaries: tuple[str, ...]


@dataclass
class DiscoveryOperationsBlock:
    worker: WorkerActivityBlock
    last_cycle_started_at: datetime | None = None
    last_cycle_finished_at: datetime | None = None
    last_cycle_status: str | None = None
    last_run_id: str | None = None
    last_error: str | None = None
    last_cycle_runtime_seconds: float | None = None
    keywords_scanned_last_cycle: int = 0
    raw_candidates_last_cycle: int = 0
    unique_videos_last_cycle: int = 0
    persisted_videos_last_cycle: int = 0
    keyword_errors_last_cycle: int = 0
    keywords_due_now: int = 0
    keywords_due_next_1h: int = 0
    keywords_due_next_24h: int = 0
    keywords_due_next_24h_includes_1h: bool = True


@dataclass
class MonitoringOperationsBlock:
    worker: WorkerActivityBlock
    last_cycle_started_at: datetime | None = None
    last_cycle_finished_at: datetime | None = None
    last_cycle_status: str | None = None
    last_run_id: str | None = None
    last_cycle_runtime_seconds: float | None = None
    loaded_video_count: int = 0
    eligible_video_count: int = 0
    selected_capture_count: int = 0
    inserted_snapshot_count: int = 0
    missing_count: int = 0
    fetch_failed_count: int = 0
    validation_failed_count: int = 0
    persistence_failed_count: int = 0
    due_count_at_last_cycle: int = 0
    overdue_count_at_last_cycle: int = 0
    live_planner_due_count: int | None = None
    live_planner_overdue_count: int | None = None
    live_planner_requested: bool = False


@dataclass
class SnapshotDailyCount:
    date: str
    count: int


@dataclass
class SnapshotOperationsBlock:
    latest_snapshot_at: datetime | None = None
    snapshots_last_1h: int = 0
    snapshots_last_24h: int = 0
    unique_videos_snapshotted_last_24h: int = 0
    daily_counts_last_7d: list[SnapshotDailyCount] = field(default_factory=list)


@dataclass
class KeywordOutcomeOperationsBlock:
    attribution_mode: OutcomeAttributionMode
    horizon_hours: int
    tolerance_hours: int
    attributed_observation_count: int = 0
    pending_72h_count: int = 0
    matured_72h_count: int = 0
    valid_72h_outcome_count: int = 0
    missing_72h_outcome_count: int = 0
    matures_next_6h: int = 0
    matures_next_24h: int = 0
    matures_next_48h: int = 0


@dataclass
class OutcomeCaptureOperationsBlock:
    worker: WorkerActivityBlock
    planner_pending: int = 0
    planner_due: int = 0
    planner_overdue: int = 0
    planner_satisfied: int = 0
    planner_expired: int = 0
    unique_due_videos: int = 0
    last_cycle_started_at: datetime | None = None
    last_cycle_finished_at: datetime | None = None
    last_cycle_status: str | None = None
    last_run_id: str | None = None
    selected_video_count_last_cycle: int = 0
    deferred_video_count_last_cycle: int = 0
    inserted_snapshot_count_last_cycle: int = 0
    fetch_failed_count_last_cycle: int = 0
    duplicate_snapshot_count_last_cycle: int = 0
    missing_video_count_last_cycle: int = 0


@dataclass
class OperationsErrorsBlock:
    discovery_last_cycle_error: str | None = None
    monitoring_recent_error_summaries: list[str] = field(default_factory=list)


@dataclass
class RecentCyclesBlock:
    discovery: list[DiscoveryCycleSummaryOps] = field(default_factory=list)
    monitoring: list[MonitoringCycleRun] = field(default_factory=list)


@dataclass
class OperationsOverview:
    generated_at: datetime
    discovery: DiscoveryOperationsBlock
    monitoring: MonitoringOperationsBlock
    outcome_capture: OutcomeCaptureOperationsBlock
    snapshots: SnapshotOperationsBlock
    keyword_outcomes: KeywordOutcomeOperationsBlock
    errors: OperationsErrorsBlock
    recent_cycles: RecentCyclesBlock


def _discovery_activity_state(
    state: DiscoveryWorkerState | None,
    *,
    now: datetime,
    expected_interval_seconds: int,
) -> tuple[ActivityState, datetime | None]:
    if state is None:
        return "unknown", None

    last_activity = state.last_cycle_finished_at or state.updated_at
    latest_failed = state.last_cycle_status == "failed" or bool(state.last_error)
    expected_running = state.status == DISCOVERY_STATUS_RUNNING

    return classify_worker_activity(
        now=now,
        worker_expected_running=expected_running,
        last_activity_at=last_activity,
        expected_interval_seconds=expected_interval_seconds,
        latest_cycle_failed=latest_failed,
    )


def get_discovery_worker_activity(
    session: Session,
    *,
    now: datetime | None = None,
    worker_state: DiscoveryWorkerState | None = None,
) -> WorkerActivityBlock:
    reference = now or utc_now()
    state = worker_state
    if state is None:
        state = session.get(DiscoveryWorkerState, DISCOVERY_WORKER_STATE_ROW_ID)
    activity, last_at = _discovery_activity_state(
        state,
        now=reference,
        expected_interval_seconds=DEFAULT_DISCOVERY_WORKER_INTERVAL_SECONDS,
    )
    stale_activity_seconds = stale_activity_threshold_seconds(DEFAULT_DISCOVERY_WORKER_INTERVAL_SECONDS)
    return WorkerActivityBlock(
        lock_status=state.status if state else None,
        lock_holder=state.lock_holder if state else None,
        lock_acquired_at=state.lock_acquired_at if state else None,
        last_activity_at=last_at,
        activity_state=activity,
        expected_interval_seconds=DEFAULT_DISCOVERY_WORKER_INTERVAL_SECONDS,
        stale_lock_minutes=DEFAULT_STALE_LOCK_MINUTES,
        liveness_note=(
            f"Activity from last cycle finish or worker heartbeat; stale after ~{stale_activity_seconds}s "
            f"({STALE_ACTIVITY_MISSED_INTERVALS}× interval). lock_acquired_at is lock diagnostics only."
        ),
    )


def _monitoring_activity_block(
    status_data,
    *,
    latest_cycle_finished_at: datetime | None,
    latest_cycle_failed: bool,
    worker_db_status: str | None,
) -> WorkerActivityBlock:
    from app.services.monitoring_worker_lock import MONITORING_STATUS_RUNNING

    last_activity = latest_cycle_finished_at or status_data.last_seen
    expected_running = worker_db_status == MONITORING_STATUS_RUNNING

    activity, last_at = classify_worker_activity(
        now=status_data.current_time,
        worker_expected_running=expected_running,
        last_activity_at=last_activity,
        expected_interval_seconds=status_data.worker_interval_seconds,
        latest_cycle_failed=latest_cycle_failed,
    )
    stale_activity_seconds = stale_activity_threshold_seconds(status_data.worker_interval_seconds)
    return WorkerActivityBlock(
        lock_status=status_data.status,
        lock_holder=status_data.lock_holder,
        lock_acquired_at=status_data.lock_acquired_at,
        last_activity_at=last_at,
        activity_state=activity,
        expected_interval_seconds=status_data.worker_interval_seconds,
        stale_lock_minutes=status_data.stale_after_seconds // 60,
        liveness_note=(
            f"Activity from monitoring cycle finish or worker heartbeat; stale after ~{stale_activity_seconds}s. "
            "lock_acquired_at is lock diagnostics only."
        ),
    )


def count_keywords_due(session: Session, *, now: datetime | None = None) -> tuple[int, int, int]:
    """
    Returns (due_now, due_next_1h_exclusive, due_next_24h_cumulative).

    due_next_24h counts (now, now+24h] and includes the 1h window (cumulative upcoming).
    due_next_1h counts (now, now+1h] only.
    """
    from app.services.operations_overview_queries import count_keywords_due_batch

    return count_keywords_due_batch(session, now=now)


def count_keywords_due_sequential(session: Session, *, now: datetime | None = None) -> tuple[int, int, int]:
    """Pre-1.19B2 reference (three round-trips). Tests only."""
    reference = ensure_utc(now or utc_now())
    in_1h = reference + timedelta(hours=1)
    in_24h = reference + timedelta(hours=24)
    base = and_(
        TargetKeyword.lifecycle_status != LIFECYCLE_ARCHIVED,
    )
    due_now_clause = or_(
        TargetKeyword.next_scan_at.is_(None),
        TargetKeyword.next_scan_at <= reference,
    )
    due_now = session.scalar(
        select(func.count()).select_from(TargetKeyword).where(base, due_now_clause),
    ) or 0
    due_1h = session.scalar(
        select(func.count())
        .select_from(TargetKeyword)
        .where(
            base,
            TargetKeyword.next_scan_at.is_not(None),
            TargetKeyword.next_scan_at > reference,
            TargetKeyword.next_scan_at <= in_1h,
        ),
    ) or 0
    due_24h = session.scalar(
        select(func.count())
        .select_from(TargetKeyword)
        .where(
            base,
            TargetKeyword.next_scan_at.is_not(None),
            TargetKeyword.next_scan_at > reference,
            TargetKeyword.next_scan_at <= in_24h,
        ),
    ) or 0
    return int(due_now), int(due_1h), int(due_24h)


def aggregate_discovery_cycle(session: Session, discovery_run_id: str) -> DiscoveryCycleSummaryOps:
    rows = list(
        session.scalars(
            select(KeywordScanRun).where(KeywordScanRun.discovery_run_id == discovery_run_id),
        ).all(),
    )
    if not rows:
        return DiscoveryCycleSummaryOps(
            discovery_run_id=discovery_run_id,
            started_at=None,
            finished_at=None,
            runtime_seconds=None,
            keywords_scanned=0,
            raw_candidates=0,
            unique_candidates=0,
            persisted_videos=0,
            qualification_passed=0,
            qualification_rejected=0,
            keyword_scan_failures=0,
            error_summaries=(),
        )

    started = min(r.started_at for r in rows)
    finished = max(r.finished_at for r in rows)
    runtime = max((r.runtime_seconds for r in rows), default=0.0)
    failures = sum(1 for r in rows if r.status != "ok")
    summaries = tuple(
        s for s in (_sanitize_error(r.error_summary) for r in rows if r.error_summary) if s
    )
    return DiscoveryCycleSummaryOps(
        discovery_run_id=discovery_run_id,
        started_at=started,
        finished_at=finished,
        runtime_seconds=round(float(runtime), 4),
        keywords_scanned=len(rows),
        raw_candidates=sum(r.raw_candidates for r in rows),
        unique_candidates=sum(r.unique_candidates for r in rows),
        persisted_videos=sum(r.persisted_videos for r in rows),
        qualification_passed=sum(r.qualification_passed for r in rows),
        qualification_rejected=sum(r.qualification_rejected for r in rows),
        keyword_scan_failures=failures,
        error_summaries=summaries[:10],
    )


def list_recent_discovery_run_ids(session: Session, *, limit: int) -> list[str]:
    stmt = (
        select(
            KeywordScanRun.discovery_run_id,
            func.max(KeywordScanRun.started_at).label("last_start"),
        )
        .group_by(KeywordScanRun.discovery_run_id)
        .order_by(func.max(KeywordScanRun.started_at).desc())
        .limit(max(1, min(limit, 50)))
    )
    return [row[0] for row in session.execute(stmt).all()]


def _apply_discovery_cycle_to_block(block: DiscoveryOperationsBlock, summary: DiscoveryCycleSummaryOps) -> None:
    block.last_cycle_runtime_seconds = summary.runtime_seconds
    block.keywords_scanned_last_cycle = summary.keywords_scanned
    block.raw_candidates_last_cycle = summary.raw_candidates
    block.unique_videos_last_cycle = summary.unique_candidates
    block.persisted_videos_last_cycle = summary.persisted_videos
    block.keyword_errors_last_cycle = summary.keyword_scan_failures
    if summary.started_at:
        block.last_cycle_started_at = summary.started_at
    if summary.finished_at:
        block.last_cycle_finished_at = summary.finished_at


def build_snapshot_metrics(session: Session, *, now: datetime | None = None) -> SnapshotOperationsBlock:
    from app.services.operations_overview_queries import build_snapshot_metrics_batch

    return build_snapshot_metrics_batch(session, now=now)


def build_snapshot_metrics_sequential(session: Session, *, now: datetime | None = None) -> SnapshotOperationsBlock:
    """Pre-1.19B2 reference. Tests only."""
    reference = ensure_utc(now or utc_now())
    since_1h = reference - timedelta(hours=1)
    since_24h = reference - timedelta(hours=24)

    latest_raw = session.scalar(select(func.max(VideoSnapshot.captured_at)))
    latest = ensure_utc(latest_raw) if latest_raw is not None else None
    count_1h = session.scalar(
        select(func.count())
        .select_from(VideoSnapshot)
        .where(VideoSnapshot.captured_at >= since_1h),
    ) or 0
    count_24h = session.scalar(
        select(func.count())
        .select_from(VideoSnapshot)
        .where(VideoSnapshot.captured_at >= since_24h),
    ) or 0
    unique_24h = session.scalar(
        select(func.count(func.distinct(VideoSnapshot.video_id)))
        .select_from(VideoSnapshot)
        .where(VideoSnapshot.captured_at >= since_24h),
    ) or 0

    daily: list[SnapshotDailyCount] = []
    for days_ago in range(6, -1, -1):
        day_start = (reference - timedelta(days=days_ago)).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        day_end = day_start + timedelta(days=1)
        cnt = (
            session.scalar(
                select(func.count())
                .select_from(VideoSnapshot)
                .where(
                    VideoSnapshot.captured_at >= day_start,
                    VideoSnapshot.captured_at < day_end,
                ),
            )
            or 0
        )
        daily.append(SnapshotDailyCount(date=day_start.date().isoformat(), count=int(cnt)))

    return SnapshotOperationsBlock(
        latest_snapshot_at=latest,
        snapshots_last_1h=int(count_1h),
        snapshots_last_24h=int(count_24h),
        unique_videos_snapshotted_last_24h=int(unique_24h),
        daily_counts_last_7d=daily,
    )


def _load_all_hits_baselines(session: Session) -> list[KeywordVideoBaseline]:
    hits = list(session.scalars(select(KeywordDiscoveryHit)).all())
    if not hits:
        return []
    first_map = _first_hit_per_keyword_video(hits)
    baselines: list[KeywordVideoBaseline] = []
    for (kid, vid), hit in first_map.items():
        baselines.append(
            KeywordVideoBaseline(
                keyword_id=kid,
                video_id=vid,
                discovery_at=hit.discovered_at,
                views_at_discovery=hit.views_at_discovery,
                vph_at_discovery=hit.vph_at_discovery,
            ),
        )
    return baselines


def _load_first_discovery_baselines(session: Session) -> list[KeywordVideoBaseline]:
    hits = list(session.scalars(select(KeywordDiscoveryHit)).all())
    if not hits:
        return []
    owner = _first_discovery_owner(hits)
    first_map = _first_hit_per_keyword_video(hits)
    baselines: list[KeywordVideoBaseline] = []
    for vid, kid in owner.items():
        hit = first_map.get((kid, vid))
        if hit is None:
            continue
        baselines.append(
            KeywordVideoBaseline(
                keyword_id=kid,
                video_id=vid,
                discovery_at=hit.discovered_at,
                views_at_discovery=hit.views_at_discovery,
                vph_at_discovery=hit.vph_at_discovery,
            ),
        )
    return baselines


def compute_keyword_outcome_maturity_legacy(
    session: Session,
    *,
    attribution_mode: OutcomeAttributionMode = "all_hits",
    now: datetime | None = None,
) -> KeywordOutcomeOperationsBlock:
    reference = ensure_utc(now or utc_now())
    if attribution_mode == "first_discovery":
        baselines = _load_first_discovery_baselines(session)
    else:
        baselines = _load_all_hits_baselines(session)

    block = KeywordOutcomeOperationsBlock(
        attribution_mode=attribution_mode,
        horizon_hours=HORIZON_HOURS,
        tolerance_hours=HORIZON_SNAPSHOT_TOLERANCE_HOURS,
        attributed_observation_count=len(baselines),
    )

    matured: list[KeywordVideoBaseline] = []
    for base in baselines:
        maturity_at = ensure_utc(base.discovery_at) + timedelta(hours=HORIZON_HOURS)
        if reference < maturity_at:
            block.pending_72h_count += 1
            if reference < maturity_at <= reference + timedelta(hours=6):
                block.matures_next_6h += 1
            if reference < maturity_at <= reference + timedelta(hours=24):
                block.matures_next_24h += 1
            if reference < maturity_at <= reference + timedelta(hours=48):
                block.matures_next_48h += 1
        else:
            block.matured_72h_count += 1
            if base.views_at_discovery is not None:
                matured.append(base)

    if matured:
        min_discovery = min(ensure_utc(b.discovery_at) for b in matured)
        max_discovery = max(ensure_utc(b.discovery_at) for b in matured)
        captured_from = min_discovery + timedelta(hours=HORIZON_HOURS - HORIZON_SNAPSHOT_TOLERANCE_HOURS)
        captured_to = max_discovery + timedelta(hours=HORIZON_HOURS + HORIZON_SNAPSHOT_TOLERANCE_HOURS)
        video_ids = {b.video_id for b in matured}
        snapshots = load_snapshots_for_horizon(
            session,
            video_ids,
            captured_from=captured_from,
            captured_to=captured_to,
        )

        for base in matured:
            outcome = match_horizon_outcome(base, snapshots)
            if outcome is not None:
                block.valid_72h_outcome_count += 1

    block.missing_72h_outcome_count = block.matured_72h_count - block.valid_72h_outcome_count
    return block


def compute_keyword_outcome_maturity(
    session: Session,
    *,
    attribution_mode: OutcomeAttributionMode = "all_hits",
    now: datetime | None = None,
) -> KeywordOutcomeOperationsBlock:
    from app.services.operations_maturity_sql import compute_maturity_aggregate_sql

    result = compute_maturity_aggregate_sql(
        session,
        attribution_mode=attribution_mode,
        now=now,
    )
    return KeywordOutcomeOperationsBlock(
        attribution_mode=result.attribution_mode,
        horizon_hours=result.horizon_hours,
        tolerance_hours=result.tolerance_hours,
        attributed_observation_count=result.attributed_observation_count,
        pending_72h_count=result.pending_72h_count,
        matured_72h_count=result.matured_72h_count,
        valid_72h_outcome_count=result.valid_72h_outcome_count,
        missing_72h_outcome_count=result.missing_72h_outcome_count,
        matures_next_6h=result.matures_next_6h,
        matures_next_24h=result.matures_next_24h,
        matures_next_48h=result.matures_next_48h,
    )


def get_outcome_capture_worker_activity(
    session: Session,
    *,
    now: datetime | None = None,
    worker_state: OutcomeCaptureWorkerState | None = None,
) -> WorkerActivityBlock:
    reference = now or utc_now()
    state = worker_state
    if state is None:
        state = session.get(OutcomeCaptureWorkerState, OUTCOME_CAPTURE_WORKER_STATE_ROW_ID)
    last_at = None
    if state is not None:
        last_at = state.last_cycle_finished_at or state.updated_at
    activity, resolved_last = classify_worker_activity(
        now=reference,
        worker_expected_running=bool(state and state.status == OUTCOME_STATUS_RUNNING),
        last_activity_at=last_at,
        expected_interval_seconds=DEFAULT_OUTCOME_CAPTURE_INTERVAL_SECONDS,
        latest_cycle_failed=bool(state and (state.last_cycle_status == "failed" or state.last_error)),
    )
    stale_activity_seconds = stale_activity_threshold_seconds(DEFAULT_OUTCOME_CAPTURE_INTERVAL_SECONDS)
    return WorkerActivityBlock(
        lock_status=state.status if state else None,
        lock_holder=state.lock_holder if state else None,
        lock_acquired_at=state.lock_acquired_at if state else None,
        last_activity_at=resolved_last,
        activity_state=activity,
        expected_interval_seconds=DEFAULT_OUTCOME_CAPTURE_INTERVAL_SECONDS,
        stale_lock_minutes=DEFAULT_STALE_LOCK_MINUTES,
        liveness_note=(
            f"Delayed outcome capture worker; stale after ~{stale_activity_seconds}s "
            f"({STALE_ACTIVITY_MISSED_INTERVALS}× interval). Separate from monitoring."
        ),
    )


def build_outcome_capture_block(
    session: Session,
    *,
    now: datetime | None = None,
    outcome_attribution_mode: OutcomeAttributionMode = "all_hits",
    include_live_planner: bool = False,
) -> OutcomeCaptureOperationsBlock:
    reference = now or utc_now()
    worker_state = session.get(OutcomeCaptureWorkerState, OUTCOME_CAPTURE_WORKER_STATE_ROW_ID)
    latest = get_latest_outcome_capture_cycle_run(session)
    if include_live_planner:
        plan = plan_delayed_outcome_capture(
            session,
            reference=reference,
            attribution_mode=outcome_attribution_mode,
        )
        planner_pending = plan.pending_count
        planner_due = plan.capture_due_count
        planner_overdue = plan.capture_overdue_count
        planner_satisfied = plan.satisfied_count
        planner_expired = plan.expired_count
        unique_due_videos = plan.unique_due_video_count
    elif latest is not None:
        planner_pending = int(latest.pending_count)
        planner_due = int(latest.capture_due_count)
        planner_overdue = int(latest.capture_overdue_count)
        planner_satisfied = int(latest.satisfied_existing_count)
        planner_expired = int(latest.expired_count)
        unique_due_videos = int(latest.unique_due_video_count)
    else:
        planner_pending = planner_due = planner_overdue = 0
        planner_satisfied = planner_expired = unique_due_videos = 0

    block = OutcomeCaptureOperationsBlock(
        worker=get_outcome_capture_worker_activity(
            session,
            now=reference,
            worker_state=worker_state,
        ),
        planner_pending=planner_pending,
        planner_due=planner_due,
        planner_overdue=planner_overdue,
        planner_satisfied=planner_satisfied,
        planner_expired=planner_expired,
        unique_due_videos=unique_due_videos,
    )
    if worker_state:
        block.last_cycle_started_at = worker_state.last_cycle_started_at
        block.last_cycle_finished_at = worker_state.last_cycle_finished_at
        block.last_cycle_status = worker_state.last_cycle_status
        block.last_run_id = worker_state.last_run_id

    if latest is not None:
        block.selected_video_count_last_cycle = latest.selected_video_count
        block.deferred_video_count_last_cycle = latest.deferred_video_count
        block.inserted_snapshot_count_last_cycle = latest.inserted_snapshot_count
        block.fetch_failed_count_last_cycle = latest.fetch_failed_count
        block.duplicate_snapshot_count_last_cycle = latest.duplicate_snapshot_count
        block.missing_video_count_last_cycle = latest.missing_video_count
        if not block.last_cycle_started_at:
            block.last_cycle_started_at = latest.started_at
        if not block.last_cycle_finished_at:
            block.last_cycle_finished_at = latest.finished_at
        if not block.last_cycle_status:
            block.last_cycle_status = latest.cycle_status
        if not block.last_run_id:
            block.last_run_id = latest.run_id
    return block


def build_monitoring_block(
    session: Session,
    *,
    include_live_planner: bool,
    cycle_runs: list[MonitoringCycleRun] | None = None,
) -> MonitoringOperationsBlock:
    latest = cycle_runs[0] if cycle_runs else None
    if latest is None:
        latest = get_latest_monitoring_cycle_run(session)

    mon_state = session.get(MonitoringWorkerState, MONITORING_WORKER_STATE_ROW_ID)
    status = get_monitoring_worker_status(session)
    worker = _monitoring_activity_block(
        status,
        latest_cycle_finished_at=latest.finished_at if latest else None,
        latest_cycle_failed=bool(latest and latest.cycle_status == "failed"),
        worker_db_status=mon_state.status if mon_state else None,
    )
    block = MonitoringOperationsBlock(worker=worker, live_planner_requested=include_live_planner)
    if latest:
        block.last_cycle_started_at = latest.started_at
        block.last_cycle_finished_at = latest.finished_at
        block.last_cycle_status = latest.cycle_status
        block.last_run_id = latest.run_id
        block.last_cycle_runtime_seconds = latest.runtime_seconds
        block.loaded_video_count = latest.loaded_video_count
        block.eligible_video_count = latest.eligible_video_count
        block.selected_capture_count = latest.selected_request_count
        block.inserted_snapshot_count = latest.inserted_snapshot_count
        block.missing_count = latest.missing_count
        block.fetch_failed_count = latest.fetch_failed_count
        block.validation_failed_count = latest.validation_failed_count
        block.persistence_failed_count = latest.persistence_failed_count
        block.due_count_at_last_cycle = latest.due_count
        block.overdue_count_at_last_cycle = latest.overdue_count

    if include_live_planner:
        overview = get_monitoring_overview(session)
        block.live_planner_due_count = overview.due_count
        block.live_planner_overdue_count = overview.overdue_count

    return block


def build_operations_overview(
    session: Session,
    *,
    include_live_monitoring_planner: bool = False,
    include_live_outcome_planner: bool = False,
    discovery_history_limit: int = 10,
    monitoring_history_limit: int = 10,
    outcome_attribution_mode: OutcomeAttributionMode = "all_hits",
    now: datetime | None = None,
) -> OperationsOverview:
    from app.services.operations_overview_queries import (
        fetch_discovery_worker_state,
        load_discovery_cycle_summaries,
        load_monitoring_cycle_runs,
    )

    reference = now or utc_now()
    worker_state = fetch_discovery_worker_state(session)
    discovery = DiscoveryOperationsBlock(
        worker=get_discovery_worker_activity(session, now=reference, worker_state=worker_state),
    )

    if worker_state:
        discovery.last_cycle_started_at = worker_state.last_cycle_started_at
        discovery.last_cycle_finished_at = worker_state.last_cycle_finished_at
        discovery.last_cycle_status = worker_state.last_cycle_status
        discovery.last_run_id = worker_state.last_run_id
        discovery.last_error = _sanitize_error(worker_state.last_error)

    due_now, due_1h, due_24h = count_keywords_due(session, now=reference)
    discovery.keywords_due_now = due_now
    discovery.keywords_due_next_1h = due_1h
    discovery.keywords_due_next_24h = due_24h
    discovery.keywords_due_next_24h_includes_1h = True

    disc_summaries, disc_by_id = load_discovery_cycle_summaries(
        session,
        history_limit=discovery_history_limit,
        extra_run_id=discovery.last_run_id,
    )
    last_run_id = discovery.last_run_id
    if last_run_id and last_run_id in disc_by_id:
        last_summary = disc_by_id[last_run_id]
        _apply_discovery_cycle_to_block(discovery, last_summary)
        if not discovery.last_cycle_started_at:
            discovery.last_cycle_started_at = last_summary.started_at
        if not discovery.last_cycle_finished_at:
            discovery.last_cycle_finished_at = last_summary.finished_at

    mon_history = load_monitoring_cycle_runs(session, limit=monitoring_history_limit)
    monitoring = build_monitoring_block(
        session,
        include_live_planner=include_live_monitoring_planner,
        cycle_runs=mon_history,
    )
    snapshots = build_snapshot_metrics(session, now=reference)
    outcomes = compute_keyword_outcome_maturity(
        session,
        attribution_mode=outcome_attribution_mode,
        now=reference,
    )
    outcome_capture = build_outcome_capture_block(
        session,
        now=reference,
        outcome_attribution_mode=outcome_attribution_mode,
        include_live_planner=include_live_outcome_planner,
    )

    errors = OperationsErrorsBlock(
        discovery_last_cycle_error=discovery.last_error,
        monitoring_recent_error_summaries=[
            s
            for s in (
                _sanitize_error(row.error_summary)
                for row in mon_history
                if row.error_summary
            )
            if s
        ][:10],
    )

    return OperationsOverview(
        generated_at=reference,
        discovery=discovery,
        monitoring=monitoring,
        outcome_capture=outcome_capture,
        snapshots=snapshots,
        keyword_outcomes=outcomes,
        errors=errors,
        recent_cycles=RecentCyclesBlock(discovery=disc_summaries, monitoring=mon_history),
    )


def build_operations_overview_sequential(
    session: Session,
    *,
    include_live_monitoring_planner: bool = False,
    discovery_history_limit: int = 10,
    monitoring_history_limit: int = 10,
    outcome_attribution_mode: OutcomeAttributionMode = "all_hits",
    now: datetime | None = None,
) -> OperationsOverview:
    """Pre-1.19B2 query pattern. Parity tests only."""
    reference = now or utc_now()
    discovery = DiscoveryOperationsBlock(worker=get_discovery_worker_activity(session, now=reference))

    worker_state = session.get(DiscoveryWorkerState, DISCOVERY_WORKER_STATE_ROW_ID)
    if worker_state:
        discovery.last_cycle_started_at = worker_state.last_cycle_started_at
        discovery.last_cycle_finished_at = worker_state.last_cycle_finished_at
        discovery.last_cycle_status = worker_state.last_cycle_status
        discovery.last_run_id = worker_state.last_run_id
        discovery.last_error = _sanitize_error(worker_state.last_error)

    due_now, due_1h, due_24h = count_keywords_due_sequential(session, now=reference)
    discovery.keywords_due_now = due_now
    discovery.keywords_due_next_1h = due_1h
    discovery.keywords_due_next_24h = due_24h
    discovery.keywords_due_next_24h_includes_1h = True

    last_run_id = discovery.last_run_id
    if last_run_id:
        last_summary = aggregate_discovery_cycle(session, last_run_id)
        _apply_discovery_cycle_to_block(discovery, last_summary)
        if not discovery.last_cycle_started_at:
            discovery.last_cycle_started_at = last_summary.started_at
        if not discovery.last_cycle_finished_at:
            discovery.last_cycle_finished_at = last_summary.finished_at

    mon_history = list_monitoring_cycle_runs(session, limit=monitoring_history_limit)
    monitoring = build_monitoring_block(
        session,
        include_live_planner=include_live_monitoring_planner,
        cycle_runs=mon_history,
    )
    snapshots = build_snapshot_metrics_sequential(session, now=reference)
    outcomes = compute_keyword_outcome_maturity(
        session,
        attribution_mode=outcome_attribution_mode,
        now=reference,
    )
    outcome_capture = build_outcome_capture_block(
        session,
        now=reference,
        outcome_attribution_mode=outcome_attribution_mode,
    )

    disc_ids = list_recent_discovery_run_ids(session, limit=discovery_history_limit)
    disc_summaries = [aggregate_discovery_cycle(session, rid) for rid in disc_ids]

    errors = OperationsErrorsBlock(
        discovery_last_cycle_error=discovery.last_error,
        monitoring_recent_error_summaries=[
            s
            for s in (
                _sanitize_error(row.error_summary)
                for row in mon_history
                if row.error_summary
            )
            if s
        ][:10],
    )

    return OperationsOverview(
        generated_at=reference,
        discovery=discovery,
        monitoring=monitoring,
        outcome_capture=outcome_capture,
        snapshots=snapshots,
        keyword_outcomes=outcomes,
        errors=errors,
        recent_cycles=RecentCyclesBlock(discovery=disc_summaries, monitoring=mon_history),
    )
