"""Tests for monitoring cycle and worker (Stage 1.13C)."""

from __future__ import annotations

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
from app.models.orm import Channel, Video, VideoFormat, VideoSnapshot
from app.services.monitoring_cycle import (
    MONITORING_CAPTURE_SOURCE,
    generate_monitoring_run_id,
    run_monitoring_cycle,
)
from app.services.monitoring_tier_budget_policy import ApiBudgetPolicy, MonitoringTierPolicy
from app.services.metrics import utc_now
from app.services.monitoring_worker_lock import acquire_monitoring_worker_lock
from app.services.monitoring_tier_budget_policy import (
    MonitoringDecision,
    MonitoringTier,
    TierCandidateInput,
)
from app.services.monitoring_worker_runtime import MonitoringWorkerConfig, run_monitoring_worker_loop
from app.models.orm import MonitoringWorkerState

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


def _add_video(
    session,
    video_id: str,
    *,
    channel_id: str = "ch1",
    published_at: datetime,
    views: int = 2400,
    content_format: VideoFormat = VideoFormat.MEDIUM,
) -> None:
    if session.get(Channel, channel_id) is None:
        session.add(
            Channel(
                id=channel_id,
                title="Channel",
                subscribers_count=1000,
                created_at=published_at,
            ),
        )
    session.add(
        Video(
            id=video_id,
            title="Video",
            views_count=views,
            likes_count=0,
            comments_count=0,
            published_at=published_at,
            duration_seconds=600,
            content_format=content_format,
            channel_id=channel_id,
        ),
    )
    session.commit()


def _add_snapshot(
    session,
    video_id: str,
    *,
    age_hours: float,
    captured_at: datetime,
    channel_id: str = "ch1",
    run_id: str = "seed",
) -> None:
    session.add(
        VideoSnapshot(
            video_id=video_id,
            channel_id=channel_id,
            captured_at=captured_at,
            published_at=captured_at - timedelta(hours=age_hours),
            age_hours=age_hours,
            views=1000,
            source="test",
            run_id=run_id,
        ),
    )
    session.commit()


class _MockClient:
    def __init__(self):
        self.calls: list[list[str]] = []

    def get_videos(self, video_ids: list[str]):
        from app.integrations.youtube.client import YouTubeVideoDetails

        self.calls.append(list(video_ids))
        return [
            YouTubeVideoDetails(
                video_id=vid,
                channel_id="ch1",
                title="t",
                published_at=_now() - timedelta(hours=24),
                views_count=5000,
                likes_count=1,
                comments_count=0,
                duration_seconds=600,
            )
            for vid in video_ids
        ]


class _FailClient:
    def get_videos(self, video_ids: list[str]):
        raise RuntimeError("network down")


def test_cycle_loads_candidates_and_returns_summary() -> None:
    session = _session()
    _add_video(session, "v1", published_at=_now() - timedelta(hours=10), views=100)
    summary = run_monitoring_cycle(session, youtube_client=_MockClient(), dry_run=True)
    assert summary.loaded_video_count == 1
    assert summary.run_id.startswith("monitoring_")


def test_no_due_work_skips_youtube() -> None:
    session = _session()
    _add_video(session, "v1", published_at=_now() - timedelta(hours=2), views=200)
    client = _MockClient()
    summary = run_monitoring_cycle(session, youtube_client=client, dry_run=False, current_time=_now())
    assert summary.selected_request_count == 0
    assert client.calls == []


def test_due_work_planner_budget_executor() -> None:
    session = _session()
    _add_video(session, "v1", published_at=_now() - timedelta(hours=24), views=2400)
    client = _MockClient()
    summary = run_monitoring_cycle(
        session,
        youtube_client=client,
        dry_run=False,
        current_time=_now(),
        run_id="monitoring_test_fixed_abcd1234",
    )
    assert summary.selected_request_count >= 1
    assert client.calls
    assert summary.inserted_snapshot_count >= 1


def test_budget_deferred_count() -> None:
    session = _session()
    pub = _now() - timedelta(hours=24)
    for i in range(10):
        _add_video(session, f"v{i}", published_at=pub, views=1000 + i * 100)
    summary = run_monitoring_cycle(
        session,
        youtube_client=_MockClient(),
        dry_run=True,
        current_time=_now(),
        budget_policy=ApiBudgetPolicy(max_capture_requests_per_cycle=2),
    )
    assert summary.capture_request_count >= 2
    assert summary.deferred_request_count >= 1
    assert summary.selected_request_count == 2


def test_channel_cap_applied() -> None:
    session = _session()
    pub = _now() - timedelta(hours=24)
    for i in range(4):
        _add_video(session, f"v{i}", channel_id="ch1", published_at=pub, views=5000 - i)
    summary = run_monitoring_cycle(
        session,
        youtube_client=_MockClient(),
        dry_run=True,
        current_time=_now(),
        tier_policy=MonitoringTierPolicy(max_active_videos_per_channel=2),
    )
    assert summary.channel_cap_excluded_count == 2


def test_tier_c_checkpoint_schedule() -> None:
    session = _session()
    pub = _now() - timedelta(hours=12)
    _add_video(session, "v1", published_at=pub, views=100)

    def _force_tier_c(candidates: list[TierCandidateInput], policy=None) -> list[MonitoringDecision]:
        item = candidates[0]
        return [
            MonitoringDecision(
                video_id=item.video_id,
                channel_id=item.channel_id,
                tier=MonitoringTier.C,
                reason_codes=("test",),
                raw_vph=item.raw_vph,
                age_hours=item.age_hours,
                baseline_status=None,
                vph_vs_channel_median=None,
                checkpoint_hours=(24, 72),
                eligible=True,
            ),
        ]

    with patch("app.services.monitoring_cycle.assign_monitoring_tiers", side_effect=_force_tier_c):
        summary = run_monitoring_cycle(
            session,
            youtube_client=_MockClient(),
            dry_run=True,
            current_time=_now(),
        )
    assert summary.capture_request_count == 0


def test_same_cycle_run_id_prefix() -> None:
    session = _session()
    _add_video(session, "v1", published_at=_now() - timedelta(hours=24), views=9000)
    run_id = "monitoring_20260915T120000Z_deadbeef"
    client = _MockClient()
    run_monitoring_cycle(
        session,
        youtube_client=client,
        dry_run=False,
        current_time=_now(),
        run_id=run_id,
    )
    snaps = session.query(VideoSnapshot).filter(VideoSnapshot.source == MONITORING_CAPTURE_SOURCE).all()
    assert snaps
    assert all(snap.run_id.startswith(f"{run_id}:v1:cp") for snap in snaps)


def test_restart_uses_snapshots_not_memory() -> None:
    session = _session()
    pub = _now() - timedelta(hours=24)
    _add_video(session, "v1", published_at=pub, views=2400)
    _add_snapshot(session, "v1", age_hours=24.0, captured_at=_now())
    client = _MockClient()
    summary = run_monitoring_cycle(session, youtube_client=client, dry_run=False, current_time=_now())
    assert summary.selected_request_count == 0
    assert client.calls == []


def test_partial_executor_failure_cycle_partial() -> None:
    session = _session()
    _add_video(session, "v1", published_at=_now() - timedelta(hours=24), views=5000)
    summary = run_monitoring_cycle(
        session,
        youtube_client=_FailClient(),
        dry_run=False,
        current_time=_now(),
    )
    assert summary.cycle_status == "partial"
    assert summary.fetch_failed_count >= 1


def test_worker_loop_catches_fatal_cycle_exception() -> None:
    sleeps: list[float] = []
    make_session, _engine = _session_factory()

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        raise StopIteration

    config = MonitoringWorkerConfig(interval_seconds=1, error_backoff_seconds=42)
    with patch(
        "app.services.monitoring_worker_runtime.run_monitoring_cycle",
        side_effect=RuntimeError("boom"),
    ):
        try:
            run_monitoring_worker_loop(
                make_session,
                _MockClient(),
                config=config,
                sleep_fn=fake_sleep,
            )
        except StopIteration:
            pass
    assert 42.0 in sleeps


def test_worker_no_overlapping_cycles() -> None:
    active = 0
    max_active = 0
    lock = threading.Lock()
    cycles = 0
    make_session, _engine = _session_factory()

    def fake_cycle(*_args, **_kwargs):
        nonlocal active, max_active, cycles
        with lock:
            active += 1
            max_active = max(max_active, active)
            cycles += 1
        time.sleep(0.05)
        with lock:
            active -= 1
        from app.services.monitoring_cycle import MonitoringCycleSummary

        return MonitoringCycleSummary(
            run_id="monitoring_test",
            started_at=_now(),
            cycle_status="ok",
        )

    stop_after = {"n": 0}

    def fake_sleep(_seconds: float) -> None:
        stop_after["n"] += 1
        if stop_after["n"] >= 2:
            raise StopIteration

    with patch("app.services.monitoring_worker_runtime.run_monitoring_cycle", side_effect=fake_cycle):
        try:
            run_monitoring_worker_loop(
                make_session,
                _MockClient(),
                config=MonitoringWorkerConfig(interval_seconds=0),
                sleep_fn=fake_sleep,
            )
        except StopIteration:
            pass
    assert max_active == 1
    assert cycles >= 2


def test_singleton_lock_blocks_second_worker() -> None:
    session = _session()
    first = acquire_monitoring_worker_lock(session, holder="worker-a")
    session.commit()
    assert first.acquired
    second = acquire_monitoring_worker_lock(session, holder="worker-b")
    assert not second.acquired


def test_stale_lock_recovery() -> None:
    session = _session()
    first = acquire_monitoring_worker_lock(session, holder="worker-a")
    session.commit()
    assert first.acquired
    state = session.get(MonitoringWorkerState, 1)
    assert state is not None
    state.lock_acquired_at = utc_now() - timedelta(hours=3)
    session.commit()
    second = acquire_monitoring_worker_lock(session, holder="worker-b", stale_after_minutes=60)
    assert second.acquired


def test_graceful_stop_exits_loop() -> None:
    calls = {"n": 0}
    make_session, _engine = _session_factory()

    def fake_cycle(*_a, **_k):
        calls["n"] += 1
        from app.services.monitoring_cycle import MonitoringCycleSummary

        return MonitoringCycleSummary(run_id="r", started_at=_now())

    def stop_check() -> bool:
        return calls["n"] >= 1

    with patch("app.services.monitoring_worker_runtime.run_monitoring_cycle", side_effect=fake_cycle):
        run_monitoring_worker_loop(
            make_session,
            _MockClient(),
            config=MonitoringWorkerConfig(interval_seconds=999),
            sleep_fn=lambda _s: None,
            stop_check=stop_check,
        )
    assert calls["n"] == 1


def test_lock_released_on_shutdown() -> None:
    make_session, _engine = _session_factory()
    done = {"flag": False}

    def fake_cycle(*_a, **_k):
        from app.services.monitoring_cycle import MonitoringCycleSummary

        done["flag"] = True
        return MonitoringCycleSummary(run_id="r", started_at=_now())

    with patch("app.services.monitoring_worker_runtime.run_monitoring_cycle", side_effect=fake_cycle):
        run_monitoring_worker_loop(
            make_session,
            _MockClient(),
            config=MonitoringWorkerConfig(interval_seconds=999),
            sleep_fn=lambda _s: None,
            stop_check=lambda: done["flag"],
        )
    session = make_session()
    state = session.get(MonitoringWorkerState, 1)
    assert state is not None
    from app.services.monitoring_worker_lock import MONITORING_STATUS_IDLE

    assert state.status == MONITORING_STATUS_IDLE
    assert state.lock_holder is None


def test_dry_run_no_network_or_persistence() -> None:
    session = _session()
    _add_video(session, "v1", published_at=_now() - timedelta(hours=24), views=8000)
    client = _MockClient()
    before = session.query(VideoSnapshot).count()
    run_monitoring_cycle(session, youtube_client=client, dry_run=True, current_time=_now())
    after = session.query(VideoSnapshot).count()
    assert client.calls == []
    assert before == after


def test_frozen_experiment_untouched() -> None:
    path = ROOT / "app" / "services" / "monitoring_cycle.py"
    text = path.read_text(encoding="utf-8")
    assert "stage110" not in text.lower()
    assert "cohort_T0_stage110" not in text


def test_generate_run_id_format() -> None:
    run_id = generate_monitoring_run_id(now=_now())
    assert run_id.startswith("monitoring_20260915T120000Z_")


def _run_script(name: str) -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / name)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise AssertionError(f"{name} failed: {result.stderr or result.stdout}")


def test_regressions() -> None:
    for script in (
        "test_video_snapshot_storage.py",
        "test_snapshot_collection_policy.py",
        "test_monitoring_tier_budget_policy.py",
        "test_revisit_executor.py",
    ):
        _run_script(script)


def main() -> None:
    tests = [
        test_cycle_loads_candidates_and_returns_summary,
        test_no_due_work_skips_youtube,
        test_due_work_planner_budget_executor,
        test_budget_deferred_count,
        test_channel_cap_applied,
        test_tier_c_checkpoint_schedule,
        test_same_cycle_run_id_prefix,
        test_restart_uses_snapshots_not_memory,
        test_partial_executor_failure_cycle_partial,
        test_worker_loop_catches_fatal_cycle_exception,
        test_worker_no_overlapping_cycles,
        test_singleton_lock_blocks_second_worker,
        test_stale_lock_recovery,
        test_graceful_stop_exits_loop,
        test_lock_released_on_shutdown,
        test_dry_run_no_network_or_persistence,
        test_frozen_experiment_untouched,
        test_generate_run_id_format,
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
    print("All monitoring worker tests passed.")


if __name__ == "__main__":
    main()
