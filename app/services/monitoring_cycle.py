"""One-shot monitoring cycle orchestration (Stage 1.13C)."""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol, Sequence

from sqlalchemy.orm import Session

from app.services.metrics import utc_now
from app.services.monitoring_tier_budget_policy import (
    ApiBudgetPolicy,
    CaptureRequestBudgetContext,
    MonitoringTier,
    MonitoringTierPolicy,
    TierCandidateInput,
    allocate_capture_budget,
    apply_channel_active_cap,
    apply_global_monitoring_cap,
    assign_monitoring_tiers,
    snapshot_collection_policy_for_tier,
)
from app.services.monitoring_video_source import (
    MonitoredVideoState,
    load_monitored_video_states,
)
from app.services.revisit_executor import (
    RevisitExecutionOutcome,
    VideoBatchFetchClient,
    execute_snapshot_capture_requests,
)
from app.services.snapshot_collection_policy import (
    SnapshotCaptureRequest,
    VideoRevisitPlan,
    build_capture_requests,
    load_snapshots_by_video_id,
    plan_video_revisits,
)

logger = logging.getLogger(__name__)

MONITORING_CAPTURE_SOURCE = "monitoring_worker"
DEFAULT_MONITORING_WORKER_INTERVAL_SECONDS = 900
DEFAULT_MONITORING_ERROR_BACKOFF_SECONDS = 300

CycleStatus = Literal["ok", "partial", "failed", "dry_run"]


def generate_monitoring_run_id(*, now: datetime | None = None) -> str:
    reference = now or utc_now()
    stamp = reference.strftime("%Y%m%dT%H%M%SZ")
    return f"monitoring_{stamp}_{secrets.token_hex(4)}"


@dataclass
class MonitoringCycleSummary:
    run_id: str
    started_at: datetime
    finished_at: datetime | None = None
    runtime_seconds: float = 0.0
    loaded_video_count: int = 0
    eligible_video_count: int = 0
    tier_counts: dict[str, int] = field(default_factory=dict)
    channel_cap_excluded_count: int = 0
    global_cap_excluded_count: int = 0
    due_count: int = 0
    overdue_count: int = 0
    capture_request_count: int = 0
    selected_request_count: int = 0
    deferred_request_count: int = 0
    inserted_snapshot_count: int = 0
    duplicate_snapshot_count: int = 0
    missing_count: int = 0
    fetch_failed_count: int = 0
    validation_failed_count: int = 0
    persistence_failed_count: int = 0
    cycle_status: CycleStatus = "ok"
    errors: tuple[str, ...] = ()


class MonitoringCycleClient(Protocol):
    def get_videos(self, video_ids: list[str]): ...


def _state_to_tier_input(state: MonitoredVideoState) -> TierCandidateInput:
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


def _count_cap_exclusions(excluded: Sequence, reason: str) -> int:
    return sum(1 for row in excluded if row.excluded_reason == reason)


def _tier_counts(decisions: Sequence) -> dict[str, int]:
    counts: dict[str, int] = {}
    for decision in decisions:
        key = decision.tier.value if hasattr(decision.tier, "value") else str(decision.tier)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _budget_context(
    request: SnapshotCaptureRequest,
    *,
    decision,
    plan: VideoRevisitPlan,
) -> CaptureRequestBudgetContext:
    checkpoint = next(
        (
            cp
            for cp in plan.due_checkpoints
            if cp.target_age_hours == request.checkpoint_age_hours
        ),
        None,
    )
    expiry: float | None = None
    if checkpoint is not None and plan.current_age_hours is not None:
        expiry = round(checkpoint.expires_at_age_hours - plan.current_age_hours, 4)
    return CaptureRequestBudgetContext(
        request=request,
        tier=decision.tier,
        raw_vph=decision.raw_vph,
        is_overdue=request.reason == "overdue",
        time_to_checkpoint_expiry_hours=expiry,
    )


def _plan_and_requests_for_decision(
    decision,
    *,
    state_by_id: dict[str, MonitoredVideoState],
    snapshots_by_video_id: dict,
    current_time: datetime,
    tier_policy: MonitoringTierPolicy,
    run_id: str,
) -> tuple[VideoRevisitPlan, list[SnapshotCaptureRequest]]:
    state = state_by_id[decision.video_id]
    collection_policy = snapshot_collection_policy_for_tier(decision.tier, tier_policy)
    plan = plan_video_revisits(
        video_id=decision.video_id,
        published_at=state.published_at,
        existing_snapshots=snapshots_by_video_id.get(decision.video_id, []),
        current_time=current_time,
        channel_id=state.channel_id,
        content_format=state.content_format,
        is_short=state.is_short,
        is_live=state.is_live,
        policy=collection_policy,
    )
    requests = build_capture_requests(
        plan,
        requested_at=current_time,
        source=MONITORING_CAPTURE_SOURCE,
        run_id_prefix=f"{run_id}:",
    )
    return plan, requests


def _resolve_cycle_status(
    *,
    dry_run: bool,
    execution: RevisitExecutionOutcome | None,
    orchestration_errors: Sequence[str],
) -> CycleStatus:
    if dry_run:
        return "dry_run"
    if orchestration_errors:
        return "failed"
    if execution is None:
        return "ok"
    summary = execution.summary
    if summary.total_failed_count > 0 or summary.failed_batch_count > 0:
        return "partial"
    return "ok"


def log_monitoring_cycle_summary(summary: MonitoringCycleSummary) -> None:
    tier_a = summary.tier_counts.get("A", 0)
    tier_b = summary.tier_counts.get("B", 0)
    tier_c = summary.tier_counts.get("C", 0)
    message = (
        "[MONITORING_CYCLE] "
        f"run_id={summary.run_id} "
        f"loaded={summary.loaded_video_count} "
        f"tier_A={tier_a} tier_B={tier_b} tier_C={tier_c} "
        f"due={summary.due_count} overdue={summary.overdue_count} "
        f"selected={summary.selected_request_count} "
        f"deferred={summary.deferred_request_count} "
        f"inserted={summary.inserted_snapshot_count} "
        f"missing={summary.missing_count} "
        f"fetch_failed={summary.fetch_failed_count} "
        f"duration={summary.runtime_seconds} "
        f"status={summary.cycle_status}"
    )
    logger.info(message)


def run_monitoring_cycle(
    session: Session,
    *,
    youtube_client: VideoBatchFetchClient | None = None,
    dry_run: bool = False,
    run_id: str | None = None,
    current_time: datetime | None = None,
    tier_policy: MonitoringTierPolicy | None = None,
    budget_policy: ApiBudgetPolicy | None = None,
    max_videos: int | None = None,
) -> MonitoringCycleSummary:
    """
    Load monitorable videos, assign tiers, plan revisits, allocate budget, optionally execute.

    State is derived from DB snapshots and current time (restart-safe).
    """
    started_perf = time.perf_counter()
    now = current_time or utc_now()
    cycle_run_id = run_id or generate_monitoring_run_id(now=now)
    tier_cfg = tier_policy or MonitoringTierPolicy()
    budget_cfg = budget_policy or ApiBudgetPolicy()

    summary = MonitoringCycleSummary(run_id=cycle_run_id, started_at=now)

    states = load_monitored_video_states(session, now=now, max_videos=max_videos)
    summary.loaded_video_count = len(states)
    state_by_id = {row.video_id: row for row in states}

    tier_inputs = [_state_to_tier_input(row) for row in states]
    all_decisions = assign_monitoring_tiers(tier_inputs, tier_cfg)

    channel_cap = apply_channel_active_cap(
        all_decisions,
        tier_cfg.max_active_videos_per_channel,
    )
    summary.channel_cap_excluded_count = _count_cap_exclusions(
        channel_cap.excluded,
        "channel_active_cap",
    )

    global_cap = apply_global_monitoring_cap(
        channel_cap.retained,
        budget_cfg.max_active_monitored_videos,
    )
    summary.global_cap_excluded_count = _count_cap_exclusions(
        global_cap.excluded,
        "global_monitoring_cap",
    )

    active_decisions = list(global_cap.retained)
    summary.eligible_video_count = len(active_decisions)
    summary.tier_counts = _tier_counts(active_decisions)

    video_ids = [d.video_id for d in active_decisions]
    snapshots_by_video_id = load_snapshots_by_video_id(session, video_ids)

    all_requests: list[SnapshotCaptureRequest] = []
    contexts: list[CaptureRequestBudgetContext] = []
    due_total = 0
    overdue_total = 0

    for decision in active_decisions:
        plan, requests = _plan_and_requests_for_decision(
            decision,
            state_by_id=state_by_id,
            snapshots_by_video_id=snapshots_by_video_id,
            current_time=now,
            tier_policy=tier_cfg,
            run_id=cycle_run_id,
        )
        for checkpoint in plan.due_checkpoints:
            if checkpoint.status == "due":
                due_total += 1
            elif checkpoint.status == "overdue":
                overdue_total += 1
        for request in requests:
            contexts.append(
                _budget_context(request, decision=decision, plan=plan),
            )
        all_requests.extend(requests)

    summary.due_count = due_total
    summary.overdue_count = overdue_total
    summary.capture_request_count = len(all_requests)

    budget = allocate_capture_budget(contexts, budget_cfg)
    summary.selected_request_count = budget.selected_for_capture_count
    summary.deferred_request_count = budget.deferred_count

    execution: RevisitExecutionOutcome | None = None
    if not dry_run and budget.selected_requests and youtube_client is not None:
        execution = execute_snapshot_capture_requests(
            budget.selected_requests,
            youtube_client,
            session,
        )
        session.commit()
        exec_summary = execution.summary
        summary.inserted_snapshot_count = exec_summary.inserted_snapshot_count
        summary.duplicate_snapshot_count = exec_summary.duplicate_snapshot_count
        summary.missing_count = exec_summary.missing_video_count
        summary.fetch_failed_count = exec_summary.fetch_failed_count
        summary.validation_failed_count = exec_summary.validation_failed_count
        summary.persistence_failed_count = exec_summary.persistence_failed_count
    elif dry_run:
        session.rollback()

    summary.cycle_status = _resolve_cycle_status(
        dry_run=dry_run,
        execution=execution,
        orchestration_errors=(),
    )
    summary.finished_at = utc_now()
    summary.runtime_seconds = round(time.perf_counter() - started_perf, 3)

    log_monitoring_cycle_summary(summary)

    if not dry_run:
        from app.services.monitoring_cycle_run_storage import persist_monitoring_cycle_run

        persist_monitoring_cycle_run(session, summary)
        session.flush()

    return summary
