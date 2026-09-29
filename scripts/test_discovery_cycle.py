"""Tests for automatic discovery cycle (Stage 1.15A)."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.integrations.youtube.client import VideoSearchModel
from app.models.db import Base
from app.models.orm import Channel, TargetKeyword, Video, VideoFormat
from app.services.discovered_video_persistence import persist_discovered_video
from app.services.discovery_cycle import (
    DiscoveryCycleConfig,
    generate_discovery_run_id,
    run_discovery_cycle_async,
)
from app.services.discovery_keyword_scan import KeywordDiscoveryScanResult
from app.services.discovery_keyword_selection import select_discovery_keywords
from app.services.monitoring_video_source import load_monitored_video_states

UTC = timezone.utc


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _session():
    return sessionmaker(bind=_engine())()


def _video(vid: str, *, views: int = 60_000, channel_id: str = "ch1") -> VideoSearchModel:
    return VideoSearchModel(
        video_id=vid,
        channel_id=channel_id,
        channel_title="Channel",
        title=f"Video {vid}",
        views_count=views,
        published_text="2 days ago",
        duration_text="10:00",
    )


def _scan_result(keyword: str, keyword_id: int, videos: list[VideoSearchModel], **kwargs) -> KeywordDiscoveryScanResult:
    return KeywordDiscoveryScanResult(
        keyword=keyword,
        keyword_id=keyword_id,
        raw_candidate_count=len(videos),
        unique_videos=videos,
        qualification_passed_count=kwargs.get("qualification_passed_count", 0),
        qualification_rejected_count=kwargs.get("qualification_rejected_count", len(videos)),
        explosive_hits=kwargs.get("explosive_hits", 0),
        error=kwargs.get("error"),
    )


def test_select_active_batch_ordering() -> None:
    session = _session()
    now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    a = TargetKeyword(
        keyword="a",
        last_checked=now,
        next_scan_at=now + timedelta(hours=5),
        lifecycle_status="active",
    )
    b = TargetKeyword(
        keyword="b",
        last_checked=None,
        next_scan_at=now - timedelta(hours=10),
        lifecycle_status="active",
    )
    c = TargetKeyword(
        keyword="c",
        last_checked=now,
        next_scan_at=now + timedelta(hours=5),
        lifecycle_status="active",
    )
    session.add_all([a, b, c])
    session.commit()
    batch = select_discovery_keywords(session, batch_size=2, now=now)
    keywords = [row.keyword for row in batch]
    assert keywords == ["b"]


def test_batch_size_respected() -> None:
    session = _session()
    for i in range(10):
        session.add(TargetKeyword(keyword=f"k{i}"))
    session.commit()
    assert len(select_discovery_keywords(session, batch_size=5)) == 5


def test_persist_rejected_qualification_video_still_stored() -> None:
    session = _session()
    video = _video("v1")
    result = persist_discovered_video(session, video, discovery_keyword="gaming")
    session.commit()
    assert result.outcome == "inserted"
    row = session.get(Video, "v1")
    assert row is not None
    assert row.topic == "gaming"


def test_null_fields_do_not_wipe_existing() -> None:
    session = _session()
    session.add(
        Channel(id="ch1", title="Old Channel", subscribers_count=1000, created_at=datetime.now(UTC)),
    )
    session.add(
        Video(
            id="v1",
            title="Keep title",
            views_count=999,
            likes_count=0,
            comments_count=0,
            published_at=datetime(2026, 9, 10, tzinfo=UTC),
            duration_seconds=600,
            content_format=VideoFormat.MEDIUM,
            channel_id="ch1",
        ),
    )
    session.commit()
    sparse = VideoSearchModel(
        video_id="v1",
        channel_id="ch1",
        title="",
        views_count=0,
        published_text="3 days ago",
    )
    persist_discovered_video(session, sparse, discovery_keyword="x")
    session.commit()
    row = session.get(Video, "v1")
    assert row.title == "Keep title"
    assert row.views_count == 999


def test_short_live_skipped_for_persistence() -> None:
    session = _session()
    short = _video("s1")
    short.is_short = True
    assert persist_discovered_video(session, short, discovery_keyword="k").outcome == "skipped_short"
    live = _video("l1")
    live.is_live = True
    assert persist_discovered_video(session, live, discovery_keyword="k").outcome == "skipped_live"


async def _run_cycle(session, **kwargs):
    return await run_discovery_cycle_async(session, **kwargs)


def test_cycle_deduplicates_across_keywords() -> None:
    session = _session()
    session.add_all([TargetKeyword(keyword="k1"), TargetKeyword(keyword="k2")])
    session.commit()

    async def fake_scan(session, *, keyword, keyword_id, **kwargs):
        return _scan_result(keyword, keyword_id, [_video("shared")])

    with patch("app.services.discovery_cycle.scan_keyword_for_discovery", side_effect=fake_scan):
        import asyncio

        outcome = asyncio.run(
            run_discovery_cycle_async(session, config=DiscoveryCycleConfig(keyword_batch_size=2)),
        )
    assert outcome.summary.persisted_video_count == 1
    assert outcome.summary.duplicate_occurrence_count == 1


def test_partial_status_one_keyword_fails() -> None:
    session = _session()
    session.add_all([TargetKeyword(keyword="ok"), TargetKeyword(keyword="bad")])
    session.commit()

    async def fake_scan(session, *, keyword, keyword_id, **kwargs):
        if keyword == "bad":
            return _scan_result(keyword, keyword_id, [], error="boom")
        return _scan_result(keyword, keyword_id, [_video("v1")])

    with patch("app.services.discovery_cycle.scan_keyword_for_discovery", side_effect=fake_scan):
        import asyncio

        outcome = asyncio.run(run_discovery_cycle_async(session, config=DiscoveryCycleConfig(keyword_batch_size=2)))
    assert outcome.summary.cycle_status == "partial"
    assert outcome.summary.failed_keyword_count == 1


def test_all_keywords_fail() -> None:
    session = _session()
    session.add(TargetKeyword(keyword="bad"))
    session.commit()

    async def fake_scan(session, *, keyword, keyword_id, **kwargs):
        return _scan_result(keyword, keyword_id, [], error="fail")

    with patch("app.services.discovery_cycle.scan_keyword_for_discovery", side_effect=fake_scan):
        import asyncio

        outcome = asyncio.run(run_discovery_cycle_async(session))
    assert outcome.summary.cycle_status == "failed"


def test_dry_run_no_persist_no_last_checked() -> None:
    session = _session()
    session.add(TargetKeyword(keyword="k1"))
    session.commit()

    async def fake_scan(session, *, keyword, keyword_id, **kwargs):
        return _scan_result(keyword, keyword_id, [_video("v1")])

    with patch("app.services.discovery_cycle.scan_keyword_for_discovery", side_effect=fake_scan):
        import asyncio

        outcome = asyncio.run(run_discovery_cycle_async(session, dry_run=True))
    assert outcome.summary.cycle_status == "dry_run"
    assert session.get(Video, "v1") is None
    row = session.scalar(select(TargetKeyword).where(TargetKeyword.keyword == "k1"))
    assert row is not None
    assert row.last_checked is None


def test_run_id_format() -> None:
    assert generate_discovery_run_id(now=datetime(2026, 9, 15, 12, 0, tzinfo=UTC)).startswith(
        "discovery_20260915T120000Z_",
    )


def test_monitoring_loads_persisted_video() -> None:
    session = _session()
    persist_discovered_video(session, _video("mon1", views=5000), discovery_keyword="fitness")
    session.commit()
    states = load_monitored_video_states(session, now=datetime(2026, 9, 15, 12, 0, tzinfo=UTC))
    assert any(s.video_id == "mon1" for s in states)


def test_dry_run_skips_explosive_registration_flag() -> None:
    session = _session()
    session.add(TargetKeyword(keyword="k1"))
    session.commit()
    captured: list[bool] = []

    async def fake_scan(session, *, keyword, keyword_id, register_explosive_channels, **kwargs):
        captured.append(register_explosive_channels)
        return _scan_result(keyword, keyword_id, [_video("v1")])

    with patch("app.services.discovery_cycle.scan_keyword_for_discovery", side_effect=fake_scan):
        import asyncio

        asyncio.run(run_discovery_cycle_async(session, dry_run=True))
    assert captured == [False]


def test_frozen_stage110_not_referenced() -> None:
    text = (ROOT / "app" / "services" / "discovery_cycle.py").read_text(encoding="utf-8")
    assert "stage110" not in text.lower()


def _run_script(name: str) -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / name)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)


def test_regressions() -> None:
    _run_script("test_monitoring_worker.py")
    _run_script("test_monitoring_api.py")


def main() -> None:
    tests = [
        test_select_active_batch_ordering,
        test_batch_size_respected,
        test_persist_rejected_qualification_video_still_stored,
        test_null_fields_do_not_wipe_existing,
        test_short_live_skipped_for_persistence,
        test_cycle_deduplicates_across_keywords,
        test_partial_status_one_keyword_fails,
        test_all_keywords_fail,
        test_dry_run_no_persist_no_last_checked,
        test_run_id_format,
        test_monitoring_loads_persisted_video,
        test_dry_run_skips_explosive_registration_flag,
        test_frozen_stage110_not_referenced,
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
    print("All discovery cycle tests passed.")


if __name__ == "__main__":
    main()
