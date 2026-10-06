"""Discovery hot-path optimizations (Stage 1.20E.6)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.integrations.youtube.client import VideoSearchModel
from app.models.db import Base
from app.models.orm import Channel, TargetKeyword, Video
from app.services.discovered_video_batch import batch_persist_discovered_videos
from app.services.discovery_cycle import DiscoveryCycleConfig, run_discovery_cycle_async
from app.services.discovery_keyword_scan import KeywordDiscoveryScanResult
from app.services.explosive_channels_service import ExplosiveChannelsService
from app.services.radar_qualification_context import load_radar_qualification_context


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _session():
    return sessionmaker(bind=_engine())()


def _video(
    vid: str,
    *,
    views: int = 60_000,
    channel_id: str = "ch-a",
    subs: int = 0,
) -> VideoSearchModel:
    return VideoSearchModel(
        video_id=vid,
        channel_id=channel_id,
        channel_title="Channel A",
        title=f"Title {vid}",
        views_count=views,
        subscribers_count=subs,
        published_text="2 days ago",
        duration_text="10:00",
    )


def test_settings_loaded_once_per_scan_via_context() -> None:
    session = _session()
    ctx = load_radar_qualification_context(session, upload_period="month")
    assert ctx.thresholds.min_views > 0
    assert ctx.upload_period == "month"

    service = ExplosiveChannelsService()
    get_settings = MagicMock(wraps=service._get_or_create_settings)

    with patch.object(service, "_get_or_create_settings", get_settings):
        asyncio.run(
            service.process_radar_videos(
                session,
                [_video("v1", subs=10_000)],
                qualification_context=ctx,
                register_channels=False,
                collect_video_outcomes=True,
            ),
        )
        asyncio.run(
            service.process_radar_videos(
                session,
                [_video("v2", subs=10_000)],
                qualification_context=ctx,
                register_channels=False,
                collect_video_outcomes=True,
            ),
        )
    get_settings.assert_not_called()


def test_db_subscribers_prevent_homepage_fetch() -> None:
    session = _session()
    session.add(
        Channel(
            id="ch-db",
            title="DB Channel",
            subscribers_count=50_000,
            created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        ),
    )
    session.commit()
    ctx = load_radar_qualification_context(session)
    service = ExplosiveChannelsService()
    fetch = AsyncMock(return_value=99_000)

    with patch(
        "app.services.explosive_channels_service.fetch_channel_subscribers_from_homepage",
        fetch,
    ):
        result = asyncio.run(
            service.process_radar_videos(
                session,
                [_video("v1", channel_id="ch-db", subs=0)],
                qualification_context=ctx,
                register_channels=False,
                collect_video_outcomes=True,
            ),
        )
    fetch.assert_not_called()
    assert result.subscriber_fetch_count == 0


def test_repeated_channel_videos_single_homepage_fetch() -> None:
    session = _session()
    ctx = load_radar_qualification_context(session)
    service = ExplosiveChannelsService()
    cache: dict[str, int | None] = {}
    fetch = AsyncMock(return_value=40_000)

    videos = [
        _video("v1", channel_id="ch-shared", subs=0),
        _video("v2", channel_id="ch-shared", subs=0),
    ]
    with patch(
        "app.services.explosive_channels_service.fetch_channel_subscribers_from_homepage",
        fetch,
    ):
        result = asyncio.run(
            service.process_radar_videos(
                session,
                videos,
                qualification_context=ctx,
                subscriber_cache=cache,
                register_channels=False,
                collect_video_outcomes=True,
                subscriber_fetch_delay_seconds=0.0,
            ),
        )
    assert fetch.await_count == 1
    assert result.subscriber_fetch_count == 1


def test_cheap_rejection_skips_homepage_fetch() -> None:
    session = _session()
    ctx = load_radar_qualification_context(session)
    service = ExplosiveChannelsService()
    fetch = AsyncMock(return_value=40_000)
    low_views = _video("v-low", views=100, subs=0)

    with patch(
        "app.services.explosive_channels_service.fetch_channel_subscribers_from_homepage",
        fetch,
    ):
        asyncio.run(
            service.process_radar_videos(
                session,
                [low_views],
                qualification_context=ctx,
                register_channels=False,
                collect_video_outcomes=True,
            ),
        )
    fetch.assert_not_called()


def test_batch_video_persist_uses_single_select() -> None:
    session = _session()
    videos = [_video("v1"), _video("v2")]
    cycle_ids: set[str] = set()
    get_mock = MagicMock(wraps=session.get)

    with patch.object(session, "get", get_mock):
        results, _dup = batch_persist_discovered_videos(
            session,
            videos,
            discovery_keyword="kw",
            cycle_persisted_ids=cycle_ids,
        )
    video_gets = [c for c in get_mock.call_args_list if c.args and c.args[0] is Video]
    assert len(video_gets) == 0
    assert len(results) == 2
    assert session.scalars(select(Video)).all()


def test_rejected_qualification_still_persists_video_in_cycle() -> None:
    session = _session()
    session.add(TargetKeyword(keyword="kw", lifecycle_status="active"))
    session.commit()
    kid = session.scalars(select(TargetKeyword)).first().id

    scan = KeywordDiscoveryScanResult(
        keyword="kw",
        keyword_id=kid,
        raw_candidate_count=1,
        unique_videos=[_video("persist-me", views=100)],
        candidates=[],
        qualification_passed_count=0,
        qualification_rejected_count=1,
    )

    async def fake_scan(*_a, **_k):
        return scan

    with patch("app.services.discovery_cycle.scan_keyword_for_discovery", fake_scan):
        outcome = asyncio.run(
            run_discovery_cycle_async(
                session,
                config=DiscoveryCycleConfig(keyword_batch_size=1, profile=False),
                dry_run=False,
            ),
        )
    assert outcome.summary.persisted_video_count + outcome.summary.updated_video_count >= 1
    assert session.get(Video, "persist-me") is not None


def test_qualification_metrics_count_candidates_not_unique() -> None:
    session = _session()
    ctx = load_radar_qualification_context(session)
    service = ExplosiveChannelsService()
    same = _video("dup", views=100, subs=10_000)
    r1 = asyncio.run(
        service.process_radar_videos(
            session,
            [same],
            qualification_context=ctx,
            register_channels=False,
            collect_video_outcomes=True,
        ),
    )
    r2 = asyncio.run(
        service.process_radar_videos(
            session,
            [same],
            qualification_context=ctx,
            register_channels=False,
            collect_video_outcomes=True,
        ),
    )
    assert r1.skipped_count + r2.skipped_count == 2
