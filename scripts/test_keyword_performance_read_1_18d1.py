"""Regression tests for keyword performance read-path optimizations (Stage 1.18D1)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.models.orm import (
    Channel,
    KeywordDiscoveryHit,
    KeywordScanRun,
    TargetKeyword,
    Video,
    VideoFormat,
    VideoSnapshot,
)
from app.services.keyword_performance_evaluation import (
    build_global_breakout_bundle,
    evaluate_keywords_batch,
    load_snapshots_for_horizon,
    make_evaluation_context,
    match_horizon_outcome,
    KeywordVideoBaseline,
)
from app.services.keyword_performance_service import list_keyword_performance

UTC = timezone.utc
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _session() -> Session:
    return sessionmaker(bind=_engine())()


def _seed_breakout_video(session: Session, video_id: str, *, views: int, age_hours: float) -> None:
    channel_id = "ch-main"
    if session.get(Channel, channel_id) is None:
        session.add(Channel(id=channel_id, title="C", subscribers_count=1000, created_at=NOW))
    published = NOW - timedelta(hours=age_hours)
    session.add(
        Video(
            id=video_id,
            title="V",
            views_count=views,
            likes_count=0,
            comments_count=0,
            published_at=published,
            duration_seconds=600,
            content_format=VideoFormat.MEDIUM,
            channel_id=channel_id,
        ),
    )
    session.add(
        VideoSnapshot(
            video_id=video_id,
            channel_id=channel_id,
            captured_at=NOW,
            source="test",
            run_id="r1",
            views=views,
            age_hours=age_hours,
            vph=round(views / age_hours, 4),
        ),
    )


def _seed_keyword_hit(session: Session, kw: TargetKeyword, video_id: str) -> None:
    session.add(
        KeywordScanRun(
            keyword_id=kw.id,
            discovery_run_id="run-1",
            started_at=NOW - timedelta(days=2),
            finished_at=NOW - timedelta(days=2),
            status="completed",
        ),
    )
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id=video_id,
            discovery_run_id="run-1",
            discovered_at=NOW - timedelta(hours=80),
            views_at_discovery=100,
            vph_at_discovery=50.0,
            content_format="regular",
            qualification_state="passed",
            persisted_for_monitoring=True,
        ),
    )


def test_global_breakout_denominator_unchained_bundle() -> None:
    session = _session()
    _seed_breakout_video(session, "v-high", views=5000, age_hours=5.0)
    _seed_breakout_video(session, "v-low", views=100, age_hours=50.0)
    session.commit()
    b1 = build_global_breakout_bundle(session, evaluated_at=NOW)
    b2 = build_global_breakout_bundle(session, evaluated_at=NOW)
    assert b1.global_eligible_video_count == b2.global_eligible_video_count
    assert b1.breakout_map["v-high"].rank == b2.breakout_map["v-high"].rank


def test_full_mode_metric_parity_attribution_and_breakout() -> None:
    session = _session()
    kw1 = TargetKeyword(keyword="alpha")
    kw2 = TargetKeyword(keyword="beta")
    session.add_all([kw1, kw2])
    session.flush()
    _seed_breakout_video(session, "shared", views=9000, age_hours=4.0)
    _seed_keyword_hit(session, kw1, "shared")
    _seed_keyword_hit(session, kw2, "shared")
    session.commit()

    full = list_keyword_performance(session, limit=10, include_breakout=True, include_delayed=True)
    assert len(full.items) == 2
    assert sum(i.attributed_video_count or 0 for i in full.items) == 2
    assert all(i.top_decile_breakout_count == 0 for i in full.items)
    assert all(i.monitorable_video_count == 1 for i in full.items)


def test_include_delayed_false_skips_horizon_snapshot_load() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k")
    session.add(kw)
    session.flush()
    _seed_breakout_video(session, "v1", views=1000, age_hours=10.0)
    _seed_keyword_hit(session, kw, "v1")
    session.commit()
    with patch(
        "app.services.keyword_performance_evaluation.load_snapshots_for_horizon",
        wraps=load_snapshots_for_horizon,
    ) as mocked:
        list_keyword_performance(session, limit=10, include_breakout=False, include_delayed=False)
        mocked.assert_not_called()


def test_include_breakout_false_skips_global_bundle() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k")
    session.add(kw)
    session.flush()
    _seed_breakout_video(session, "v1", views=1000, age_hours=10.0)
    _seed_keyword_hit(session, kw, "v1")
    session.commit()
    with patch(
        "app.services.keyword_performance_service.build_global_breakout_bundle",
    ) as mocked:
        result = list_keyword_performance(
            session,
            limit=10,
            include_breakout=False,
            include_delayed=False,
        )
        mocked.assert_not_called()
        assert result.context.global_eligible_video_count == 0
        assert result.items[0].top_decile_breakout_rate is None


def test_delayed_matching_unchanged_with_bounded_window() -> None:
    session = _session()
    discovery = NOW - timedelta(hours=72)
    target = discovery + timedelta(hours=72)
    session.add(Channel(id="ch", title="C", subscribers_count=1, created_at=NOW))
    session.add(
        Video(
            id="v",
            title="V",
            views_count=100,
            likes_count=0,
            comments_count=0,
            published_at=NOW - timedelta(days=5),
            duration_seconds=60,
            content_format=VideoFormat.MEDIUM,
            channel_id="ch",
        ),
    )
    session.add(
        VideoSnapshot(
            video_id="v",
            channel_id="ch",
            captured_at=target,
            source="test",
            run_id="r1",
            views=250,
        ),
    )
    session.commit()
    baseline = KeywordVideoBaseline(
        keyword_id=1,
        video_id="v",
        discovery_at=discovery,
        views_at_discovery=100,
        vph_at_discovery=10.0,
    )
    full = load_snapshots_for_horizon(session, {"v"})
    bounded = load_snapshots_for_horizon(
        session,
        {"v"},
        captured_from=discovery + timedelta(hours=60),
        captured_to=discovery + timedelta(hours=84),
    )
    o_full = match_horizon_outcome(baseline, full)
    o_bounded = match_horizon_outcome(baseline, bounded)
    assert o_full is not None and o_bounded is not None
    assert o_full.absolute_view_growth == o_bounded.absolute_view_growth == 150


def test_no_per_keyword_query_growth() -> None:
    session = _session()
    for idx in range(3):
        kw = TargetKeyword(keyword=f"k{idx}")
        session.add(kw)
        session.flush()
        _seed_breakout_video(session, f"v{idx}", views=1000 + idx, age_hours=8.0)
        _seed_keyword_hit(session, kw, f"v{idx}")
    session.commit()

    engine = session.get_bind()
    counts: list[int] = []

    def run_count(limit: int) -> int:
        count = 0

        def before_cursor_execute(*_a, **_k) -> None:
            nonlocal count
            count += 1

        event.listen(engine, "before_cursor_execute", before_cursor_execute, retval=False)
        try:
            list_keyword_performance(
                session,
                limit=limit,
                include_breakout=True,
                include_delayed=True,
            )
        finally:
            event.remove(engine, "before_cursor_execute", before_cursor_execute)
        return count

    counts.append(run_count(1))
    counts.append(run_count(3))
    assert counts[1] <= counts[0] + 2


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"OK {name}")
            except Exception as exc:
                failed += 1
                print(f"FAIL {name}: {exc}")
    raise SystemExit(failed)
