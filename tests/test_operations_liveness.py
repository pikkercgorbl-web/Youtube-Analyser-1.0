"""Regression tests for worker activity liveness (Stage 1.20C.2)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.models.orm import DiscoveryWorkerState, MonitoringCycleRun, MonitoringWorkerState
from app.services.discovery_worker_lock import DISCOVERY_STATUS_RUNNING, acquire_discovery_worker_lock
from app.services.discovery_worker_runtime import DEFAULT_DISCOVERY_WORKER_INTERVAL_SECONDS
from app.services.monitoring_api_service import get_monitoring_worker_status
from app.services.monitoring_cycle import DEFAULT_MONITORING_WORKER_INTERVAL_SECONDS
from app.services.monitoring_worker_lock import (
    MONITORING_STATUS_RUNNING,
    acquire_monitoring_worker_lock,
    default_lock_holder,
)
from app.services.metrics import ensure_utc
from app.services.operations_overview_service import get_discovery_worker_activity
from app.services.worker_activity_policy import stale_activity_threshold_seconds

UTC = timezone.utc
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_discovery_active_despite_old_lock() -> None:
    session = _session()
    state = DiscoveryWorkerState(
        id=1,
        status=DISCOVERY_STATUS_RUNNING,
        lock_holder="host:discovery",
        lock_acquired_at=NOW - timedelta(minutes=95),
        last_cycle_finished_at=NOW - timedelta(minutes=10),
        last_cycle_status="ok",
        updated_at=NOW - timedelta(minutes=10),
    )
    session.add(state)
    session.commit()
    block = get_discovery_worker_activity(session, now=NOW, worker_state=state)
    assert block.activity_state == "active_recently"
    assert block.last_activity_at == state.last_cycle_finished_at


def test_discovery_stale_when_cycles_and_heartbeat_old() -> None:
    session = _session()
    threshold = stale_activity_threshold_seconds(DEFAULT_DISCOVERY_WORKER_INTERVAL_SECONDS)
    old = NOW - timedelta(seconds=threshold + 60)
    state = DiscoveryWorkerState(
        id=1,
        status=DISCOVERY_STATUS_RUNNING,
        lock_holder="host:discovery",
        lock_acquired_at=NOW - timedelta(hours=5),
        last_cycle_finished_at=old,
        last_cycle_status="ok",
        updated_at=old,
    )
    session.add(state)
    session.commit()
    block = get_discovery_worker_activity(session, now=NOW, worker_state=state)
    assert block.activity_state == "stale_activity"


def test_discovery_error_on_failed_cycle() -> None:
    session = _session()
    state = DiscoveryWorkerState(
        id=1,
        status=DISCOVERY_STATUS_RUNNING,
        lock_acquired_at=NOW - timedelta(minutes=5),
        last_cycle_finished_at=NOW - timedelta(minutes=2),
        last_cycle_status="failed",
        last_error="boom",
        updated_at=NOW - timedelta(minutes=2),
    )
    session.add(state)
    session.commit()
    block = get_discovery_worker_activity(session, now=NOW, worker_state=state)
    assert block.activity_state == "error"


def test_monitoring_active_despite_old_lock() -> None:
    session = _session()
    session.add(
        MonitoringWorkerState(
            id=1,
            status=MONITORING_STATUS_RUNNING,
            lock_holder="host:1",
            lock_acquired_at=NOW - timedelta(hours=19),
            updated_at=NOW - timedelta(minutes=18),
        ),
    )
    session.add(
        MonitoringCycleRun(
            run_id="m1",
            started_at=NOW - timedelta(minutes=20),
            finished_at=NOW - timedelta(minutes=18),
            runtime_seconds=10.0,
            cycle_status="ok",
        ),
    )
    session.commit()
    status = get_monitoring_worker_status(session, now=NOW)
    assert status.status == "running"
    expected = NOW - timedelta(minutes=18)
    assert status.last_seen is not None
    assert ensure_utc(status.last_seen) == ensure_utc(expected)


def test_monitoring_stale_when_cycles_old() -> None:
    session = _session()
    threshold = stale_activity_threshold_seconds(DEFAULT_MONITORING_WORKER_INTERVAL_SECONDS)
    old = NOW - timedelta(seconds=threshold + 120)
    session.add(
        MonitoringWorkerState(
            id=1,
            status=MONITORING_STATUS_RUNNING,
            lock_acquired_at=NOW - timedelta(hours=10),
            updated_at=old,
        ),
    )
    session.add(
        MonitoringCycleRun(
            run_id="m-old",
            started_at=old - timedelta(minutes=5),
            finished_at=old,
            runtime_seconds=5.0,
            cycle_status="ok",
        ),
    )
    session.commit()
    status = get_monitoring_worker_status(session, now=NOW)
    assert status.status == "stale"


def test_discovery_lock_recovery_unchanged() -> None:
    from unittest.mock import patch

    session = _session()
    holder_a = "host-a:discovery"
    holder_b = "host-b:discovery"
    state = DiscoveryWorkerState(id=1, status=DISCOVERY_STATUS_RUNNING, lock_holder=holder_a)
    state.lock_acquired_at = NOW - timedelta(minutes=30)
    state.updated_at = NOW
    session.add(state)
    session.flush()
    with patch("app.services.discovery_worker_lock.utc_now", return_value=NOW):
        fresh = acquire_discovery_worker_lock(session, holder=holder_b, stale_after_minutes=90)
    assert not fresh.acquired
    assert fresh.reason == "lock_held"
    state.lock_acquired_at = NOW - timedelta(minutes=100)
    session.flush()
    with patch("app.services.discovery_worker_lock.utc_now", return_value=NOW):
        recovered = acquire_discovery_worker_lock(session, holder=holder_b, stale_after_minutes=90)
    assert recovered.acquired


def test_monitoring_heartbeat_without_new_cycle_still_active() -> None:
    session = _session()
    session.add(
        MonitoringWorkerState(
            id=1,
            status=MONITORING_STATUS_RUNNING,
            lock_acquired_at=NOW - timedelta(hours=8),
            updated_at=NOW - timedelta(minutes=5),
        ),
    )
    session.commit()
    status = get_monitoring_worker_status(session, now=NOW)
    assert status.status == "running"


def test_monitoring_foreign_lock_blocked_until_stale() -> None:
    from unittest.mock import patch

    session = _session()
    holder_a = default_lock_holder()
    with patch("app.services.monitoring_worker_lock.utc_now", return_value=NOW):
        acquire_monitoring_worker_lock(session, holder=holder_a, stale_after_minutes=90)
    session.commit()
    with patch("app.services.monitoring_worker_lock.utc_now", return_value=NOW):
        blocked = acquire_monitoring_worker_lock(session, holder="other:1", stale_after_minutes=90)
    assert not blocked.acquired
    state = session.get(MonitoringWorkerState, 1)
    assert state is not None
    state.lock_acquired_at = NOW - timedelta(minutes=100)
    session.flush()
    with patch("app.services.monitoring_worker_lock.utc_now", return_value=NOW):
        recovered = acquire_monitoring_worker_lock(session, holder="other:1", stale_after_minutes=90)
    assert recovered.acquired


def main() -> None:
    tests = [
        test_discovery_active_despite_old_lock,
        test_discovery_stale_when_cycles_and_heartbeat_old,
        test_discovery_error_on_failed_cycle,
        test_monitoring_active_despite_old_lock,
        test_monitoring_stale_when_cycles_old,
        test_monitoring_heartbeat_without_new_cycle_still_active,
        test_discovery_lock_recovery_unchanged,
        test_monitoring_foreign_lock_blocked_until_stale,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"OK {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")
    if failed:
        raise SystemExit(f"{failed} failed")
    print("All operations liveness tests passed.")


if __name__ == "__main__":
    main()
