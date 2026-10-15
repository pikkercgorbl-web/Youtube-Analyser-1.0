"""Resilience tests for outcome capture worker runtime (Stage 1.20E.2)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.models.orm import OutcomeCaptureWorkerState
from app.services.delayed_outcome_capture_cycle import DelayedOutcomeCaptureCycleSummary
from app.services.metrics import utc_now
from app.services.outcome_capture_worker_lock import (
    OUTCOME_CAPTURE_WORKER_STATE_ROW_ID,
    OUTCOME_STATUS_RUNNING,
    acquire_outcome_capture_worker_lock,
)
from app.services.outcome_capture_worker_runtime import (
    OutcomeCaptureWorkerConfig,
    _persist_cycle_status as real_persist_cycle_status,
    run_outcome_capture_worker_loop,
)

UTC = timezone.utc


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _session_factory():
    engine = _engine()
    factory = sessionmaker(bind=engine)

    def _make():
        return factory()

    return _make, factory


def _summary(run_id: str = "outcome_test_1") -> DelayedOutcomeCaptureCycleSummary:
    now = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
    return DelayedOutcomeCaptureCycleSummary(
        run_id=run_id,
        started_at=now,
        finished_at=now,
        cycle_status="ok",
        selected_video_count=0,
        fetch_failed_count=0,
    )


def test_db_unavailable_during_cycle_and_persist_retries() -> None:
    make_session, _ = _session_factory()
    sleeps: list[float] = []
    cycle_calls = {"n": 0}

    def fake_cycle(*_a, **_k):
        cycle_calls["n"] += 1
        if cycle_calls["n"] == 1:
            raise OperationalError("SELECT snapshots", {}, Exception("db down"))
        return _summary(run_id="outcome_recovered")

    persist_calls = {"n": 0}

    def fake_persist(session_factory, *, summary, cycle_error):
        persist_calls["n"] += 1
        if persist_calls["n"] == 1:
            raise OperationalError("INSERT state", {}, Exception("db down"))
        return real_persist_cycle_status(
            session_factory,
            summary=summary,
            cycle_error=cycle_error,
        )

    with patch(
        "app.services.outcome_capture_worker_runtime.run_delayed_outcome_capture_cycle",
        side_effect=fake_cycle,
    ), patch(
        "app.services.outcome_capture_worker_runtime._persist_cycle_status",
        side_effect=fake_persist,
    ):
        run_outcome_capture_worker_loop(
            make_session,
            object(),
            config=OutcomeCaptureWorkerConfig(
                interval_seconds=999,
                error_backoff_seconds=11,
            ),
            sleep_fn=lambda s: sleeps.append(s),
            stop_check=lambda: cycle_calls["n"] >= 2 and persist_calls["n"] >= 2,
        )

    assert cycle_calls["n"] == 2
    assert persist_calls["n"] == 2
    assert 11.0 in sleeps


def test_release_lock_failure_does_not_crash_main() -> None:
    make_session, _ = _session_factory()

    with patch(
        "app.services.outcome_capture_worker_runtime.run_delayed_outcome_capture_cycle",
        return_value=_summary(),
    ), patch(
        "app.services.outcome_capture_worker_runtime.release_outcome_capture_worker_lock",
        side_effect=OperationalError("release", {}, Exception("db down")),
    ):
        run_outcome_capture_worker_loop(
            make_session,
            object(),
            config=OutcomeCaptureWorkerConfig(interval_seconds=999),
            sleep_fn=lambda _s: None,
            stop_check=lambda: True,
        )


def test_db_recovers_and_worker_resumes_cycles() -> None:
    make_session, _ = _session_factory()
    cycles: list[str] = []
    attempts = {"n": 0}

    def fake_cycle(*_a, **_k):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise OperationalError("snapshots", {}, Exception("temporary"))
        run_id = f"outcome_{len(cycles) + 1}"
        cycles.append(run_id)
        return _summary(run_id=run_id)

    with patch(
        "app.services.outcome_capture_worker_runtime.run_delayed_outcome_capture_cycle",
        side_effect=fake_cycle,
    ):
        run_outcome_capture_worker_loop(
            make_session,
            object(),
            config=OutcomeCaptureWorkerConfig(
                interval_seconds=50,
                error_backoff_seconds=7,
            ),
            sleep_fn=lambda _s: None,
            stop_check=lambda: len(cycles) >= 1,
        )

    assert cycles == ["outcome_1"]


def test_does_not_run_when_lock_held_by_other_worker() -> None:
    make_session, factory = _session_factory()
    session = factory()
    session.add(
        OutcomeCaptureWorkerState(
            id=OUTCOME_CAPTURE_WORKER_STATE_ROW_ID,
            status=OUTCOME_STATUS_RUNNING,
            lock_holder="other-host:1",
            lock_acquired_at=utc_now(),
        ),
    )
    session.commit()
    session.close()

    cycle_calls: list[str] = []

    def fake_cycle(*_a, **_k):
        cycle_calls.append("cycle")
        return _summary()

    with patch(
        "app.services.outcome_capture_worker_runtime.run_delayed_outcome_capture_cycle",
        side_effect=fake_cycle,
    ):
        run_outcome_capture_worker_loop(
            make_session,
            object(),
            config=OutcomeCaptureWorkerConfig(stale_lock_minutes=90),
            sleep_fn=lambda _s: None,
            lock_holder="this-host:1",
        )

    assert cycle_calls == []


def test_stale_lock_allows_new_holder_after_recovery() -> None:
    make_session, factory = _session_factory()
    session = factory()
    stale_at = datetime(2020, 1, 1, tzinfo=UTC)
    session.add(
        OutcomeCaptureWorkerState(
            id=OUTCOME_CAPTURE_WORKER_STATE_ROW_ID,
            status=OUTCOME_STATUS_RUNNING,
            lock_holder="dead-host:1",
            lock_acquired_at=stale_at,
        ),
    )
    session.commit()
    session.close()

    lock = acquire_outcome_capture_worker_lock(
        factory(),
        holder="new-host:1",
        stale_after_minutes=90,
    )
    assert lock.acquired is True


def test_stops_without_cycle_when_renew_reports_other_holder() -> None:
    make_session, _ = _session_factory()
    cycle_calls: list[str] = []

    def fake_renew(_session_factory, *, holder, stale_after_minutes):
        return SimpleNamespace(
            acquired=False,
            reason="lock_held",
            holder="other-host:2",
        )

    with patch(
        "app.services.outcome_capture_worker_runtime.run_delayed_outcome_capture_cycle",
        side_effect=lambda *_a, **_k: (cycle_calls.append("cycle") or _summary()),
    ), patch(
        "app.services.outcome_capture_worker_runtime._renew_worker_lock",
        side_effect=fake_renew,
    ):
        run_outcome_capture_worker_loop(
            make_session,
            object(),
            config=OutcomeCaptureWorkerConfig(interval_seconds=999),
            sleep_fn=lambda _s: None,
            lock_holder="solo-host:1",
        )

    assert cycle_calls == []


def main() -> None:
    tests = [
        test_db_unavailable_during_cycle_and_persist_retries,
        test_release_lock_failure_does_not_crash_main,
        test_db_recovers_and_worker_resumes_cycles,
        test_does_not_run_when_lock_held_by_other_worker,
        test_stops_without_cycle_when_renew_reports_other_holder,
        test_stale_lock_allows_new_holder_after_recovery,
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
        raise SystemExit(f"{failed} test(s) failed")
    print("All outcome capture worker runtime tests passed.")


if __name__ == "__main__":
    main()
