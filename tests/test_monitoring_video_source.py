"""Tests for monitorable video state loading (batch snapshot fetch)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.models.orm import Channel, Video, VideoFormat, VideoSnapshot
from app.services.monitoring_api_service import build_active_monitoring_enriched
from app.services.monitoring_video_source import load_monitored_video_states

UTC = timezone.utc
NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
PUB = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _session() -> Session:
    return sessionmaker(bind=_engine())()


def _seed_channel(session: Session, channel_id: str = "ch1") -> None:
    session.add(
        Channel(
            id=channel_id,
            title="Channel",
            subscribers_count=1000,
            created_at=PUB,
        ),
    )


def _seed_video(
    session: Session,
    video_id: str,
    *,
    views: int = 1000,
    fmt: VideoFormat = VideoFormat.MEDIUM,
) -> None:
    session.add(
        Video(
            id=video_id,
            title=f"Title {video_id}",
            views_count=views,
            likes_count=0,
            comments_count=0,
            published_at=PUB,
            duration_seconds=600,
            content_format=fmt,
            channel_id="ch1",
        ),
    )


def _seed_snapshot(
    session: Session,
    video_id: str,
    *,
    captured_at: datetime,
    views: int,
    vph: float | None = 50.0,
) -> None:
    session.add(
        VideoSnapshot(
            video_id=video_id,
            channel_id="ch1",
            captured_at=captured_at,
            published_at=PUB,
            age_hours=48.0,
            views=views,
            likes=0,
            comments=0,
            subscribers=1000,
            vph=vph,
            source="test",
            run_id="run1",
            fetch_status="refreshed",
        ),
    )


def test_short_and_live_excluded() -> None:
    session = _session()
    _seed_channel(session)
    _seed_video(session, "regular1")
    _seed_video(session, "short1", fmt=VideoFormat.SHORT)
    _seed_video(session, "live1", fmt=VideoFormat.LIVE)
    session.commit()
    ids = [s.video_id for s in load_monitored_video_states(session, now=NOW)]
    assert ids == ["regular1"]


def test_latest_snapshot_overrides_video_views_and_vph() -> None:
    session = _session()
    _seed_channel(session)
    _seed_video(session, "v1", views=1000)
    _seed_snapshot(session, "v1", captured_at=datetime(2026, 9, 15, 12, 0, tzinfo=UTC), views=5000, vph=120.5)
    session.commit()
    state = load_monitored_video_states(session, now=NOW)[0]
    assert state.raw_vph == 120.5


def test_no_snapshot_falls_back_to_video_views() -> None:
    session = _session()
    _seed_channel(session)
    _seed_video(session, "v1", views=3333)
    session.commit()
    state = load_monitored_video_states(session, now=NOW)[0]
    assert state.raw_vph == round(3333 / state.age_hours, 4)


def test_multiple_snapshots_pick_latest() -> None:
    session = _session()
    _seed_channel(session)
    _seed_video(session, "v1", views=100)
    _seed_snapshot(session, "v1", captured_at=datetime(2026, 9, 15, 10, 0, tzinfo=UTC), views=2000, vph=10.0)
    _seed_snapshot(session, "v1", captured_at=datetime(2026, 9, 16, 10, 0, tzinfo=UTC), views=9000, vph=99.9)
    session.commit()
    state = load_monitored_video_states(session, now=NOW)[0]
    assert state.raw_vph == 99.9


def test_build_active_single_snapshot_query_for_active_set() -> None:
    session = _session()
    _seed_channel(session)
    for i in range(5):
        vid = f"active{i}"
        _seed_video(session, vid, views=5000 + i)
        _seed_snapshot(
            session,
            vid,
            captured_at=datetime(2026, 9, 15, 12, i, tzinfo=UTC),
            views=8000 + i,
            vph=100.0 + i,
        )
        _seed_snapshot(
            session,
            vid,
            captured_at=datetime(2026, 9, 15, 14, i, tzinfo=UTC),
            views=9000 + i,
            vph=110.0 + i,
        )
    session.commit()

    engine = session.get_bind()
    snapshot_query_count = 0

    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany) -> None:
        nonlocal snapshot_query_count
        sql = statement if isinstance(statement, str) else str(statement)
        if "video_snapshots" in sql.lower():
            snapshot_query_count += 1

    event.listen(engine, "before_cursor_execute", _before_cursor_execute, retval=False)
    try:
        enriched, tier_counts, _ = build_active_monitoring_enriched(session, now=NOW)
    finally:
        event.remove(engine, "before_cursor_execute", _before_cursor_execute)

    assert len(enriched) >= 1
    # One batch for load_monitored_video_states + one batch for active planner/latest.
    assert snapshot_query_count == 2, f"expected 2 snapshot batch queries, got {snapshot_query_count}"


def test_batch_fetch_query_count() -> None:
    session = _session()
    _seed_channel(session)
    n = 40
    for i in range(n):
        vid = f"v{i:03d}"
        _seed_video(session, vid, views=1000 + i)
        _seed_snapshot(
            session,
            vid,
            captured_at=datetime(2026, 9, 15, 12, 0, tzinfo=UTC),
            views=2000 + i,
            vph=float(i),
        )
    session.commit()

    engine = session.get_bind()
    snapshot_query_count = 0

    def _before_cursor_execute(
        conn,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ) -> None:
        nonlocal snapshot_query_count
        sql = statement if isinstance(statement, str) else str(statement)
        if "video_snapshots" in sql.lower():
            snapshot_query_count += 1

    event.listen(engine, "before_cursor_execute", _before_cursor_execute, retval=False)
    try:
        states = load_monitored_video_states(session, now=NOW)
    finally:
        event.remove(engine, "before_cursor_execute", _before_cursor_execute)

    assert len(states) == n
    assert snapshot_query_count == 1, f"expected 1 snapshot batch query, got {snapshot_query_count}"


def main() -> None:
    tests = [
        test_short_and_live_excluded,
        test_latest_snapshot_overrides_video_views_and_vph,
        test_no_snapshot_falls_back_to_video_views,
        test_multiple_snapshots_pick_latest,
        test_build_active_single_snapshot_query_for_active_set,
        test_batch_fetch_query_count,
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
    print("All monitoring video source tests passed.")


if __name__ == "__main__":
    main()
