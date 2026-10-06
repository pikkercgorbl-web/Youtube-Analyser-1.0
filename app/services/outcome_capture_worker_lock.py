"""Process singleton lock for delayed outcome capture worker (Stage 1.20E.2)."""

from __future__ import annotations

import socket
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.orm import OutcomeCaptureWorkerState
from app.services.metrics import ensure_utc, utc_now

OUTCOME_CAPTURE_WORKER_STATE_ROW_ID = 1
OUTCOME_STATUS_IDLE = "idle"
OUTCOME_STATUS_RUNNING = "running"
OUTCOME_STATUS_STOPPED = "stopped"
DEFAULT_STALE_LOCK_MINUTES = 90


@dataclass(frozen=True, slots=True)
class OutcomeCaptureLockResult:
    acquired: bool
    reason: str
    holder: str | None = None


def default_lock_holder() -> str:
    return f"{socket.gethostname()}:{OUTCOME_CAPTURE_WORKER_STATE_ROW_ID}"


def _get_or_create_state(session: Session) -> OutcomeCaptureWorkerState:
    state = session.get(OutcomeCaptureWorkerState, OUTCOME_CAPTURE_WORKER_STATE_ROW_ID)
    if state is not None:
        return state
    state = OutcomeCaptureWorkerState(
        id=OUTCOME_CAPTURE_WORKER_STATE_ROW_ID,
        status=OUTCOME_STATUS_IDLE,
    )
    session.add(state)
    session.flush()
    return state


def acquire_outcome_capture_worker_lock(
    session: Session,
    *,
    holder: str | None = None,
    stale_after_minutes: int = DEFAULT_STALE_LOCK_MINUTES,
) -> OutcomeCaptureLockResult:
    lock_holder = holder or default_lock_holder()
    state = _get_or_create_state(session)
    now = utc_now()

    if state.status == OUTCOME_STATUS_STOPPED:
        return OutcomeCaptureLockResult(acquired=False, reason="worker_stopped", holder=state.lock_holder)

    if state.status == OUTCOME_STATUS_RUNNING and state.lock_holder not in (None, lock_holder):
        acquired_at = state.lock_acquired_at
        if acquired_at is not None:
            age = now - ensure_utc(acquired_at)
            if age <= timedelta(minutes=stale_after_minutes):
                return OutcomeCaptureLockResult(
                    acquired=False,
                    reason="lock_held",
                    holder=state.lock_holder,
                )

    state.status = OUTCOME_STATUS_RUNNING
    state.lock_holder = lock_holder
    state.lock_acquired_at = now
    state.updated_at = now
    session.flush()
    return OutcomeCaptureLockResult(acquired=True, reason="acquired", holder=lock_holder)


def release_outcome_capture_worker_lock(session: Session, *, holder: str | None = None) -> None:
    state = _get_or_create_state(session)
    lock_holder = holder or default_lock_holder()
    if state.lock_holder not in (None, lock_holder):
        return
    state.status = OUTCOME_STATUS_IDLE
    state.lock_holder = None
    state.lock_acquired_at = None
    state.updated_at = utc_now()
    session.flush()


def clear_outcome_capture_worker_stop(session: Session) -> None:
    state = _get_or_create_state(session)
    if state.status == OUTCOME_STATUS_STOPPED:
        state.status = OUTCOME_STATUS_IDLE
        state.updated_at = utc_now()
        session.flush()


def record_outcome_capture_cycle_finish(
    session: Session,
    *,
    run_id: str,
    started_at: datetime,
    finished_at: datetime,
    cycle_status: str,
    error: str | None = None,
) -> None:
    state = _get_or_create_state(session)
    state.last_cycle_started_at = started_at
    state.last_cycle_finished_at = finished_at
    state.last_cycle_status = cycle_status
    state.last_run_id = run_id
    state.last_error = error
    state.updated_at = finished_at
    session.flush()


def record_outcome_capture_worker_heartbeat(
    session: Session,
    *,
    at: datetime | None = None,
) -> None:
    state = _get_or_create_state(session)
    state.updated_at = at or utc_now()
    session.flush()
