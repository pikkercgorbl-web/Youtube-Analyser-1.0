"""Process singleton lock for discovery worker (Stage 1.15B)."""

from __future__ import annotations

import socket
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.orm import DiscoveryWorkerState
from app.services.metrics import ensure_utc, utc_now

DISCOVERY_WORKER_STATE_ROW_ID = 1
DISCOVERY_STATUS_IDLE = "idle"
DISCOVERY_STATUS_RUNNING = "running"
DISCOVERY_STATUS_STOPPED = "stopped"
DEFAULT_STALE_LOCK_MINUTES = 90


@dataclass(frozen=True, slots=True)
class DiscoveryLockResult:
    acquired: bool
    reason: str
    holder: str | None = None


def default_discovery_lock_holder() -> str:
    return f"{socket.gethostname()}:discovery"


def _get_or_create_state(session: Session) -> DiscoveryWorkerState:
    state = session.get(DiscoveryWorkerState, DISCOVERY_WORKER_STATE_ROW_ID)
    if state is not None:
        return state
    state = DiscoveryWorkerState(
        id=DISCOVERY_WORKER_STATE_ROW_ID,
        status=DISCOVERY_STATUS_IDLE,
    )
    session.add(state)
    session.flush()
    return state


def acquire_discovery_worker_lock(
    session: Session,
    *,
    holder: str | None = None,
    stale_after_minutes: int = DEFAULT_STALE_LOCK_MINUTES,
) -> DiscoveryLockResult:
    lock_holder = holder or default_discovery_lock_holder()
    state = _get_or_create_state(session)
    now = utc_now()

    if state.status == DISCOVERY_STATUS_STOPPED:
        return DiscoveryLockResult(acquired=False, reason="worker_stopped", holder=state.lock_holder)

    if state.status == DISCOVERY_STATUS_RUNNING and state.lock_holder not in (None, lock_holder):
        acquired_at = state.lock_acquired_at
        if acquired_at is not None:
            age = now - ensure_utc(acquired_at)
            if age <= timedelta(minutes=stale_after_minutes):
                return DiscoveryLockResult(
                    acquired=False,
                    reason="lock_held",
                    holder=state.lock_holder,
                )

    state.status = DISCOVERY_STATUS_RUNNING
    state.lock_holder = lock_holder
    state.lock_acquired_at = now
    state.updated_at = now
    session.flush()
    return DiscoveryLockResult(acquired=True, reason="acquired", holder=lock_holder)


def release_discovery_worker_lock(session: Session, *, holder: str | None = None) -> None:
    state = _get_or_create_state(session)
    lock_holder = holder or default_discovery_lock_holder()
    if state.lock_holder not in (None, lock_holder):
        return
    state.status = DISCOVERY_STATUS_IDLE
    state.lock_holder = None
    state.lock_acquired_at = None
    state.updated_at = utc_now()
    session.flush()


def request_discovery_worker_stop(session: Session) -> None:
    state = _get_or_create_state(session)
    state.status = DISCOVERY_STATUS_STOPPED
    state.updated_at = utc_now()
    session.flush()


def clear_discovery_worker_stop(session: Session) -> None:
    state = _get_or_create_state(session)
    if state.status == DISCOVERY_STATUS_STOPPED:
        state.status = DISCOVERY_STATUS_IDLE
        state.updated_at = utc_now()
        session.flush()


def record_discovery_worker_cycle(
    session: Session,
    *,
    started_at: datetime,
    finished_at: datetime,
    run_id: str,
    cycle_status: str,
    last_error: str | None = None,
) -> None:
    state = _get_or_create_state(session)
    state.last_cycle_started_at = started_at
    state.last_cycle_finished_at = finished_at
    state.last_run_id = run_id
    state.last_cycle_status = cycle_status
    state.last_error = last_error
    state.updated_at = utc_now()
    session.flush()
