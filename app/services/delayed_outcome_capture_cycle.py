"""Execute one delayed outcome capture cycle (Stage 1.20E.2)."""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from sqlalchemy.orm import Session

from app.services.delayed_outcome_capture_config import (
    OUTCOME_CAPTURE_SOURCE,
    OUTCOME_CHECKPOINT_AGE_HOURS,
    OutcomeCaptureBudgetPolicy,
)
from app.services.delayed_outcome_capture_planner import (
    load_published_at_by_video,
    plan_delayed_outcome_capture,
)
from app.services.delayed_outcome_capture_types import OutcomeAttributionMode
from app.services.metrics import ensure_utc, utc_now
from app.services.revisit_executor import (
    RevisitExecutorConfig,
    VideoBatchFetchClient,
    execute_snapshot_capture_requests,
)
from app.services.snapshot_collection_policy import SnapshotCaptureRequest

logger = logging.getLogger(__name__)

CycleStatus = Literal["ok", "partial", "failed", "dry_run"]


def generate_outcome_capture_run_id(*, now: datetime | None = None) -> str:
    reference = now or utc_now()
    stamp = reference.strftime("%Y%m%dT%H%M%SZ")
    return f"outcome_{stamp}_{secrets.token_hex(4)}"


@dataclass
class DelayedOutcomeCaptureCycleSummary:
    run_id: str
    started_at: datetime
    finished_at: datetime | None = None
    runtime_seconds: float = 0.0
    attribution_mode: OutcomeAttributionMode = "all_hits"
    attributed_observation_count: int = 0
    pending_count: int = 0
    satisfied_existing_count: int = 0
    capture_due_count: int = 0
    capture_overdue_count: int = 0
    expired_count: int = 0
    unique_due_video_count: int = 0
    selected_video_count: int = 0
    deferred_video_count: int = 0
    inserted_snapshot_count: int = 0
    duplicate_snapshot_count: int = 0
    missing_video_count: int = 0
    fetch_failed_count: int = 0
    cycle_status: CycleStatus = "ok"
    errors: tuple[str, ...] = ()


def _resolve_status(*, dry_run: bool, fetch_failed: int, inserted: int, selected: int) -> CycleStatus:
    if dry_run:
        return "dry_run"
    if selected == 0:
        return "ok"
    if fetch_failed >= selected and inserted == 0:
        return "failed"
    if fetch_failed > 0:
        return "partial"
    return "ok"


def run_delayed_outcome_capture_cycle(
    session: Session,
    *,
    youtube_client: VideoBatchFetchClient | None = None,
    dry_run: bool = False,
    run_id: str | None = None,
    current_time: datetime | None = None,
    attribution_mode: OutcomeAttributionMode = "all_hits",
    budget: OutcomeCaptureBudgetPolicy | None = None,
) -> DelayedOutcomeCaptureCycleSummary:
    started_perf = time.perf_counter()
    now = current_time or utc_now()
    cycle_run_id = run_id or generate_outcome_capture_run_id(now=now)
    budget_cfg = budget or OutcomeCaptureBudgetPolicy()

    plan = plan_delayed_outcome_capture(
        session,
        reference=now,
        attribution_mode=attribution_mode,
    )

    summary = DelayedOutcomeCaptureCycleSummary(
        run_id=cycle_run_id,
        started_at=now,
        attribution_mode=attribution_mode,
        attributed_observation_count=plan.attributed_observation_count,
        pending_count=plan.pending_count,
        satisfied_existing_count=plan.satisfied_count,
        capture_due_count=plan.capture_due_count,
        capture_overdue_count=plan.capture_overdue_count,
        expired_count=plan.expired_count,
        unique_due_video_count=plan.unique_due_video_count,
    )

    selected = plan.fetch_candidates[: budget_cfg.max_videos_per_cycle]
    deferred = plan.fetch_candidates[budget_cfg.max_videos_per_cycle :]
    summary.selected_video_count = len(selected)
    summary.deferred_video_count = len(deferred)

    if dry_run or youtube_client is None:
        summary.cycle_status = "dry_run" if dry_run else summary.cycle_status
        summary.finished_at = utc_now()
        summary.runtime_seconds = round(time.perf_counter() - started_perf, 3)
        if dry_run:
            session.rollback()
        return summary

    if not selected:
        summary.cycle_status = "ok"
        summary.finished_at = utc_now()
        summary.runtime_seconds = round(time.perf_counter() - started_perf, 3)
        from app.services.outcome_capture_cycle_run_storage import persist_outcome_capture_cycle_run

        persist_outcome_capture_cycle_run(session, summary)
        session.flush()
        return summary

    video_ids = [row.video_id for row in selected]
    published_by_id = load_published_at_by_video(session, video_ids)

    requests: list[SnapshotCaptureRequest] = []
    for candidate in selected:
        published = published_by_id.get(candidate.video_id)
        if published is not None:
            age_h = max(
                0.0,
                (ensure_utc(now) - ensure_utc(published)).total_seconds() / 3600.0,
            )
        else:
            age_h = 0.0
        due_rows = [
            row
            for row in plan.observations
            if row.video_id == candidate.video_id and row.state in ("capture_due", "capture_overdue")
        ]
        target_at = min(row.target_at for row in due_rows) if due_rows else now
        reason = "overdue" if any(r.state == "capture_overdue" for r in due_rows) else "due"
        requests.append(
            SnapshotCaptureRequest(
                video_id=candidate.video_id,
                channel_id=candidate.channel_id,
                checkpoint_age_hours=OUTCOME_CHECKPOINT_AGE_HOURS,
                reason=reason,
                requested_at=now,
                current_age_hours=round(age_h, 4),
                source=OUTCOME_CAPTURE_SOURCE,
                run_id=f"{cycle_run_id}:{candidate.video_id}",
                outcome_target_at=target_at,
            ),
        )

    execution = execute_snapshot_capture_requests(
        requests,
        youtube_client,
        session,
        config=RevisitExecutorConfig(batch_size=budget_cfg.batch_size),
    )
    exec_summary = execution.summary
    summary.inserted_snapshot_count = exec_summary.inserted_snapshot_count
    summary.duplicate_snapshot_count = exec_summary.duplicate_snapshot_count
    summary.missing_video_count = exec_summary.missing_video_count
    summary.fetch_failed_count = exec_summary.fetch_failed_count
    summary.cycle_status = _resolve_status(
        dry_run=False,
        fetch_failed=exec_summary.fetch_failed_count,
        inserted=exec_summary.inserted_snapshot_count,
        selected=len(selected),
    )
    summary.finished_at = utc_now()
    summary.runtime_seconds = round(time.perf_counter() - started_perf, 3)

    from app.services.outcome_capture_cycle_run_storage import persist_outcome_capture_cycle_run

    persist_outcome_capture_cycle_run(session, summary)
    session.commit()

    logger.info(
        "Outcome capture cycle run_id=%s due_videos=%s selected=%s deferred=%s inserted=%s status=%s",
        summary.run_id,
        summary.unique_due_video_count,
        summary.selected_video_count,
        summary.deferred_video_count,
        summary.inserted_snapshot_count,
        summary.cycle_status,
    )
    return summary
