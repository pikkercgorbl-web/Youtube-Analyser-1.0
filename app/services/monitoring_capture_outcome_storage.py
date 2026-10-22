"""Persist per-request monitoring capture diagnostics (non-insert outcomes only)."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.models.orm import MonitoringCaptureOutcome
from app.services.revisit_executor import SnapshotCaptureExecutionResult

logger = logging.getLogger(__name__)

_DIAGNOSTIC_OUTCOMES = frozenset(
    {"missing", "fetch_failed", "validation_failed", "persistence_failed"},
)


def capture_outcome_reason_code(*, outcome: str, error: str | None) -> str:
    if outcome == "missing":
        return "yt_items_absent"
    if outcome == "fetch_failed":
        return "batch_fetch_failed"
    if outcome == "persistence_failed":
        return "persist_failed"
    if outcome == "validation_failed":
        message = (error or "").strip().lower()
        if "channel_id" in message:
            return "channel_id_missing"
        return "validation_rejected"
    return "unknown"


def persist_monitoring_capture_outcomes(
    session: Session,
    *,
    monitoring_run_id: str,
    results: Sequence[SnapshotCaptureExecutionResult],
) -> int:
    """Append diagnostic rows; returns count inserted. Caller commits separately."""
    rows: list[MonitoringCaptureOutcome] = []
    for result in results:
        if result.status not in _DIAGNOSTIC_OUTCOMES:
            continue
        rows.append(
            MonitoringCaptureOutcome(
                monitoring_run_id=monitoring_run_id,
                video_id=result.video_id,
                checkpoint_age_hours=result.checkpoint_age_hours,
                capture_run_id=result.run_id,
                attempted_at=result.requested_at,
                outcome=result.status,
                reason_code=capture_outcome_reason_code(
                    outcome=result.status,
                    error=result.error,
                ),
            ),
        )
    if not rows:
        return 0
    session.add_all(rows)
    session.flush()
    return len(rows)


def persist_monitoring_capture_outcomes_safe(
    session: Session,
    *,
    monitoring_run_id: str,
    results: Sequence[SnapshotCaptureExecutionResult],
) -> None:
    """Best-effort persist after main cycle commit; never raises to caller."""
    try:
        count = persist_monitoring_capture_outcomes(
            session,
            monitoring_run_id=monitoring_run_id,
            results=results,
        )
        session.commit()
        if count:
            logger.info(
                "[MONITORING_CAPTURE_OUTCOMES] run_id=%s rows=%s",
                monitoring_run_id,
                count,
            )
    except Exception:
        session.rollback()
        logger.exception(
            "Failed to persist monitoring capture outcomes for run_id=%s",
            monitoring_run_id,
        )
