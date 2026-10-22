"""Monitoring REST API read model (Stage 1.14A)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import Channel, MonitoringCycleRun, MonitoringWorkerState, Video, VideoSnapshot
from app.services.channel_velocity_baseline import compute_channel_velocity_baseline
from app.services.metrics import ensure_utc, utc_now
from app.services.monitoring_cycle import (
    DEFAULT_MONITORING_WORKER_INTERVAL_SECONDS,
    MonitoringCycleSummary,
)
from app.services.monitoring_cycle_run_storage import get_latest_monitoring_cycle_run, list_monitoring_cycle_runs
from app.services.monitoring_tier_budget_policy import (
    ApiBudgetPolicy,
    MonitoringDecision,
    MonitoringTier,
    MonitoringTierPolicy,
    assign_monitoring_tiers,
    apply_channel_active_cap,
    apply_global_monitoring_cap,
    snapshot_collection_policy_for_tier,
)
from app.services.breakout_ranking_service import (
    breakout_fundamental_eligibility,
    rank_breakout_v1,
)
from app.services.monitoring_video_source import (
    MonitoredVideoState,
    load_monitored_video_states,
)
from app.services.monitoring_worker_lock import (
    DEFAULT_STALE_LOCK_MINUTES,
    MONITORING_STATUS_RUNNING,
    MONITORING_STATUS_STOPPED,
    MONITORING_WORKER_STATE_ROW_ID,
)
from app.services.worker_activity_policy import classify_worker_activity
from app.services.snapshot_collection_policy import (
    VideoRevisitPlan,
    existing_snapshot_from_orm,
    load_snapshots_by_video_id,
    plan_video_revisits,
)
from app.services.snapshot_collection_policy import MONITORING_PLANNER_MAX_SNAPSHOT_AGE_HOURS
from app.services.video_snapshot_storage import (
    get_latest_snapshots_for_videos,
    get_snapshots_for_video,
    get_snapshots_for_videos_planner,
)

MonitoringSort = Literal[
    "priority",
    "breakout_v1",
    "vph_desc",
    "views_desc",
    "age_asc",
    "latest_snapshot_desc",
]
MonitoringListStatus = Literal["due", "overdue", "pending", "active", "stopped"]
WorkerStatusLabel = Literal["running", "stopped", "stale", "unknown"]


@dataclass(frozen=True, slots=True)
class MonitoringWorkerStatusData:
    status: WorkerStatusLabel
    lock_holder: str | None
    lock_acquired_at: datetime | None
    worker_interval_seconds: int
    stale_after_seconds: int
    last_seen: datetime | None
    is_lock_stale: bool
    current_time: datetime


@dataclass(frozen=True, slots=True)
class MonitoringOverviewData:
    active_monitored_count: int
    tier_counts: dict[str, int]
    unmonitored_count: int
    due_count: int
    overdue_count: int
    pending_count: int
    stopped_count: int
    latest_cycle: MonitoringCycleSummary | None


@dataclass
class MonitoringEnrichedVideo:
    state: MonitoredVideoState
    decision: MonitoringDecision
    plan: VideoRevisitPlan
    title: str | None
    channel_title: str | None
    latest_snapshot: VideoSnapshot | None
    current_views: int | None
    current_vph: float | None


@dataclass
class BreakoutVideoListRow:
    """Cap-independent breakout list row (planner optional)."""

    state: MonitoredVideoState
    decision: MonitoringDecision
    title: str | None
    channel_title: str | None
    latest_snapshot: VideoSnapshot | None
    current_views: int | None
    current_vph: float | None
    breakout_rank: int
    breakout_ranking_value: float
    in_active_capture_pool: bool
    plan: VideoRevisitPlan | None = None


def _state_to_tier_input(state: MonitoredVideoState):
    from app.services.monitoring_tier_budget_policy import TierCandidateInput

    return TierCandidateInput(
        video_id=state.video_id,
        channel_id=state.channel_id,
        raw_vph=state.raw_vph,
        age_hours=state.age_hours,
        published_at_present=True,
        content_format=state.content_format,
        is_short=state.is_short,
        is_live=state.is_live,
        channel_velocity_baseline_status=state.channel_velocity_baseline_status,
        vph_vs_channel_median=state.vph_vs_channel_median,
    )


def _resolve_worker_status(
    state: MonitoringWorkerState | None,
    *,
    now: datetime,
    lock_stale_after_seconds: int,
    latest_cycle_finished_at: datetime | None = None,
    latest_cycle_status: str | None = None,
) -> MonitoringWorkerStatusData:
    lock_acquired_at = state.lock_acquired_at if state else None
    lock_holder = state.lock_holder if state else None
    heartbeat_at = state.updated_at if state else None

    last_activity = latest_cycle_finished_at
    if heartbeat_at is not None:
        if last_activity is None or ensure_utc(heartbeat_at) > ensure_utc(last_activity):
            last_activity = heartbeat_at

    latest_failed = latest_cycle_status == "failed"
    expected_running = state is not None and state.status == MONITORING_STATUS_RUNNING
    activity_state, _ = classify_worker_activity(
        now=now,
        worker_expected_running=expected_running,
        last_activity_at=last_activity,
        expected_interval_seconds=DEFAULT_MONITORING_WORKER_INTERVAL_SECONDS,
        latest_cycle_failed=latest_failed,
    )

    is_lock_stale = False
    if state is not None and state.status == MONITORING_STATUS_RUNNING and lock_acquired_at is not None:
        lock_age = (ensure_utc(now) - ensure_utc(lock_acquired_at)).total_seconds()
        is_lock_stale = lock_age > lock_stale_after_seconds

    label: WorkerStatusLabel = "unknown"
    if state is None:
        label = "unknown"
    elif state.status == MONITORING_STATUS_STOPPED:
        label = "stopped"
    elif state.status == MONITORING_STATUS_RUNNING:
        if activity_state in ("stale_activity", "error"):
            label = "stale"
        else:
            label = "running"
    else:
        label = "unknown"

    return MonitoringWorkerStatusData(
        status=label,
        lock_holder=lock_holder,
        lock_acquired_at=lock_acquired_at,
        worker_interval_seconds=DEFAULT_MONITORING_WORKER_INTERVAL_SECONDS,
        stale_after_seconds=lock_stale_after_seconds,
        last_seen=last_activity,
        is_lock_stale=is_lock_stale,
        current_time=now,
    )


def get_monitoring_worker_status(
    session: Session,
    *,
    now: datetime | None = None,
) -> MonitoringWorkerStatusData:
    reference = now or utc_now()
    state = session.get(MonitoringWorkerState, MONITORING_WORKER_STATE_ROW_ID)
    latest = get_latest_monitoring_cycle_run(session)
    lock_stale_seconds = DEFAULT_STALE_LOCK_MINUTES * 60
    return _resolve_worker_status(
        state,
        now=reference,
        lock_stale_after_seconds=lock_stale_seconds,
        latest_cycle_finished_at=latest.finished_at if latest else None,
        latest_cycle_status=latest.cycle_status if latest else None,
    )


def _cycle_run_to_summary(row: MonitoringCycleRun) -> MonitoringCycleSummary:
    return MonitoringCycleSummary(
        run_id=row.run_id,
        started_at=row.started_at,
        finished_at=row.finished_at,
        runtime_seconds=row.runtime_seconds,
        loaded_video_count=row.loaded_video_count,
        eligible_video_count=row.eligible_video_count,
        tier_counts={
            "A": row.tier_a_count,
            "B": row.tier_b_count,
            "C": row.tier_c_count,
        },
        due_count=row.due_count,
        overdue_count=row.overdue_count,
        selected_request_count=row.selected_request_count,
        deferred_request_count=row.deferred_request_count,
        inserted_snapshot_count=row.inserted_snapshot_count,
        duplicate_snapshot_count=row.duplicate_snapshot_count,
        missing_count=row.missing_count,
        fetch_failed_count=row.fetch_failed_count,
        validation_failed_count=row.validation_failed_count,
        persistence_failed_count=row.persistence_failed_count,
        cycle_status=row.cycle_status,  # type: ignore[arg-type]
        errors=(row.error_summary,) if row.error_summary else (),
    )


def build_active_monitoring_enriched(
    session: Session,
    *,
    now: datetime | None = None,
    tier_policy: MonitoringTierPolicy | None = None,
    budget_policy: ApiBudgetPolicy | None = None,
) -> tuple[list[MonitoringEnrichedVideo], dict[str, int], int]:
    """Batch tier assignment, snapshots, and planner for active monitored videos."""
    reference = now or utc_now()
    tier_cfg = tier_policy or MonitoringTierPolicy()
    budget_cfg = budget_policy or ApiBudgetPolicy()

    states = load_monitored_video_states(session, now=reference)
    state_by_id = {row.video_id: row for row in states}
    all_decisions = assign_monitoring_tiers([_state_to_tier_input(s) for s in states], tier_cfg)
    unmonitored_count = sum(
        1 for d in all_decisions if d.tier == MonitoringTier.UNMONITORED or not d.eligible
    )

    channel_cap = apply_channel_active_cap(all_decisions, tier_cfg.max_active_videos_per_channel)
    global_cap = apply_global_monitoring_cap(channel_cap.retained, budget_cfg.max_active_monitored_videos)
    active_decisions = list(global_cap.retained)

    video_ids = [d.video_id for d in active_decisions]
    snapshots_by_video: dict[str, list] = {}  # ExistingSnapshot lists for planner
    latest_by_video: dict[str, VideoSnapshot] = {}
    for row in get_snapshots_for_videos_planner(
        session,
        video_ids,
        max_age_hours=MONITORING_PLANNER_MAX_SNAPSHOT_AGE_HOURS,
    ):
        snapshots_by_video.setdefault(row.video_id, []).append(existing_snapshot_from_orm(row))
        previous = latest_by_video.get(row.video_id)
        if previous is None or row.captured_at > previous.captured_at:
            latest_by_video[row.video_id] = row
    if video_ids:
        latest_by_video.update(get_latest_snapshots_for_videos(session, video_ids))

    video_rows: dict[str, Video] = {}
    channel_titles: dict[str, str] = {}
    if video_ids:
        stmt = (
            select(Video, Channel)
            .join(Channel, Video.channel_id == Channel.id)
            .where(Video.id.in_(video_ids))
        )
        for video, channel in session.execute(stmt).all():
            video_rows[video.id] = video
            channel_titles[video.channel_id] = channel.title

    enriched: list[MonitoringEnrichedVideo] = []
    tier_counts: dict[str, int] = {"A": 0, "B": 0, "C": 0}

    for decision in active_decisions:
        state = state_by_id[decision.video_id]
        collection_policy = snapshot_collection_policy_for_tier(decision.tier, tier_cfg)
        plan = plan_video_revisits(
            video_id=decision.video_id,
            published_at=state.published_at,
            existing_snapshots=snapshots_by_video.get(decision.video_id, []),
            current_time=reference,
            channel_id=state.channel_id,
            content_format=state.content_format,
            is_short=state.is_short,
            is_live=state.is_live,
            policy=collection_policy,
        )
        latest = latest_by_video.get(decision.video_id)
        video = video_rows.get(decision.video_id)
        views = latest.views if latest and latest.views is not None else (video.views_count if video else None)
        vph = state.raw_vph

        tier_key = decision.tier.value
        if tier_key in tier_counts:
            tier_counts[tier_key] += 1

        enriched.append(
            MonitoringEnrichedVideo(
                state=state,
                decision=decision,
                plan=plan,
                title=video.title if video else None,
                channel_title=channel_titles.get(state.channel_id),
                latest_snapshot=latest,
                current_views=views,
                current_vph=vph,
            ),
        )

    return enriched, tier_counts, unmonitored_count


def _aggregate_planner_counts(enriched: list[MonitoringEnrichedVideo]) -> tuple[int, int, int, int]:
    due = 0
    overdue = 0
    pending = 0
    stopped = 0
    for row in enriched:
        for cp in row.plan.checkpoints:
            if cp.status == "due":
                due += 1
            elif cp.status == "overdue":
                overdue += 1
            elif cp.status == "pending":
                pending += 1
        if row.plan.monitoring_status == "stopped":
            stopped += 1
    return due, overdue, pending, stopped


def get_monitoring_overview(
    session: Session,
    *,
    live_planner: bool = False,
) -> MonitoringOverviewData:
    latest_row = get_latest_monitoring_cycle_run(session)
    latest_cycle = _cycle_run_to_summary(latest_row) if latest_row else None

    if not live_planner and latest_row is not None:
        return MonitoringOverviewData(
            active_monitored_count=int(latest_row.eligible_video_count),
            tier_counts={
                "A": int(latest_row.tier_a_count),
                "B": int(latest_row.tier_b_count),
                "C": int(latest_row.tier_c_count),
            },
            unmonitored_count=max(0, int(latest_row.loaded_video_count) - int(latest_row.eligible_video_count)),
            due_count=int(latest_row.due_count),
            overdue_count=int(latest_row.overdue_count),
            pending_count=0,
            stopped_count=0,
            latest_cycle=latest_cycle,
        )

    enriched, tier_counts, unmonitored_count = build_active_monitoring_enriched(session)
    due, overdue, pending, stopped = _aggregate_planner_counts(enriched)
    return MonitoringOverviewData(
        active_monitored_count=len(enriched),
        tier_counts=tier_counts,
        unmonitored_count=unmonitored_count,
        due_count=due,
        overdue_count=overdue,
        pending_count=pending,
        stopped_count=stopped,
        latest_cycle=latest_cycle,
    )


def _priority_sort_key(row: MonitoringEnrichedVideo) -> tuple:
    overdue_hours = [
        cp.target_age_hours
        for cp in row.plan.due_checkpoints
        if cp.status == "overdue"
    ]
    due_hours = [
        cp.target_age_hours for cp in row.plan.due_checkpoints if cp.status == "due"
    ]
    has_overdue = 0 if overdue_hours else 1
    has_due = 0 if due_hours else 1
    tier_rank = {"A": 0, "B": 1, "C": 2}.get(row.decision.tier.value, 9)
    vph = row.current_vph if row.current_vph is not None else -1.0
    return (has_overdue, has_due, tier_rank, -vph, row.state.video_id)


def _sort_rows(rows: list[MonitoringEnrichedVideo], sort: MonitoringSort) -> list[MonitoringEnrichedVideo]:
    if sort == "priority":
        return sorted(rows, key=_priority_sort_key)
    if sort == "vph_desc":
        return sorted(
            rows,
            key=lambda r: (-(r.current_vph or -1.0), r.state.video_id),
        )
    if sort == "views_desc":
        return sorted(
            rows,
            key=lambda r: (-(r.current_views or -1), r.state.video_id),
        )
    if sort == "age_asc":
        return sorted(
            rows,
            key=lambda r: (r.state.age_hours if r.state.age_hours is not None else 999999.0, r.state.video_id),
        )
    if sort == "latest_snapshot_desc":
        return sorted(
            rows,
            key=lambda r: (
                -(r.latest_snapshot.captured_at.timestamp() if r.latest_snapshot else 0.0),
                r.state.video_id,
            ),
        )
    return sorted(rows, key=_priority_sort_key)


def _matches_status(row: MonitoringEnrichedVideo, status: MonitoringListStatus) -> bool:
    if status == "overdue":
        return any(cp.status == "overdue" for cp in row.plan.due_checkpoints)
    if status == "due":
        return any(cp.status == "due" for cp in row.plan.due_checkpoints)
    if status == "pending":
        return (
            row.plan.monitoring_status == "active"
            and not row.plan.due_checkpoints
            and any(cp.status == "pending" for cp in row.plan.checkpoints)
        )
    if status == "active":
        return row.plan.monitoring_status == "active"
    if status == "stopped":
        return row.plan.monitoring_status == "stopped"
    return True


def _load_video_channel_titles(
    session: Session,
    video_ids: list[str],
) -> tuple[dict[str, Video], dict[str, str]]:
    video_rows: dict[str, Video] = {}
    channel_titles: dict[str, str] = {}
    if not video_ids:
        return video_rows, channel_titles
    stmt = (
        select(Video, Channel)
        .join(Channel, Video.channel_id == Channel.id)
        .where(Video.id.in_(video_ids))
    )
    for video, channel in session.execute(stmt).all():
        video_rows[video.id] = video
        channel_titles[video.channel_id] = channel.title
    return video_rows, channel_titles


def _active_capture_video_ids(
    all_decisions: list[MonitoringDecision],
    *,
    tier_policy: MonitoringTierPolicy,
    budget_policy: ApiBudgetPolicy,
) -> set[str]:
    channel_cap = apply_channel_active_cap(all_decisions, tier_policy.max_active_videos_per_channel)
    global_cap = apply_global_monitoring_cap(
        channel_cap.retained,
        budget_policy.max_active_monitored_videos,
    )
    return {decision.video_id for decision in global_cap.retained}


def list_monitoring_videos_breakout(
    session: Session,
    *,
    tier: str | None = None,
    channel_id: str | None = None,
    keyword: str | None = None,
    limit: int = 50,
    offset: int = 0,
    now: datetime | None = None,
    tier_policy: MonitoringTierPolicy | None = None,
    budget_policy: ApiBudgetPolicy | None = None,
) -> tuple[list[BreakoutVideoListRow], int]:
    """Breakout-eligible population (before caps). Ignores ops status filters."""
    reference = now or utc_now()
    tier_cfg = tier_policy or MonitoringTierPolicy()
    budget_cfg = budget_policy or ApiBudgetPolicy()

    states = load_monitored_video_states(session, now=reference)
    state_by_id = {row.video_id: row for row in states}
    all_decisions = assign_monitoring_tiers([_state_to_tier_input(s) for s in states], tier_cfg)
    decision_by_id = {row.video_id: row for row in all_decisions}
    active_ids = _active_capture_video_ids(all_decisions, tier_policy=tier_cfg, budget_policy=budget_cfg)

    eligible_ids = [
        s.video_id
        for s in states
        if breakout_fundamental_eligibility(s, max_age_monitoring_hours=tier_cfg.max_age_monitoring_hours)[0]
    ]
    latest_by_video = get_latest_snapshots_for_videos(session, eligible_ids) if eligible_ids else {}
    video_rows, channel_titles = _load_video_channel_titles(session, eligible_ids)

    views_by_id: dict[str, int | None] = {}
    for video_id in eligible_ids:
        latest = latest_by_video.get(video_id)
        video = video_rows.get(video_id)
        views_by_id[video_id] = (
            latest.views if latest and latest.views is not None else (video.views_count if video else None)
        )

    ranked = rank_breakout_v1(states, views_by_video_id=views_by_id, tier_policy=tier_cfg)

    rows: list[BreakoutVideoListRow] = []
    for item in ranked:
        state = state_by_id[item.video_id]
        decision = decision_by_id[item.video_id]
        latest = latest_by_video.get(item.video_id)
        video = video_rows.get(item.video_id)
        views = views_by_id.get(item.video_id)
        rows.append(
            BreakoutVideoListRow(
                state=state,
                decision=decision,
                title=video.title if video else None,
                channel_title=channel_titles.get(state.channel_id),
                latest_snapshot=latest,
                current_views=views,
                current_vph=state.raw_vph,
                breakout_rank=item.rank,
                breakout_ranking_value=item.ranking_value,
                in_active_capture_pool=item.video_id in active_ids,
            ),
        )

    filtered = rows
    if tier is not None:
        tier_upper = tier.upper()
        filtered = [r for r in filtered if r.decision.tier.value == tier_upper]
    if channel_id is not None:
        filtered = [r for r in filtered if r.state.channel_id == channel_id]
    if keyword:
        needle = keyword.strip().lower()
        if needle:
            filtered = [
                r
                for r in filtered
                if (r.title and needle in r.title.lower())
                or (r.state.video_id.lower().find(needle) >= 0)
            ]

    total = len(filtered)
    page = filtered[max(0, offset) : max(0, offset) + max(1, min(limit, 200))]
    return page, total


@dataclass(frozen=True, slots=True)
class MonitoringVideosListResult:
    rows: list[MonitoringEnrichedVideo] | list[BreakoutVideoListRow] | list
    total: int
    queue_run_id: str | None = None
    queue_generated_at: datetime | None = None
    queue_source: str = "cycle_snapshot"


def list_monitoring_videos(
    session: Session,
    *,
    tier: str | None = None,
    status: MonitoringListStatus | None = None,
    channel_id: str | None = None,
    keyword: str | None = None,
    sort: MonitoringSort = "priority",
    limit: int = 50,
    offset: int = 0,
    live_planner: bool = False,
) -> MonitoringVideosListResult:
    if sort == "breakout_v1":
        page, total = list_monitoring_videos_breakout(
            session,
            tier=tier,
            channel_id=channel_id,
            keyword=keyword,
            limit=limit,
            offset=offset,
        )
        return MonitoringVideosListResult(rows=page, total=total, queue_source="live_planner")

    if live_planner:
        enriched, _, _ = build_active_monitoring_enriched(session)
        filtered = enriched
        if tier is not None:
            tier_upper = tier.upper()
            filtered = [r for r in filtered if r.decision.tier.value == tier_upper]
        if channel_id is not None:
            filtered = [r for r in filtered if r.state.channel_id == channel_id]
        if keyword:
            needle = keyword.strip().lower()
            if needle:
                filtered = [
                    r
                    for r in filtered
                    if (r.title and needle in r.title.lower())
                    or (r.state.video_id.lower().find(needle) >= 0)
                ]
        if status is not None:
            filtered = [r for r in filtered if _matches_status(r, status)]
        ordered = _sort_rows(filtered, sort)
        total = len(ordered)
        page = ordered[max(0, offset) : max(0, offset) + max(1, min(limit, 200))]
        return MonitoringVideosListResult(rows=page, total=total, queue_source="live_planner")

    from app.services.monitoring_video_queue import (
        list_queue_videos_page,
        queue_list_meta,
        resolve_queue_list_context,
    )

    run_id, generated_at, ready = resolve_queue_list_context(session)
    if not ready or run_id is None:
        meta = queue_list_meta(run_id=None, generated_at=generated_at, source="unavailable")
        return MonitoringVideosListResult(
            rows=[],
            total=0,
            queue_run_id=meta.queue_run_id,
            queue_generated_at=meta.queue_generated_at,
            queue_source=meta.queue_source,
        )

    page_rows, total = list_queue_videos_page(
        session,
        run_id,
        tier=tier,
        status=status,
        channel_id=channel_id,
        keyword=keyword,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    meta = queue_list_meta(run_id=run_id, generated_at=generated_at, source="cycle_snapshot")
    return MonitoringVideosListResult(
        rows=page_rows,
        total=total,
        queue_run_id=meta.queue_run_id,
        queue_generated_at=meta.queue_generated_at,
        queue_source=meta.queue_source,
    )


def get_monitoring_video_detail(
    session: Session,
    video_id: str,
    *,
    include_baseline: bool = True,
) -> MonitoringEnrichedVideo | None:
    enriched, _, _ = build_active_monitoring_enriched(session)
    match = next((row for row in enriched if row.state.video_id == video_id), None)
    if match is not None:
        return match

    video = session.get(Video, video_id)
    if video is None:
        return None

    reference = utc_now()
    states = load_monitored_video_states(session, now=reference, max_videos=None)
    state = next((s for s in states if s.video_id == video_id), None)
    if state is None:
        return None

    decisions = assign_monitoring_tiers([_state_to_tier_input(state)])
    decision = decisions[0]
    snapshots = load_snapshots_by_video_id(session, [video_id]).get(video_id, [])
    latest = get_latest_snapshots_for_videos(session, [video_id]).get(video_id)
    channel = session.get(Channel, video.channel_id)
    policy = snapshot_collection_policy_for_tier(decision.tier, MonitoringTierPolicy())
    plan = plan_video_revisits(
        video_id=video_id,
        published_at=state.published_at,
        existing_snapshots=snapshots,
        current_time=reference,
        channel_id=state.channel_id,
        content_format=state.content_format,
        is_short=state.is_short,
        is_live=state.is_live,
        policy=policy,
    )
    views = latest.views if latest and latest.views is not None else video.views_count
    vph = latest.vph if latest and latest.vph is not None else state.raw_vph
    return MonitoringEnrichedVideo(
        state=state,
        decision=decision,
        plan=plan,
        title=video.title,
        channel_title=channel.title if channel else None,
        latest_snapshot=latest,
        current_views=views,
        current_vph=vph,
    )


def get_video_baseline_for_detail(
    session: Session,
    row: MonitoringEnrichedVideo,
):
    if not row.state.channel_id:
        return None
    return compute_channel_velocity_baseline(
        session,
        channel_id=row.state.channel_id,
        candidate_video_id=row.state.video_id,
        candidate_age_hours=row.state.age_hours,
        candidate_vph=row.current_vph,
        candidate_published_at=row.state.published_at,
        candidate_captured_at=row.latest_snapshot.captured_at if row.latest_snapshot else None,
    )


def list_video_monitoring_snapshots(
    session: Session,
    video_id: str,
    *,
    limit: int | None = None,
    captured_from: datetime | None = None,
    captured_to: datetime | None = None,
) -> list[VideoSnapshot]:
    rows = get_snapshots_for_video(session, video_id)
    if captured_from is not None:
        captured_from = ensure_utc(captured_from)
        rows = [r for r in rows if ensure_utc(r.captured_at) >= captured_from]
    if captured_to is not None:
        captured_to = ensure_utc(captured_to)
        rows = [r for r in rows if ensure_utc(r.captured_at) <= captured_to]
    if limit is not None:
        rows = rows[-max(1, min(limit, 500)) :]
    return rows


def get_monitoring_cycle_history(
    session: Session,
    *,
    limit: int = 20,
    cycle_status: str | None = None,
) -> list[MonitoringCycleRun]:
    return list_monitoring_cycle_runs(session, limit=limit, cycle_status=cycle_status)
