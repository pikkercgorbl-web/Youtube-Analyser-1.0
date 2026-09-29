"""Tests for keyword performance metrics (Stage 1.16A)."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.integrations.youtube.client import VideoSearchModel
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
from app.services.discovery_cycle import DiscoveryCycleConfig, run_discovery_cycle_async
from app.services.discovery_keyword_scan import KeywordDiscoveryScanResult
from app.services.keyword_performance_service import get_keyword_performance, list_keyword_performance
from app.services.radar_candidate import QUALIFICATION_PASSED, QUALIFICATION_REJECTED, RadarCandidate

UTC = timezone.utc


def _engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


def _session():
    return sessionmaker(bind=_engine())()


def _now() -> datetime:
    return datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


def _video(vid: str, *, channel_id: str = "ch1", views: int = 50_000) -> VideoSearchModel:
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
    candidates = [
        RadarCandidate(
            video_id=v.video_id,
            channel_id=v.channel_id,
            keyword=keyword,
            discovery_source="innertube",
            discovered_at=_now(),
            video_title=v.title,
            channel_title=v.channel_title,
            qualification_state=kwargs.get("qualification_state", QUALIFICATION_REJECTED),
        )
        for v in videos
    ]
    return KeywordDiscoveryScanResult(
        keyword=keyword,
        keyword_id=keyword_id,
        raw_candidate_count=kwargs.get("raw_candidate_count", len(videos)),
        unique_videos=videos,
        candidates=candidates,
        qualification_passed_count=kwargs.get("qualification_passed_count", 0),
        qualification_rejected_count=kwargs.get("qualification_rejected_count", len(videos)),
        error=kwargs.get("error"),
    )


def test_zero_result_scan_persisted() -> None:
    session = _session()
    kw = TargetKeyword(keyword="empty")
    session.add(kw)
    session.commit()

    async def fake_scan(session, *, keyword, keyword_id, **kwargs):
        return _scan_result(keyword, keyword_id, [])

    with patch("app.services.discovery_cycle.scan_keyword_for_discovery", side_effect=fake_scan):
        asyncio.run(run_discovery_cycle_async(session, config=DiscoveryCycleConfig(keyword_batch_size=1)))

    runs = session.scalars(select(KeywordScanRun)).all()
    assert len(runs) == 1
    assert runs[0].unique_candidates == 0
    assert runs[0].status == "ok"
    metrics = get_keyword_performance(session, kw.id)
    assert metrics is not None
    assert metrics.scan_count == 1


def test_failed_scan_persisted() -> None:
    session = _session()
    kw = TargetKeyword(keyword="fail")
    session.add(kw)
    session.commit()

    async def fake_scan(session, *, keyword, keyword_id, **kwargs):
        return _scan_result(keyword, keyword_id, [], error="network")

    with patch("app.services.discovery_cycle.scan_keyword_for_discovery", side_effect=fake_scan):
        asyncio.run(run_discovery_cycle_async(session, config=DiscoveryCycleConfig(keyword_batch_size=1)))

    run = session.scalar(select(KeywordScanRun))
    assert run is not None
    assert run.status == "failed"
    assert run.error_summary == "network"


def test_discovery_hit_persisted() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k1")
    session.add(kw)
    session.commit()

    async def fake_scan(session, *, keyword, keyword_id, **kwargs):
        return _scan_result(keyword, keyword_id, [_video("v1")])

    with patch("app.services.discovery_cycle.scan_keyword_for_discovery", side_effect=fake_scan):
        asyncio.run(run_discovery_cycle_async(session, config=DiscoveryCycleConfig(keyword_batch_size=1)))

    hits = session.scalars(select(KeywordDiscoveryHit)).all()
    assert len(hits) == 1
    assert hits[0].video_id == "v1"
    assert hits[0].persisted_for_monitoring is True


def test_two_keywords_two_hits_one_video_row() -> None:
    session = _session()
    session.add_all([TargetKeyword(keyword="a"), TargetKeyword(keyword="b")])
    session.commit()

    async def fake_scan(session, *, keyword, keyword_id, **kwargs):
        return _scan_result(keyword, keyword_id, [_video("shared")])

    with patch("app.services.discovery_cycle.scan_keyword_for_discovery", side_effect=fake_scan):
        asyncio.run(run_discovery_cycle_async(session, config=DiscoveryCycleConfig(keyword_batch_size=2)))

    hits = session.scalars(select(KeywordDiscoveryHit)).all()
    assert len(hits) == 2
    assert session.scalar(select(func.count()).select_from(Video)) == 1


def test_dry_run_writes_nothing() -> None:
    session = _session()
    session.add(TargetKeyword(keyword="dry"))
    session.commit()

    async def fake_scan(session, *, keyword, keyword_id, **kwargs):
        return _scan_result(keyword, keyword_id, [_video("v1")])

    with patch("app.services.discovery_cycle.scan_keyword_for_discovery", side_effect=fake_scan):
        asyncio.run(
            run_discovery_cycle_async(
                session,
                config=DiscoveryCycleConfig(keyword_batch_size=1),
                dry_run=True,
            ),
        )
    assert session.scalar(select(func.count()).select_from(KeywordScanRun)) == 0
    assert session.scalar(select(func.count()).select_from(KeywordDiscoveryHit)) == 0


def test_unique_channel_ignores_null() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k")
    session.add(kw)
    session.commit()
    run_id = "discovery_test_run"
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="v1",
            discovery_run_id=run_id,
            discovered_at=_now(),
            channel_id="ch1",
            content_format="regular",
            qualification_state="rejected",
        ),
    )
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="v2",
            discovery_run_id=run_id,
            discovered_at=_now(),
            channel_id=None,
            content_format="regular",
            qualification_state="rejected",
        ),
    )
    session.add(
        KeywordScanRun(
            keyword_id=kw.id,
            discovery_run_id=run_id,
            started_at=_now(),
            finished_at=_now(),
            status="ok",
        ),
    )
    session.commit()
    metrics = get_keyword_performance(session, kw.id)
    assert metrics.unique_channel_count == 1


def test_cross_keyword_duplicate_flag() -> None:
    session = _session()
    k1, k2 = TargetKeyword(keyword="a"), TargetKeyword(keyword="b")
    session.add_all([k1, k2])
    session.commit()
    run_id = "discovery_dup"

    async def fake_scan(session, *, keyword, keyword_id, **kwargs):
        return _scan_result(keyword, keyword_id, [_video("shared")])

    with patch("app.services.discovery_cycle.scan_keyword_for_discovery", side_effect=fake_scan):
        asyncio.run(run_discovery_cycle_async(session, config=DiscoveryCycleConfig(keyword_batch_size=2)))

    hits = session.scalars(select(KeywordDiscoveryHit).order_by(KeywordDiscoveryHit.keyword_id)).all()
    assert hits[0].was_cross_keyword_duplicate is False
    assert hits[1].was_cross_keyword_duplicate is True
    assert hits[0].video_existed_before_discovery is False
    assert hits[1].video_existed_before_discovery is False
    assert session.scalar(select(func.count()).select_from(Video)) == 1
    metrics = get_keyword_performance(session, k2.id)
    assert metrics.cross_keyword_duplicate_count == 1
    assert metrics.already_known_video_count == 0


def test_new_video_two_keywords_both_existed_before_false() -> None:
    """Regression: pre-cycle snapshot must not grow after keyword A inserts Video."""
    session = _session()
    session.add_all([TargetKeyword(keyword="kw_a"), TargetKeyword(keyword="kw_b")])
    session.commit()
    call_order: list[str] = []

    async def fake_scan(session, *, keyword, keyword_id, **kwargs):
        call_order.append(keyword)
        return _scan_result(keyword, keyword_id, [_video("brand_new")])

    with patch("app.services.discovery_cycle.scan_keyword_for_discovery", side_effect=fake_scan):
        asyncio.run(run_discovery_cycle_async(session, config=DiscoveryCycleConfig(keyword_batch_size=2)))

    hits = session.scalars(
        select(KeywordDiscoveryHit).order_by(KeywordDiscoveryHit.keyword_id.asc()),
    ).all()
    assert len(hits) == 2
    assert all(not h.video_existed_before_discovery for h in hits)
    assert hits[0].was_cross_keyword_duplicate is False
    assert hits[1].was_cross_keyword_duplicate is True
    assert session.scalar(select(func.count()).select_from(Video)) == 1


def test_already_known_video_flag() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k")
    session.add(kw)
    session.add(
        Channel(id="ch1", title="C", subscribers_count=1, created_at=_now()),
    )
    session.add(
        Video(
            id="old",
            title="Old",
            views_count=100,
            likes_count=0,
            comments_count=0,
            published_at=_now() - timedelta(days=3),
            duration_seconds=600,
            content_format=VideoFormat.MEDIUM,
            channel_id="ch1",
        ),
    )
    session.commit()

    async def fake_scan(session, *, keyword, keyword_id, **kwargs):
        return _scan_result(keyword, keyword_id, [_video("old")])

    with patch("app.services.discovery_cycle.scan_keyword_for_discovery", side_effect=fake_scan):
        asyncio.run(run_discovery_cycle_async(session, config=DiscoveryCycleConfig(keyword_batch_size=1)))

    hit = session.scalar(select(KeywordDiscoveryHit))
    assert hit.video_existed_before_discovery is True
    metrics = get_keyword_performance(session, kw.id)
    assert metrics.already_known_video_count == 1


def test_qualification_counts() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k")
    session.add(kw)
    session.commit()
    v1, v2 = _video("p"), _video("r")
    candidates = [
        RadarCandidate(
            video_id="p",
            channel_id="ch1",
            keyword="k",
            discovery_source="innertube",
            discovered_at=_now(),
            video_title="p",
            channel_title="C",
            qualification_state=QUALIFICATION_PASSED,
        ),
        RadarCandidate(
            video_id="r",
            channel_id="ch1",
            keyword="k",
            discovery_source="innertube",
            discovered_at=_now(),
            video_title="r",
            channel_title="C",
            qualification_state=QUALIFICATION_REJECTED,
        ),
    ]
    result = KeywordDiscoveryScanResult(
        keyword="k",
        keyword_id=kw.id,
        raw_candidate_count=2,
        unique_videos=[v1, v2],
        candidates=candidates,
        qualification_passed_count=1,
        qualification_rejected_count=1,
    )

    async def fake_scan(session, *, keyword, keyword_id, **kwargs):
        return result

    with patch("app.services.discovery_cycle.scan_keyword_for_discovery", side_effect=fake_scan):
        asyncio.run(run_discovery_cycle_async(session, config=DiscoveryCycleConfig(keyword_batch_size=1)))

    metrics = get_keyword_performance(session, kw.id)
    assert metrics.qualification_passed_count == 1
    assert metrics.qualification_rejected_count == 1


def test_snapshot_coverage_by_age() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k")
    session.add(kw)
    session.flush()
    session.add(Channel(id="ch1", title="C", subscribers_count=1, created_at=_now()))
    session.add(
        Video(
            id="v1",
            title="V",
            views_count=1000,
            likes_count=0,
            comments_count=0,
            published_at=_now() - timedelta(hours=30),
            duration_seconds=600,
            content_format=VideoFormat.MEDIUM,
            channel_id="ch1",
        ),
    )
    run_id = "discovery_snap"
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="v1",
            discovery_run_id=run_id,
            discovered_at=_now(),
            channel_id="ch1",
            content_format="regular",
            qualification_state="rejected",
            persisted_for_monitoring=True,
        ),
    )
    session.add(
        KeywordScanRun(
            keyword_id=kw.id,
            discovery_run_id=run_id,
            started_at=_now(),
            finished_at=_now(),
            status="ok",
        ),
    )
    session.add(
        VideoSnapshot(
            video_id="v1",
            channel_id="ch1",
            captured_at=_now(),
            published_at=_now() - timedelta(hours=30),
            age_hours=72.0,
            views=2000,
            source="test",
            run_id="mon",
        ),
    )
    session.commit()
    metrics = get_keyword_performance(session, kw.id)
    assert metrics.videos_with_snapshot_count == 1
    assert metrics.videos_with_snapshot_24h_count == 1
    assert metrics.videos_with_snapshot_48h_count == 1
    assert metrics.videos_with_snapshot_72h_count == 1
    assert metrics.t24_outcome_count == 0
    assert metrics.confirmed_breakout_count == 0


def test_no_keyword_score_field() -> None:
    metrics = get_keyword_performance(_session(), 999)
    assert metrics is None
    fields = KeywordPerformanceMetrics = __import__(
        "app.services.keyword_performance_service",
        fromlist=["KeywordPerformanceMetrics"],
    ).KeywordPerformanceMetrics
    assert "keyword_score" not in fields.__dataclass_fields__


def test_time_window_filter() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k")
    session.add(kw)
    session.commit()
    old = _now() - timedelta(days=40)
    recent = _now()
    for run_id, at in (("old_run", old), ("new_run", recent)):
        session.add(
            KeywordScanRun(
                keyword_id=kw.id,
                discovery_run_id=run_id,
                started_at=at,
                finished_at=at,
                status="ok",
            ),
        )
        session.add(
            KeywordDiscoveryHit(
                keyword_id=kw.id,
                video_id=f"v-{run_id}",
                discovery_run_id=run_id,
                discovered_at=at,
                channel_id="ch1",
                content_format="regular",
                qualification_state="rejected",
            ),
        )
    session.commit()
    metrics = get_keyword_performance(
        session,
        kw.id,
        from_timestamp=_now() - timedelta(days=7),
    )
    assert metrics.scan_count == 1
    assert metrics.discovery_hit_count == 1


def test_efficiency_metrics() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k")
    session.add(kw)
    session.commit()
    run_id = "eff"
    session.add(
        KeywordScanRun(
            keyword_id=kw.id,
            discovery_run_id=run_id,
            started_at=_now(),
            finished_at=_now(),
            status="ok",
            persisted_videos=2,
        ),
    )
    for vid in ("v1", "v2"):
        session.add(
            KeywordDiscoveryHit(
                keyword_id=kw.id,
                video_id=vid,
                discovery_run_id=run_id,
                discovered_at=_now(),
                channel_id="ch1",
                content_format="regular",
                qualification_state="passed",
                persisted_for_monitoring=True,
            ),
        )
    session.commit()
    metrics = get_keyword_performance(session, kw.id)
    assert metrics.videos_per_scan == 2.0
    assert metrics.persisted_videos_per_scan == 2.0
    assert metrics.qualification_passed_per_scan == 2.0


def test_list_keyword_performance() -> None:
    session = _session()
    session.add(TargetKeyword(keyword="a"))
    session.commit()
    result = list_keyword_performance(session, limit=10)
    assert len(result.items) == 1
    assert result.context.ranking_version == "breakout_v1"


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
    _run_script("test_keyword_performance_evaluation.py")
    _run_script("test_discovery_cycle.py")
    _run_script("test_discovery_worker.py")
    _run_script("test_monitoring_worker.py")
    _run_script("test_monitoring_api.py")


def main() -> None:
    tests = [
        test_zero_result_scan_persisted,
        test_failed_scan_persisted,
        test_discovery_hit_persisted,
        test_two_keywords_two_hits_one_video_row,
        test_dry_run_writes_nothing,
        test_unique_channel_ignores_null,
        test_cross_keyword_duplicate_flag,
        test_new_video_two_keywords_both_existed_before_false,
        test_already_known_video_flag,
        test_qualification_counts,
        test_snapshot_coverage_by_age,
        test_no_keyword_score_field,
        test_time_window_filter,
        test_efficiency_metrics,
        test_list_keyword_performance,
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
    print("All keyword performance tests passed.")


if __name__ == "__main__":
    main()
