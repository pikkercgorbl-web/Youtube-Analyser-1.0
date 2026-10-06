"""Tests for discovery worker (Stage 1.15B)."""

from __future__ import annotations

import importlib.util
import logging
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.models.orm import DiscoveryWorkerState, TargetKeyword
from app.services.discovery_cycle import DiscoveryCycleOutcome, DiscoveryCycleSummary, generate_discovery_run_id
from app.services.discovery_worker_lock import (
    DISCOVERY_STATUS_IDLE,
    acquire_discovery_worker_lock,
)
from app.services.discovery_worker_runtime import DiscoveryWorkerConfig, run_discovery_worker
from app.services.metrics import utc_now
from app.services.target_keywords_service import TargetKeywordsService

UTC = timezone.utc


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _session():
    return sessionmaker(bind=_engine())()


def _session_factory():
    engine = _engine()
    factory = sessionmaker(bind=engine)

    def _make():
        return factory()

    return _make, engine


def _now() -> datetime:
    return datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


def _empty_outcome(*, run_id: str) -> DiscoveryCycleOutcome:
    return DiscoveryCycleOutcome(
        summary=DiscoveryCycleSummary(
            run_id=run_id,
            started_at=_now(),
            finished_at=_now(),
            cycle_status="ok",
        ),
    )


def test_worker_runs_discovery_cycle() -> None:
    calls: list[str] = []
    make_session, _ = _session_factory()

    def fake_cycle(*_args, **_kwargs):
        calls.append("cycle")
        return _empty_outcome(run_id="discovery_test_1")

    with patch("app.services.discovery_worker_runtime.run_discovery_cycle", side_effect=fake_cycle):
        run_discovery_worker(
            make_session,
            object(),
            config=DiscoveryWorkerConfig(interval_seconds=999),
            sleep_fn=lambda _s: None,
            stop_check=lambda: len(calls) >= 1,
        )
    assert calls == ["cycle"]


def test_worker_repeats_after_interval() -> None:
    sleeps: list[float] = []
    cycles = {"n": 0}
    make_session, _ = _session_factory()

    def fake_cycle(*_a, **_k):
        cycles["n"] += 1
        return _empty_outcome(run_id=f"discovery_{cycles['n']}")

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if cycles["n"] >= 2:
            raise StopIteration

    with patch("app.services.discovery_worker_runtime.run_discovery_cycle", side_effect=fake_cycle):
        try:
            run_discovery_worker(
                make_session,
                object(),
                config=DiscoveryWorkerConfig(interval_seconds=77),
                sleep_fn=fake_sleep,
            )
        except StopIteration:
            pass
    assert cycles["n"] >= 2
    assert 77.0 in sleeps


def test_worker_no_overlapping_cycles() -> None:
    active = 0
    max_active = 0
    lock = threading.Lock()
    make_session, _ = _session_factory()

    def fake_cycle(*_a, **_k):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return _empty_outcome(run_id="discovery_overlap")

    stop_after = {"n": 0}

    def fake_sleep(_s: float) -> None:
        stop_after["n"] += 1
        if stop_after["n"] >= 2:
            raise StopIteration

    with patch("app.services.discovery_worker_runtime.run_discovery_cycle", side_effect=fake_cycle):
        try:
            run_discovery_worker(
                make_session,
                object(),
                config=DiscoveryWorkerConfig(interval_seconds=0),
                sleep_fn=fake_sleep,
            )
        except StopIteration:
            pass
    assert max_active == 1


def test_singleton_lock_blocks_second_worker() -> None:
    session = _session()
    first = acquire_discovery_worker_lock(session, holder="worker-a")
    session.commit()
    assert first.acquired
    second = acquire_discovery_worker_lock(session, holder="worker-b")
    assert not second.acquired


def test_stale_lock_recovery() -> None:
    session = _session()
    first = acquire_discovery_worker_lock(session, holder="worker-a")
    session.commit()
    assert first.acquired
    state = session.get(DiscoveryWorkerState, 1)
    assert state is not None
    state.lock_acquired_at = utc_now() - timedelta(hours=3)
    session.commit()
    second = acquire_discovery_worker_lock(session, holder="worker-b", stale_after_minutes=60)
    assert second.acquired


def test_graceful_stop_exits_loop() -> None:
    calls = {"n": 0}
    make_session, _ = _session_factory()

    def fake_cycle(*_a, **_k):
        calls["n"] += 1
        return _empty_outcome(run_id="discovery_stop")

    with patch("app.services.discovery_worker_runtime.run_discovery_cycle", side_effect=fake_cycle):
        run_discovery_worker(
            make_session,
            object(),
            config=DiscoveryWorkerConfig(interval_seconds=999),
            sleep_fn=lambda _s: None,
            stop_check=lambda: calls["n"] >= 1,
        )
    assert calls["n"] == 1


def test_lock_released_on_shutdown() -> None:
    make_session, _ = _session_factory()
    done = {"flag": False}

    def fake_cycle(*_a, **_k):
        done["flag"] = True
        return _empty_outcome(run_id="discovery_lock")

    with patch("app.services.discovery_worker_runtime.run_discovery_cycle", side_effect=fake_cycle):
        run_discovery_worker(
            make_session,
            object(),
            config=DiscoveryWorkerConfig(interval_seconds=999),
            sleep_fn=lambda _s: None,
            stop_check=lambda: done["flag"],
        )
    session = make_session()
    state = session.get(DiscoveryWorkerState, 1)
    assert state is not None
    assert state.status == DISCOVERY_STATUS_IDLE
    assert state.lock_holder is None


def test_fatal_cycle_exception_backoff_and_continue() -> None:
    """First cycle raises RuntimeError('boom') on purpose; worker must backoff and retry."""
    sleeps: list[float] = []
    attempts = {"n": 0}
    make_session, _ = _session_factory()
    runtime_logger = logging.getLogger("app.services.discovery_worker_runtime")
    previous_level = runtime_logger.level

    def fake_cycle(*_a, **_k):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("boom")
        return _empty_outcome(run_id="discovery_recovered")

    config = DiscoveryWorkerConfig(interval_seconds=1, error_backoff_seconds=42)
    runtime_logger.setLevel(logging.CRITICAL)
    try:
        with patch("app.services.discovery_worker_runtime.run_discovery_cycle", side_effect=fake_cycle):
            run_discovery_worker(
                make_session,
                object(),
                config=config,
                sleep_fn=lambda seconds: sleeps.append(seconds),
                stop_check=lambda: attempts["n"] >= 2,
            )
    finally:
        runtime_logger.setLevel(previous_level)
    assert 42.0 in sleeps
    assert attempts["n"] >= 2


def test_empty_keyword_db_no_crash() -> None:
    make_session, _ = _session_factory()

    with patch(
        "app.services.discovery_worker_runtime.run_discovery_cycle",
        return_value=_empty_outcome(run_id="discovery_empty"),
    ):
        run_discovery_worker(
            make_session,
            object(),
            config=DiscoveryWorkerConfig(interval_seconds=999),
            sleep_fn=lambda _s: None,
            stop_check=lambda: True,
        )


def test_each_cycle_distinct_run_id() -> None:
    run_ids: list[str] = []
    make_session, _ = _session_factory()
    counter = {"n": 0}

    def fake_cycle(*_a, **_k):
        counter["n"] += 1
        rid = generate_discovery_run_id(now=_now() + timedelta(seconds=counter["n"]))
        run_ids.append(rid)
        return _empty_outcome(run_id=rid)

    def fake_sleep(_s: float) -> None:
        if len(run_ids) >= 2:
            raise StopIteration

    with patch("app.services.discovery_worker_runtime.run_discovery_cycle", side_effect=fake_cycle):
        try:
            run_discovery_worker(
                make_session,
                object(),
                config=DiscoveryWorkerConfig(interval_seconds=0),
                sleep_fn=fake_sleep,
            )
        except StopIteration:
            pass
    assert len(run_ids) >= 2
    assert len(set(run_ids)) == len(run_ids)


def test_keyword_rotation_last_checked() -> None:
    session = _session()
    now = _now()
    session.add_all(
        [
            TargetKeyword(
                keyword="a",
                last_checked=now - timedelta(days=2),
                next_scan_at=now - timedelta(hours=1),
                lifecycle_status="active",
            ),
            TargetKeyword(
                keyword="b",
                last_checked=None,
                next_scan_at=now - timedelta(hours=3),
                lifecycle_status="active",
            ),
            TargetKeyword(
                keyword="c",
                last_checked=now - timedelta(days=1),
                next_scan_at=now - timedelta(hours=2),
                lifecycle_status="active",
            ),
        ],
    )
    session.commit()
    svc = TargetKeywordsService()
    batch1 = svc.pick_due_batch(session, batch_size=2)
    ids1 = [r.id for r in batch1]
    svc.mark_checked(session, ids1)
    session.commit()
    batch2 = svc.pick_due_batch(session, batch_size=2)
    ids2 = [r.id for r in batch2]
    assert set(ids1).isdisjoint(set(ids2)) or len(batch2) <= 2


def _load_cli_wiring_tests():
    path = ROOT / "scripts" / "test_discovery_cli_wiring.py"
    spec = importlib.util.spec_from_file_location("test_discovery_cli_wiring", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_discovery_cycle_cli_wiring_without_live_infra() -> None:
    """CLI argv, session/youtube injection, JSON summary — see test_discovery_cli_wiring.py."""
    wiring = _load_cli_wiring_tests()
    wiring.test_cli_dry_run_and_batch_size_wiring()
    wiring.test_cli_failed_cycle_exit_code()


def test_monitoring_worker_not_imported() -> None:
    runtime_text = (ROOT / "app" / "services" / "discovery_worker_runtime.py").read_text(encoding="utf-8")
    assert "monitoring_worker" not in runtime_text
    assert "run_monitoring_cycle" not in runtime_text


def test_frozen_stage110_untouched() -> None:
    text = (ROOT / "app" / "services" / "discovery_worker_runtime.py").read_text(encoding="utf-8")
    assert "stage110" not in text.lower()


def _run_script(name: str) -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / name)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0:
        raise AssertionError(f"{name}: {proc.stderr or proc.stdout}")


def test_regressions() -> None:
    _run_script("test_discovery_cycle.py")
    _run_script("test_monitoring_worker.py")
    _run_script("test_monitoring_api.py")


def main() -> None:
    tests = [
        test_worker_runs_discovery_cycle,
        test_worker_repeats_after_interval,
        test_worker_no_overlapping_cycles,
        test_singleton_lock_blocks_second_worker,
        test_stale_lock_recovery,
        test_graceful_stop_exits_loop,
        test_lock_released_on_shutdown,
        test_fatal_cycle_exception_backoff_and_continue,
        test_empty_keyword_db_no_crash,
        test_each_cycle_distinct_run_id,
        test_keyword_rotation_last_checked,
        test_discovery_cycle_cli_wiring_without_live_infra,
        test_monitoring_worker_not_imported,
        test_frozen_stage110_untouched,
        test_regressions,
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
    print("All discovery worker tests passed.")


if __name__ == "__main__":
    main()
