"""Tests for Breakout Ranking v1 (Stage 1.17B)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.models.orm import Channel, Video, VideoFormat, VideoFormatEnrichmentAttempt, VideoSnapshot
from app.services.channel_subscriber_backfill import SUBSCRIBERS_API_KNOWN
from app.services.breakout_ranking_service import (
    breakout_fundamental_eligibility,
    rank_breakout_v1,
)
from app.services.monitoring_api_service import (
    list_monitoring_videos,
    list_monitoring_videos_breakout,
)
from app.services.monitoring_tier_budget_policy import ApiBudgetPolicy, MonitoringTierPolicy
from app.services.monitoring_video_source import MonitoredVideoState
from app.services import video_snapshot_storage as video_snapshot_storage_module

UTC = timezone.utc
NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _state(
    video_id: str,
    *,
    vph: float | None = 10.0,
    age_hours: float = 24.0,
    content_format: str | None = "regular",
    is_short: bool = False,
    is_live: bool = False,
) -> MonitoredVideoState:
    pub = NOW - timedelta(hours=age_hours)
    return MonitoredVideoState(
        video_id=video_id,
        channel_id="ch1",
        published_at=pub,
        raw_vph=vph,
        age_hours=age_hours,
        content_format=content_format,
        is_short=is_short,
        is_live=is_live,
    )


def test_deterministic_ranking_order() -> None:
    states = [
        _state("v3", vph=50.0),
        _state("v1", vph=100.0),
        _state("v2", vph=100.0),
    ]
    views = {"v1": 200, "v2": 300, "v3": 999}
    ranked = rank_breakout_v1(states, views_by_video_id=views)
    assert [r.video_id for r in ranked] == ["v2", "v1", "v3"]
    assert [r.rank for r in ranked] == [1, 2, 3]
    assert ranked[0].ranking_value == 100.0


def test_same_input_same_rank() -> None:
    states = [_state("b", vph=2.0), _state("a", vph=5.0)]
    views = {"a": 10, "b": 10}
    first = rank_breakout_v1(states, views_by_video_id=views)
    second = rank_breakout_v1(states, views_by_video_id=views)
    assert [(r.video_id, r.rank) for r in first] == [(r.video_id, r.rank) for r in second]


def test_missing_vph_excluded() -> None:
    ok, reason = breakout_fundamental_eligibility(_state("x", vph=None), max_age_monitoring_hours=72.0)
    assert not ok
    assert reason == "missing_vph"
    assert rank_breakout_v1([_state("x", vph=None)]) == []


def test_age_beyond_horizon_excluded() -> None:
    ok, reason = breakout_fundamental_eligibility(_state("x", age_hours=80.0), max_age_monitoring_hours=72.0)
    assert not ok
    assert reason == "stale_discovery_age"


def test_short_and_live_excluded() -> None:
    short_ok, short_reason = breakout_fundamental_eligibility(
        _state("s", content_format="short", is_short=True),
        max_age_monitoring_hours=72.0,
    )
    live_ok, live_reason = breakout_fundamental_eligibility(
        _state("l", content_format="live", is_live=True),
        max_age_monitoring_hours=72.0,
    )
    assert not short_ok and short_reason == "short_format"
    assert not live_ok and live_reason == "live_format"


def _seed_channel_video(
    session: Session,
    video_id: str,
    *,
    vph: float,
    views: int,
    age_hours: float = 20.0,
    channel_id: str = "ch1",
) -> None:
    if session.get(Channel, channel_id) is None:
        session.add(
            Channel(
                id=channel_id,
                title=f"Channel {channel_id}",
                subscribers_count=100,
                subscribers_api_status=SUBSCRIBERS_API_KNOWN,
                subscribers_api_checked_at=NOW,
                created_at=NOW,
            ),
        )
    pub = NOW - timedelta(hours=age_hours)
    session.add(
        Video(
            id=video_id,
            title=f"Video {video_id}",
            views_count=views,
            likes_count=0,
            comments_count=0,
            published_at=pub,
            published_at_source="api_snippet",
            duration_seconds=600,
            content_format=VideoFormat.MEDIUM,
            channel_id=channel_id,
        ),
    )
    session.add(
        VideoFormatEnrichmentAttempt(
            video_id=video_id,
            last_attempt_at=NOW,
            last_outcome="confirmed_regular",
        ),
    )
    session.add(
        VideoSnapshot(
            video_id=video_id,
            channel_id=channel_id,
            captured_at=NOW,
            published_at=pub,
            age_hours=age_hours,
            views=views,
            vph=vph,
            source="test",
            run_id="r1",
        ),
    )
    session.commit()


def test_channel_cap_independence() -> None:
    engine = _engine()
    factory = sessionmaker(bind=engine)
    session = factory()
    # Persisted snapshot.vph must match views/age at capture (derived read path ignores stale stored vph).
    _seed_channel_video(session, "v1", vph=100.0, views=1000, age_hours=10.0)
    _seed_channel_video(session, "v2", vph=2000 / 12.0, views=2000, age_hours=12.0)
    _seed_channel_video(session, "v3", vph=3000 / 14.0, views=3000, age_hours=14.0)
    _seed_channel_video(session, "v4", vph=500.0, views=20000, age_hours=40.0)

    policy = MonitoringTierPolicy(max_active_videos_per_channel=1)
    budget = ApiBudgetPolicy(max_active_monitored_videos=500)
    with patch("app.services.monitoring_api_service.utc_now", return_value=NOW):
        with patch("app.services.monitoring_api_service.MonitoringTierPolicy", return_value=policy):
            with patch("app.services.monitoring_api_service.ApiBudgetPolicy", return_value=budget):
                breakout_rows, _ = list_monitoring_videos_breakout(session)
                priority_result = list_monitoring_videos(session, sort="priority", live_planner=True)
                priority_rows = priority_result.rows

    breakout_ids = {r.state.video_id for r in breakout_rows}
    priority_ids = {r.state.video_id for r in priority_rows}
    assert "v4" in breakout_ids
    assert breakout_rows[0].state.video_id == "v4"
    assert "v4" not in priority_ids
    assert len(priority_ids) <= 1


def test_global_cap_independence() -> None:
    engine = _engine()
    factory = sessionmaker(bind=engine)
    session = factory()
    for idx in range(5):
        _seed_channel_video(
            session,
            f"g{idx}",
            vph=float(100 - idx),
            views=1000 + idx,
            channel_id=f"ch{idx}",
        )

    policy = MonitoringTierPolicy(max_active_videos_per_channel=10)
    budget = ApiBudgetPolicy(max_active_monitored_videos=2)
    with patch("app.services.monitoring_api_service.utc_now", return_value=NOW):
        with patch("app.services.monitoring_api_service.MonitoringTierPolicy", return_value=policy):
            with patch("app.services.monitoring_api_service.ApiBudgetPolicy", return_value=budget):
                breakout_rows, total_b = list_monitoring_videos_breakout(session)
                priority_result = list_monitoring_videos(session, sort="priority", live_planner=True)
                priority_rows = priority_result.rows

    assert total_b == 5
    assert len(priority_rows) == 2
    excluded = [r for r in breakout_rows if not r.in_active_capture_pool]
    assert excluded
    assert any(r.state.video_id not in {p.state.video_id for p in priority_rows} for r in excluded)


def test_breakout_batch_queries_not_n_plus_one() -> None:
    engine = _engine()
    factory = sessionmaker(bind=engine)
    session = factory()
    for idx in range(8):
        _seed_channel_video(session, f"n{idx}", vph=float(idx + 1), views=100 * idx)

    original_latest = video_snapshot_storage_module.get_latest_snapshots_for_videos
    call_count = 0

    def counting_latest(db, video_ids):
        nonlocal call_count
        call_count += 1
        return original_latest(db, video_ids)

    with patch("app.services.monitoring_api_service.utc_now", return_value=NOW):
        with patch.object(
            video_snapshot_storage_module,
            "get_latest_snapshots_for_videos",
            side_effect=counting_latest,
        ):
            list_monitoring_videos_breakout(session)

    assert call_count <= 2


def test_priority_sort_regression_unchanged_with_breakout_present() -> None:
    engine = _engine()
    factory = sessionmaker(bind=engine)
    session = factory()
    _seed_channel_video(session, "p1", vph=40.0, views=4000)
    _seed_channel_video(session, "p2", vph=30.0, views=3000, channel_id="ch2")

    with patch("app.services.monitoring_api_service.utc_now", return_value=NOW):
        first = list_monitoring_videos(session, sort="priority", live_planner=True)
        second = list_monitoring_videos(session, sort="priority", live_planner=True)

    assert first.total == second.total == 2
    assert [r.state.video_id for r in first.rows] == [r.state.video_id for r in second.rows]


def main() -> None:
    tests = [
        test_deterministic_ranking_order,
        test_same_input_same_rank,
        test_missing_vph_excluded,
        test_age_beyond_horizon_excluded,
        test_short_and_live_excluded,
        test_channel_cap_independence,
        test_global_cap_independence,
        test_breakout_batch_queries_not_n_plus_one,
        test_priority_sort_regression_unchanged_with_breakout_present,
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
    print("All breakout ranking tests passed.")


if __name__ == "__main__":
    main()
