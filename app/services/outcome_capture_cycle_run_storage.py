"""Persist delayed outcome capture cycle summaries (Stage 1.20E.2)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import OutcomeCaptureCycleRun
from app.services.delayed_outcome_capture_cycle import DelayedOutcomeCaptureCycleSummary


def persist_outcome_capture_cycle_run(
    session: Session,
    summary: DelayedOutcomeCaptureCycleSummary,
) -> OutcomeCaptureCycleRun:
    row = OutcomeCaptureCycleRun(
        run_id=summary.run_id,
        started_at=summary.started_at,
        finished_at=summary.finished_at,
        runtime_seconds=summary.runtime_seconds,
        cycle_status=summary.cycle_status,
        attribution_mode=summary.attribution_mode,
        attributed_observation_count=summary.attributed_observation_count,
        pending_count=summary.pending_count,
        satisfied_existing_count=summary.satisfied_existing_count,
        capture_due_count=summary.capture_due_count,
        capture_overdue_count=summary.capture_overdue_count,
        expired_count=summary.expired_count,
        unique_due_video_count=summary.unique_due_video_count,
        selected_video_count=summary.selected_video_count,
        deferred_video_count=summary.deferred_video_count,
        inserted_snapshot_count=summary.inserted_snapshot_count,
        duplicate_snapshot_count=summary.duplicate_snapshot_count,
        missing_video_count=summary.missing_video_count,
        fetch_failed_count=summary.fetch_failed_count,
        error_summary="; ".join(summary.errors) if summary.errors else None,
    )
    session.add(row)
    session.flush()
    return row


def get_latest_outcome_capture_cycle_run(session: Session) -> OutcomeCaptureCycleRun | None:
    stmt = (
        select(OutcomeCaptureCycleRun)
        .order_by(OutcomeCaptureCycleRun.started_at.desc(), OutcomeCaptureCycleRun.id.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def list_outcome_capture_cycle_runs(
    session: Session,
    *,
    limit: int = 20,
) -> list[OutcomeCaptureCycleRun]:
    stmt = select(OutcomeCaptureCycleRun).order_by(
        OutcomeCaptureCycleRun.started_at.desc(),
        OutcomeCaptureCycleRun.id.desc(),
    ).limit(max(1, min(limit, 100)))
    return list(session.scalars(stmt).all())
