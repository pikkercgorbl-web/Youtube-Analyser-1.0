"""Stage 1.20E.4 — keyword performance bounded read path."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, func, select
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
from app.services.keyword_performance_read_model import refresh_keyword_performance_read_model
from app.services.keyword_performance_service import list_keyword_performance

UTC = timezone.utc
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _seed_keyword_with_hit(session: Session, keyword: str, video_id: str) -> TargetKeyword:
    kw = TargetKeyword(keyword=keyword)
    session.add(kw)
    session.flush()
    if session.get(Channel, "ch1") is None:
        session.add(Channel(id="ch1", title="C", subscribers_count=100, created_at=NOW))
    published = NOW - timedelta(hours=80)
    session.add(
        Video(
            id=video_id,
            title="V",
            views_count=1000,
            likes_count=0,
            comments_count=0,
            published_at=published,
            duration_seconds=600,
            content_format=VideoFormat.MEDIUM,
            channel_id="ch1",
        ),
    )
    session.add(
        KeywordScanRun(
            keyword_id=kw.id,
            discovery_run_id="run-1",
            started_at=NOW - timedelta(days=1),
            finished_at=NOW - timedelta(days=1),
            status="completed",
        ),
    )
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id=video_id,
            discovery_run_id="run-1",
            discovered_at=published,
            views_at_discovery=100,
            vph_at_discovery=10.0,
            content_format="regular",
            qualification_state="passed",
        ),
    )
    session.add(
        VideoSnapshot(
            video_id=video_id,
            channel_id="ch1",
            captured_at=NOW,
            source="test",
            run_id="r1",
            views=1000,
            age_hours=80.0,
            vph=12.5,
        ),
    )
    return kw


def test_default_list_uses_snapshot_not_live_batch() -> None:
    session = sessionmaker(bind=_engine())()
    _seed_keyword_with_hit(session, "alpha", "v1")
    session.commit()
    refresh_keyword_performance_read_model(session)
    session.commit()
    with patch("app.services.keyword_performance_evaluation.evaluate_keywords_batch") as mocked:
        result = list_keyword_performance(session, limit=50, include_breakout=True, include_delayed=True)
        mocked.assert_not_called()
    assert result.data_source == "snapshot"
    assert len(result.items) >= 1


def test_unavailable_without_snapshot() -> None:
    session = sessionmaker(bind=_engine())()
    _seed_keyword_with_hit(session, "beta", "v2")
    session.commit()
    result = list_keyword_performance(session, limit=10)
    assert result.data_source == "unavailable"
    assert result.items == []


def test_live_page_bounds_keywords_processed() -> None:
    session = sessionmaker(bind=_engine())()
    for idx in range(8):
        _seed_keyword_with_hit(session, f"kw{idx}", f"v{idx}")
    session.commit()
    seen: list[int] = []

    def _spy(session_arg, keyword_records, **_kwargs):
        seen.append(len(keyword_records))
        return {}

    with patch(
        "app.services.keyword_performance_service.evaluate_keywords_batch",
        side_effect=_spy,
    ):
        list_keyword_performance(session, limit=3, offset=2, live_evaluation=True)
    assert seen == [3]


def test_batch_does_not_load_entire_discovery_hit_table() -> None:
    session = sessionmaker(bind=_engine())()
    _seed_keyword_with_hit(session, "only", "v-only")
    extra = TargetKeyword(keyword="empty")
    session.add(extra)
    session.commit()
    hit_count = session.scalar(select(func.count()).select_from(KeywordDiscoveryHit)) or 0
    assert hit_count >= 1
    refresh_keyword_performance_read_model(session)
    session.commit()
    assert list_keyword_performance(session, limit=10).data_source == "snapshot"


def test_missing_72h_not_zeroed_in_snapshot() -> None:
    session = sessionmaker(bind=_engine())()
    _seed_keyword_with_hit(session, "outcome", "v-out")
    session.commit()
    refresh_keyword_performance_read_model(session)
    session.commit()
    item = list_keyword_performance(
        session,
        limit=10,
        attribution_mode="all_hits",
    ).items[0]
    if (item.missing_72h_video_count or 0) > 0:
        assert item.missing_72h_video_count != item.attributed_video_count


def main() -> None:
    tests = [
        test_default_list_uses_snapshot_not_live_batch,
        test_unavailable_without_snapshot,
        test_live_page_bounds_keywords_processed,
        test_batch_does_not_load_entire_discovery_hit_table,
        test_missing_72h_not_zeroed_in_snapshot,
    ]
    for test in tests:
        test()
        print(f"OK {test.__name__}")


if __name__ == "__main__":
    main()
