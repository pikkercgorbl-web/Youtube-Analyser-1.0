"""SavedFamily topic video search watch tests."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.orm  # noqa: F401
from app.integrations.youtube.client import VideoSearchModel
from app.models.db import Base
from app.models.orm import (
    SavedFamily,
    SavedFamilyTopicFinding,
    SavedFamilyTopicWatch,
    SavedVideoSimilarWatch,
)
from app.services.saved_research import archive_family, restore_family
from app.services.saved_video_similar_search import SimilarQuerySearchResult
from app.services.saved_family_topic_watch import (
    WATCH_ACTIVE,
    WATCH_PAUSED,
    confirm_family_topic_watch_queries,
    execute_family_topic_watch_scan,
    get_or_create_family_topic_watch_draft,
    pause_family_topic_watch,
    resume_family_topic_watch,
)
from app.services.saved_library_watch_batch import count_active_library_watches, run_library_watch_batch_for_discovery_cycle

UTC = timezone.utc
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


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


def _seed_family(session: Session) -> SavedFamily:
    frozen = {
        "family": {"label": "Test topic family", "family_key": "pf_test"},
        "member_patterns": [{"pattern_key": "p1", "label": "widget teardown trend"}],
        "keyword_ids": [],
        "video_ids": ["member-vid-1"],
    }
    row = SavedFamily(
        family_key="pf_test",
        saved_at=NOW,
        frozen_label="Test topic family",
        frozen_kind="pattern_family",
        frozen_payload_json=json.dumps(frozen),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def test_confirm_and_dedupe_findings():
    session = _session()
    family = _seed_family(session)
    watch = get_or_create_family_topic_watch_draft(session, saved_family_id=family.id)
    assert watch.suggested_queries_json
    confirm_family_topic_watch_queries(
        session,
        saved_family_id=family.id,
        queries=["widget teardown", "widget teardown"],
    )
    session.commit()

    mock_video = VideoSearchModel(
        video_id="found-1",
        title="New widget teardown 2026",
        channel_id="ch1",
        channel_title="Tech Channel",
        views_count=5000,
        published_text="2 days ago",
        duration_text="10:00",
        thumbnail_url="https://example.com/t.jpg",
        is_short=False,
        is_live=False,
    )

    async def fake_search(query: str, *, exclude_video_ids):
        return SimilarQuerySearchResult(query=query, videos=[mock_video])

    with patch(
        "app.services.saved_family_topic_watch.search_similar_videos_for_query",
        new=AsyncMock(side_effect=fake_search),
    ):
        execute_family_topic_watch_scan(session, saved_family_id=family.id, trigger="manual")
        session.commit()
        execute_family_topic_watch_scan(session, saved_family_id=family.id, trigger="manual")
        session.commit()

    count = session.scalar(
        select(SavedFamilyTopicFinding).where(SavedFamilyTopicFinding.saved_family_id == family.id),
    )
    rows = session.scalars(
        select(SavedFamilyTopicFinding).where(SavedFamilyTopicFinding.saved_family_id == family.id),
    ).all()
    assert len(rows) == 1
    print("  dedupe findings OK")


def test_archive_pauses_restore_stays_paused():
    session = _session()
    family = _seed_family(session)
    confirm_family_topic_watch_queries(session, saved_family_id=family.id, queries=["widget teardown"])
    session.commit()
    archive_family(session, family.id)
    session.commit()
    watch = session.get(SavedFamilyTopicWatch, family.id)
    assert watch is not None and watch.status == WATCH_PAUSED
    restore_family(session, family.id)
    session.commit()
    watch = session.get(SavedFamilyTopicWatch, family.id)
    assert watch is not None and watch.status == WATCH_PAUSED
    print("  archive pause / restore stays paused OK")


def test_shared_active_limit():
    session = _session()
    family = _seed_family(session)
    confirm_family_topic_watch_queries(session, saved_family_id=family.id, queries=["one query"])
    session.commit()
    assert count_active_library_watches(session) == 1
    print("  shared active count OK")


def main() -> None:
    test_confirm_and_dedupe_findings()
    test_archive_pauses_restore_stays_paused()
    test_shared_active_limit()
    print("test_saved_family_topic_watch: OK")


if __name__ == "__main__":
    main()
