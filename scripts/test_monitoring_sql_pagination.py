"""Stage 1.20E.3 — SQL pagination + bounded enrichment for monitoring video list."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.models.orm import Channel, MonitoringVideoQueueEntry, Video, VideoFormat
from app.services.monitoring_api_service import build_active_monitoring_enriched, list_monitoring_videos
from app.services.monitoring_cycle import MonitoringCycleSummary
from app.services.monitoring_cycle_run_storage import persist_monitoring_cycle_run
from app.services.monitoring_queue_persist import replace_monitoring_video_queue
from app.services import video_snapshot_storage as snapshot_mod

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


def _seed_many(session: Session, count: int) -> None:
    from scripts.monitoring_test_seed_helpers import ensure_monitoring_eligible_video

    for idx in range(count):
        pub = NOW - timedelta(hours=12 + (idx % 5))
        ensure_monitoring_eligible_video(
            session,
            f"v{idx:04d}",
            channel_id=f"ch{idx:04d}",
            published_at=pub,
            views=1000 + idx,
            title=f"Video {idx}",
        )
    session.commit()


def _seed_queue(session: Session, run_id: str = "queue_run_1") -> int:
    with patch("app.services.monitoring_api_service.utc_now", return_value=NOW):
        enriched, _, _ = build_active_monitoring_enriched(session)
        replace_monitoring_video_queue(session, run_id, enriched)
    persist_monitoring_cycle_run(
        session,
        MonitoringCycleSummary(
            run_id=run_id,
            started_at=NOW - timedelta(minutes=1),
            finished_at=NOW,
            cycle_status="ok",
            loaded_video_count=len(enriched),
            eligible_video_count=len(enriched),
        ),
    )
    session.commit()
    return len(enriched)


def test_page_loads_only_page_snapshots() -> None:
    engine = _engine()
    session = sessionmaker(bind=engine)()
    _seed_many(session, 120)
    pool_size = _seed_queue(session)
    page_limit = min(50, pool_size)
    assert pool_size >= 3

    original = snapshot_mod.get_latest_snapshots_for_videos
    seen_ids: list[list[str]] = []

    def spy(db, video_ids):
        seen_ids.append(list(video_ids))
        return original(db, video_ids)

    with patch.object(snapshot_mod, "get_latest_snapshots_for_videos", side_effect=spy):
        result = list_monitoring_videos(session, limit=50, offset=0)

    assert result.queue_source == "cycle_snapshot"
    assert len(result.rows) == page_limit
    assert result.total == pool_size
    page_batch_calls = [batch for batch in seen_ids if len(batch) == page_limit]
    assert len(page_batch_calls) == 1
    assert len(page_batch_calls[0]) == page_limit


def test_no_full_enrich_on_default_path() -> None:
    engine = _engine()
    session = sessionmaker(bind=engine)()
    _seed_many(session, 80)
    _seed_queue(session)

    with patch(
        "app.services.monitoring_api_service.build_active_monitoring_enriched",
    ) as mock_enrich:
        list_monitoring_videos(session, limit=50, offset=0)
    mock_enrich.assert_not_called()


def test_live_planner_still_enriches_full_pool() -> None:
    engine = _engine()
    session = sessionmaker(bind=engine)()
    _seed_many(session, 10)
    _seed_queue(session)

    with patch(
        "app.services.monitoring_api_service.build_active_monitoring_enriched",
        wraps=build_active_monitoring_enriched,
    ) as mock_enrich:
        list_monitoring_videos(session, limit=50, live_planner=True)
    mock_enrich.assert_called_once()


def test_missing_queue_unavailable() -> None:
    engine = _engine()
    session = sessionmaker(bind=engine)()
    _seed_many(session, 5)
    result = list_monitoring_videos(session, limit=50)
    assert result.queue_source == "unavailable"
    assert result.total == 0
    assert result.rows == []


def test_tier_and_search_filters_sql() -> None:
    engine = _engine()
    session = sessionmaker(bind=engine)()
    _seed_many(session, 20)
    _seed_queue(session)
    result = list_monitoring_videos(session, tier="A", keyword="Video 1", limit=200)
    for row in result.rows:
        assert row.tier == "A"
        assert "Video 1" in (row.title or "")


def test_total_count_matches_filtered_rows() -> None:
    engine = _engine()
    session = sessionmaker(bind=engine)()
    _seed_many(session, 15)
    _seed_queue(session)
    all_rows = list_monitoring_videos(session, limit=200).total
    tier_a = list_monitoring_videos(session, tier="A", limit=200).total
    assert tier_a <= all_rows


def test_priority_rank_persisted() -> None:
    engine = _engine()
    session = sessionmaker(bind=engine)()
    _seed_many(session, 3)
    _seed_queue(session)
    ranks = session.scalars(
        select(MonitoringVideoQueueEntry.priority_rank)
        .where(MonitoringVideoQueueEntry.run_id == "queue_run_1")
        .order_by(MonitoringVideoQueueEntry.priority_rank),
    ).all()
    assert ranks == [0, 1, 2]


def main() -> None:
    tests = [
        test_page_loads_only_page_snapshots,
        test_no_full_enrich_on_default_path,
        test_live_planner_still_enriches_full_pool,
        test_missing_queue_unavailable,
        test_tier_and_search_filters_sql,
        test_total_count_matches_filtered_rows,
        test_priority_rank_persisted,
    ]
    for test in tests:
        test()
        print(f"OK {test.__name__}")


if __name__ == "__main__":
    main()
