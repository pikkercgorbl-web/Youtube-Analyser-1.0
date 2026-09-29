"""Process singleton lock for monitoring worker (Stage 1.13C)."""

from __future__ import annotations

import socket
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.orm import MonitoringWorkerState
from app.services.metrics import ensure_utc, utc_now

MONITORING_WORKER_STATE_ROW_ID = 1
MONITORING_STATUS_IDLE = "idle"
MONITORING_STATUS_RUNNING = "running"
MONITORING_STATUS_STOPPED = "stopped"
DEFAULT_STALE_LOCK_MINUTES = 90


@dataclass(frozen=True, slots=True)
class MonitoringLockResult:
    acquired: bool
    reason: str
    holder: str | None = None


def default_lock_holder() -> str:
    return f"{socket.gethostname()}:{MONITORING_WORKER_STATE_ROW_ID}"


def _get_or_create_state(session: Session) -> MonitoringWorkerState:
    state = session.get(MonitoringWorkerState, MONITORING_WORKER_STATE_ROW_ID)
    if state is not None:
        return state
    state = MonitoringWorkerState(
        id=MONITORING_WORKER_STATE_ROW_ID,
        status=MONITORING_STATUS_IDLE,
    )
    session.add(state)
    session.flush()
    return state


def acquire_monitoring_worker_lock(
    session: Session,
    *,
    holder: str | None = None,
    stale_after_minutes: int = DEFAULT_STALE_LOCK_MINUTES,
) -> MonitoringLockResult:
    lock_holder = holder or default_lock_holder()
    state = _get_or_create_state(session)
    now = utc_now()

    if state.status == MONITORING_STATUS_STOPPED:
        return MonitoringLockResult(acquired=False, reason="worker_stopped", holder=state.lock_holder)

    if state.status == MONITORING_STATUS_RUNNING and state.lock_holder not in (None, lock_holder):
        acquired_at = state.lock_acquired_at
        if acquired_at is not None:
            age = now - ensure_utc(acquired_at)
            if age <= timedelta(minutes=stale_after_minutes):
                return MonitoringLockResult(
                    acquired=False,
                    reason="lock_held",
                    holder=state.lock_holder,
                )

    state.status = MONITORING_STATUS_RUNNING
    state.lock_holder = lock_holder
    state.lock_acquired_at = now
    state.updated_at = now
    session.flush()
    return MonitoringLockResult(acquired=True, reason="acquired", holder=lock_holder)


def release_monitoring_worker_lock(session: Session, *, holder: str | None = None) -> None:
    state = _get_or_create_state(session)
    lock_holder = holder or default_lock_holder()
    if state.lock_holder not in (None, lock_holder):
        return
    state.status = MONITORING_STATUS_IDLE
    state.lock_holder = None
    state.lock_acquired_at = None
    state.updated_at = utc_now()
    session.flush()


def request_monitoring_worker_stop(session: Session) -> None:
    state = _get_or_create_state(session)
    state.status = MONITORING_STATUS_STOPPED
    state.updated_at = utc_now()
    session.flush()


def clear_monitoring_worker_stop(session: Session) -> None:
    state = _get_or_create_state(session)
    if state.status == MONITORING_STATUS_STOPPED:
        state.status = MONITORING_STATUS_IDLE
        state.updated_at = utc_now()
        session.flush()
