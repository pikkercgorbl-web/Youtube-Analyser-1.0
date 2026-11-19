"""Tests for discovered channel PostgreSQL upsert (discovery persistence fix)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.integrations.youtube.client import VideoSearchModel
from app.models.db import Base
from app.models.orm import Channel, KeywordDiscoveryHit, TargetKeyword, Video
from app.services.discovered_video_persistence import (
    _upsert_discovered_channel,
    persist_discovered_video,
)
from app.services.keyword_discovery_metrics_storage import (
    mark_hits_persisted_for_monitoring,
    persist_keyword_discovery_hits,
)

UTC = timezone.utc
NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
CHANNEL_ID = "UC8J1yxr4VDX5KbkACBhMMQA"


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _session():
    return sessionmaker(bind=_engine(), autoflush=False)()


def _video(vid: str, *, channel_id: str = CHANNEL_ID, channel_title: str = "Channel") -> VideoSearchModel:
    return VideoSearchModel(
        video_id=vid,
        channel_id=channel_id,
        channel_title=channel_title,
        title=f"Video {vid}",
        views_count=50_000,
        published_text="2 days ago",
        duration_text="10:00",
        subscribers_count=0,
    )


def test_new_channel_inserts() -> None:
    session = _session()
    _upsert_discovered_channel(
        session,
        CHANNEL_ID,
        title="Fresh Channel",
        subscribers_count=500,
        created_at=NOW,
    )
    session.commit()
    row = session.get(Channel, CHANNEL_ID)
    assert row is not None
    assert row.title == "Fresh Channel"
    assert row.subscribers_count == 500


def test_existing_channel_id_does_not_crash() -> None:
    session = _session()
    session.add(
        Channel(id=CHANNEL_ID, title="Existing", subscribers_count=100, created_at=NOW),
    )
    session.commit()
    _upsert_discovered_channel(
        session,
        CHANNEL_ID,
        title="Existing",
        subscribers_count=0,
        created_at=NOW,
    )
    session.flush()
    session.commit()
    assert session.get(Channel, CHANNEL_ID) is not None


def test_title_updates_when_incoming_non_empty() -> None:
    session = _session()
    session.add(
        Channel(id=CHANNEL_ID, title="Old Name", subscribers_count=0, created_at=NOW),
    )
    session.commit()
    _upsert_discovered_channel(
        session,
        CHANNEL_ID,
        title="New Name",
        subscribers_count=0,
        created_at=NOW,
    )
    session.commit()
    assert session.get(Channel, CHANNEL_ID).title == "New Name"


def test_subscribers_update_when_incoming_positive() -> None:
    session = _session()
    session.add(
        Channel(id=CHANNEL_ID, title="Ch", subscribers_count=10_000, created_at=NOW),
    )
    session.commit()
    _upsert_discovered_channel(
        session,
        CHANNEL_ID,
        title="Ch",
        subscribers_count=12_000,
        created_at=NOW,
    )
    session.commit()
    assert session.get(Channel, CHANNEL_ID).subscribers_count == 12_000


def test_subscribers_not_overwritten_with_zero() -> None:
    session = _session()
    session.add(
        Channel(id=CHANNEL_ID, title="Ch", subscribers_count=10_000, created_at=NOW),
    )
    session.commit()
    _upsert_discovered_channel(
        session,
        CHANNEL_ID,
        title="Ch",
        subscribers_count=0,
        created_at=NOW,
    )
    session.commit()
    assert session.get(Channel, CHANNEL_ID).subscribers_count == 10_000


def test_title_not_wiped_by_empty_incoming() -> None:
    session = _session()
    session.add(
        Channel(id=CHANNEL_ID, title="Good Title", subscribers_count=0, created_at=NOW),
    )
    session.commit()
    _upsert_discovered_channel(
        session,
        CHANNEL_ID,
        title="",
        subscribers_count=0,
        created_at=NOW,
    )
    session.commit()
    assert session.get(Channel, CHANNEL_ID).title == "Good Title"


def test_two_videos_same_channel_one_row() -> None:
    session = _session()
    v1 = _video("v1", channel_title="Ch A")
    v1.subscribers_count = 1000
    v2 = _video("v2", channel_title="Ch B")
    v2.subscribers_count = 2000
    persist_discovered_video(session, v1, discovery_keyword="k")
    persist_discovered_video(session, v2, discovery_keyword="k")
    session.flush()
    count = session.scalar(select(func.count()).select_from(Channel))
    assert count == 1
    assert session.get(Channel, CHANNEL_ID).subscribers_count == 2000


def test_discovery_path_flush_without_channels_pkey_error() -> None:
    session = _session()
    session.add(TargetKeyword(keyword="gaming"))
    session.commit()
    keyword_id = session.scalar(select(TargetKeyword.id))

    v1 = _video("d1")
    v1.subscribers_count = 800
    v2 = _video("d2")
    v2.subscribers_count = 900

    from app.services.discovery_keyword_scan import KeywordDiscoveryScanResult

    scan = KeywordDiscoveryScanResult(
        keyword="gaming",
        keyword_id=keyword_id,
        raw_candidate_count=2,
        unique_videos=[v1, v2],
        qualification_passed_count=0,
        qualification_rejected_count=2,
        explosive_hits=0,
    )
    persist_keyword_discovery_hits(
        session,
        keyword_id=keyword_id,
        discovery_run_id="discovery_test",
        discovered_at=NOW,
        scan=scan,
        cycle_video_ids_seen=set(),
        video_ids_existing_before_cycle=frozenset(),
    )
    persisted_ids: set[str] = set()
    for video in scan.unique_videos:
        persist_discovered_video(session, video, discovery_keyword="gaming")
        persisted_ids.add(video.video_id)
    mark_hits_persisted_for_monitoring(
        session,
        keyword_id=keyword_id,
        discovery_run_id="discovery_test",
        video_ids=persisted_ids,
    )
    session.commit()
    assert session.scalar(select(func.count()).select_from(Channel)) == 1
    assert session.scalar(select(func.count()).select_from(Video)) == 2
    hits = session.scalars(select(KeywordDiscoveryHit)).all()
    assert len(hits) == 2
    assert all(h.persisted_for_monitoring for h in hits)


def main() -> None:
    tests = [
        test_new_channel_inserts,
        test_existing_channel_id_does_not_crash,
        test_title_updates_when_incoming_non_empty,
        test_subscribers_update_when_incoming_positive,
        test_subscribers_not_overwritten_with_zero,
        test_title_not_wiped_by_empty_incoming,
        test_two_videos_same_channel_one_row,
        test_discovery_path_flush_without_channels_pkey_error,
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
    print("All channel upsert tests passed.")


if __name__ == "__main__":
    main()
