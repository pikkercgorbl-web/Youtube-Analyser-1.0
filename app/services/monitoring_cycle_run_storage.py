"""Persist monitoring cycle summaries for API/history (Stage 1.14A)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import MonitoringCycleRun
from app.services.monitoring_cycle import MonitoringCycleSummary


def persist_monitoring_cycle_run(
    session: Session,
    summary: MonitoringCycleSummary,
) -> MonitoringCycleRun:
    tier = summary.tier_counts or {}
    row = MonitoringCycleRun(
        run_id=summary.run_id,
        started_at=summary.started_at,
        finished_at=summary.finished_at,
        runtime_seconds=summary.runtime_seconds,
        cycle_status=summary.cycle_status,
        loaded_video_count=summary.loaded_video_count,
        eligible_video_count=summary.eligible_video_count,
        tier_a_count=int(tier.get("A", 0)),
        tier_b_count=int(tier.get("B", 0)),
        tier_c_count=int(tier.get("C", 0)),
        due_count=summary.due_count,
        overdue_count=summary.overdue_count,
        selected_request_count=summary.selected_request_count,
        deferred_request_count=summary.deferred_request_count,
        inserted_snapshot_count=summary.inserted_snapshot_count,
        duplicate_snapshot_count=summary.duplicate_snapshot_count,
        missing_count=summary.missing_count,
        fetch_failed_count=summary.fetch_failed_count,
        validation_failed_count=summary.validation_failed_count,
        persistence_failed_count=summary.persistence_failed_count,
        error_summary="; ".join(summary.errors) if summary.errors else None,
    )
    session.add(row)
    session.flush()
    return row


def get_latest_monitoring_cycle_run(session: Session) -> MonitoringCycleRun | None:
    stmt = (
        select(MonitoringCycleRun)
        .order_by(MonitoringCycleRun.started_at.desc(), MonitoringCycleRun.id.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def list_monitoring_cycle_runs(
    session: Session,
    *,
    limit: int = 20,
    cycle_status: str | None = None,
) -> list[MonitoringCycleRun]:
    stmt = select(MonitoringCycleRun).order_by(
        MonitoringCycleRun.started_at.desc(),
        MonitoringCycleRun.id.desc(),
    )
    if cycle_status is not None:
        stmt = stmt.where(MonitoringCycleRun.cycle_status == cycle_status)
    stmt = stmt.limit(max(1, min(limit, 100)))
    return list(session.scalars(stmt).all())
