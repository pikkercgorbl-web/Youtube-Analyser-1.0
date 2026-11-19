"""Regression tests for discovery cycle session transaction ownership."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session, sessionmaker

import app.models.orm  # noqa: F401
from app.integrations.youtube.client import VideoSearchModel
from app.models.db import Base
from app.models.orm import ExplosiveChannel, ExplosiveChannelSettings, TargetKeyword
from app.services.discovery_cycle import DiscoveryCycleConfig, run_discovery_cycle, run_discovery_cycle_async
from app.services.discovery_keyword_scan import KeywordDiscoveryScanResult
from app.services.discovery_worker_runtime import DiscoveryWorkerConfig, run_discovery_worker
from app.services.explosive_channels_service import ExplosiveChannelsService, RadarProcessResult
from app.services.metrics import utc_now

UTC = timezone.utc


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _session_factory():
    engine = _engine()
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def make() -> Session:
        return factory()

    return make, engine, factory


def _video(vid: str, *, views: int = 100_000, subs: int = 10_000) -> VideoSearchModel:
    return VideoSearchModel(
        video_id=vid,
        channel_id="UC1234567890123456789012",
        channel_title="Channel",
        title=f"Title {vid}",
        views_count=views,
        subscribers_count=subs,
        published_text="2 days ago",
        duration_text="10:00",
    )


def _scan_result(keyword: str, keyword_id: int, videos: list[VideoSearchModel]) -> KeywordDiscoveryScanResult:
    return KeywordDiscoveryScanResult(
        keyword=keyword,
        keyword_id=keyword_id,
        raw_candidate_count=len(videos),
        unique_videos=videos,
        qualification_passed_count=len(videos),
        qualification_rejected_count=0,
    )


def test_process_radar_videos_flushes_instead_of_commit_on_borrowed_session() -> None:
    service = ExplosiveChannelsService()
    db = MagicMock()
    settings = ExplosiveChannelSettings(
        id=1,
        max_age_days=30,
        min_views=1000,
        min_viral_coeff=1.0,
        upload_period="week",
    )
    video = _video("v1")

    with patch.object(service, "_get_or_create_settings", return_value=settings):
        with patch.object(service, "get_thresholds", return_value=MagicMock(min_views=1000, min_viral_coeff=1.0)):
            with patch.object(service, "_register_channel_video", return_value=MagicMock()):
                with patch(
                    "app.services.explosive_channels_service.fetch_channel_subscribers_from_homepage",
                    new_callable=AsyncMock,
                    return_value=None,
                ):
                    with patch(
                        "app.services.explosive_channels_service.asyncio.sleep",
                        new_callable=AsyncMock,
                    ):
                        asyncio.run(
                            service.process_radar_videos(
                                db,
                                [video],
                                upload_period="week",
                                register_channels=True,
                            ),
                        )

    db.commit.assert_not_called()
    db.flush.assert_called()


async def _multi_page_scan(session: Session, **kwargs) -> KeywordDiscoveryScanResult:
    """Simulate two search pages; real process_radar_videos uses flush only."""
    service = ExplosiveChannelsService()
    for page in (1, 2):
        videos = [_video(f"vid-p{page}")]
        await service.process_radar_videos(
            session,
            videos,
            upload_period="week",
            register_channels=True,
        )
    return _scan_result(kwargs["keyword"], kwargs.get("keyword_id") or 0, [_video("vid-p1"), _video("vid-p2")])


def test_multi_page_discovery_cycle_no_prepared_error() -> None:
    make_session, engine, _ = _session_factory()
    session = make_session()
    now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    session.add(
        ExplosiveChannelSettings(
            id=1,
            max_age_days=30,
            min_views=1000,
            min_viral_coeff=1.0,
            upload_period="week",
            updated_at=now,
        ),
    )
    kw = TargetKeyword(
        keyword="gaming",
        lifecycle_status="active",
        source_type="seed",
        scan_interval_seconds=3600,
        next_scan_at=now - timedelta(hours=1),
    )
    session.add(kw)
    session.commit()

    commit_spy: list[str] = []
    orig_commit = Session.commit

    def tracked_commit(self: Session) -> None:
        commit_spy.append("commit")
        return orig_commit(self)

    with patch.object(Session, "commit", tracked_commit):
        with patch(
            "app.services.discovery_cycle.scan_keyword_for_discovery",
            side_effect=_multi_page_scan,
        ):
            run_discovery_cycle(
                session,
                config=DiscoveryCycleConfig(keyword_batch_size=1),
                dry_run=False,
            )

    assert commit_spy == ["commit"]
    assert session.get(ExplosiveChannel, "UC1234567890123456789012") is not None
    session.close()
    engine.dispose()


def test_multi_keyword_single_cycle_commit() -> None:
    make_session, engine, _ = _session_factory()
    session = make_session()
    now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    session.add(
        ExplosiveChannelSettings(
            id=1,
            max_age_days=30,
            min_views=1000,
            min_viral_coeff=1.0,
            upload_period="week",
            updated_at=now,
        ),
    )
    for label in ("kw-a", "kw-b"):
        session.add(
            TargetKeyword(
                keyword=label,
                lifecycle_status="active",
                source_type="seed",
                scan_interval_seconds=3600,
                next_scan_at=now - timedelta(hours=1),
            ),
        )
    session.commit()

    commit_count = {"n": 0}
    orig_commit = Session.commit

    def counting_commit(self: Session) -> None:
        commit_count["n"] += 1
        return orig_commit(self)

    async def fake_scan(session: Session, **kwargs) -> KeywordDiscoveryScanResult:
        return _scan_result(kwargs["keyword"], kwargs.get("keyword_id") or 0, [_video("v1")])

    with patch.object(Session, "commit", counting_commit):
        with patch("app.services.discovery_cycle.scan_keyword_for_discovery", side_effect=fake_scan):
            run_discovery_cycle(
                session,
                config=DiscoveryCycleConfig(keyword_batch_size=2),
                dry_run=False,
            )

    assert commit_count["n"] == 1
    session.close()
    engine.dispose()


def test_worker_does_not_commit_cycle_session_after_cycle() -> None:
    from collections import defaultdict

    from app.services.discovery_cycle import DiscoveryCycleOutcome, DiscoveryCycleSummary

    base_factory, engine, orm_factory = _session_factory()
    commits_by_session: dict[int, int] = defaultdict(int)
    cycle_session_ids: list[int] = []

    def session_factory() -> Session:
        s = orm_factory()
        sid = id(s)
        orig = s.commit

        def wrapped() -> None:
            commits_by_session[sid] += 1
            return orig()

        s.commit = wrapped  # type: ignore[method-assign]
        return s

    def fake_cycle(cycle_session, **_kwargs):
        cycle_session_ids.append(id(cycle_session))
        cycle_session.commit()
        return DiscoveryCycleOutcome(
            summary=DiscoveryCycleSummary(
                run_id="test",
                started_at=utc_now(),
                finished_at=utc_now(),
                cycle_status="ok",
            ),
        )

    done = {"flag": False}

    def stop_after_first_cycle() -> bool:
        return done["flag"]

    def cycle_and_mark(cycle_session, **_kwargs):
        outcome = fake_cycle(cycle_session)
        done["flag"] = True
        return outcome

    with patch("app.services.discovery_worker_runtime.run_discovery_cycle", side_effect=cycle_and_mark):
        run_discovery_worker(
            session_factory,
            object(),
            config=DiscoveryWorkerConfig(interval_seconds=999),
            sleep_fn=lambda _s: None,
            stop_check=stop_after_first_cycle,
            lock_holder="test-worker",
        )

    assert len(cycle_session_ids) == 1
    assert commits_by_session[cycle_session_ids[0]] == 1
    engine.dispose()


def test_settings_bootstrap_flush_persisted_by_cycle_commit() -> None:
    make_session, engine, _ = _session_factory()
    session = make_session()
    now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    session.add(
        TargetKeyword(
            keyword="solo",
            lifecycle_status="active",
            source_type="seed",
            scan_interval_seconds=3600,
            next_scan_at=now - timedelta(hours=1),
        ),
    )
    session.commit()
    assert session.get(ExplosiveChannelSettings, 1) is None

    async def fake_scan(session: Session, **kwargs) -> KeywordDiscoveryScanResult:
        return _scan_result(kwargs["keyword"], kwargs.get("keyword_id") or 0, [])

    with patch("app.services.discovery_cycle.scan_keyword_for_discovery", side_effect=fake_scan):
        run_discovery_cycle(session, config=DiscoveryCycleConfig(keyword_batch_size=1), dry_run=False)

    settings = session.get(ExplosiveChannelSettings, 1)
    assert settings is not None
    assert settings.upload_period in ("week", "all", "month", "today")

    session.close()
    verify = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    assert verify.get(ExplosiveChannelSettings, 1) is not None
    verify.close()
    engine.dispose()


def test_mid_cycle_failure_rollback_leaves_session_closable() -> None:
    make_session, engine, _ = _session_factory()
    session = make_session()
    now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    session.add(
        ExplosiveChannelSettings(
            id=1,
            max_age_days=30,
            min_views=1000,
            min_viral_coeff=1.0,
            upload_period="week",
            updated_at=now,
        ),
    )
    session.add(
        TargetKeyword(
            keyword="fail-kw",
            lifecycle_status="active",
            source_type="seed",
            scan_interval_seconds=3600,
            next_scan_at=now - timedelta(hours=1),
        ),
    )
    session.commit()

    async def failing_scan(_session: Session, **_kwargs) -> KeywordDiscoveryScanResult:
        raise RuntimeError("simulated scan failure")

    with patch("app.services.discovery_cycle.scan_keyword_for_discovery", side_effect=failing_scan):
        outcome = asyncio.run(
            run_discovery_cycle_async(
                session,
                config=DiscoveryCycleConfig(keyword_batch_size=1),
                dry_run=False,
            ),
        )

    assert outcome.summary.failed_keyword_count == 1
    session.rollback()
    session.close()
    engine.dispose()


def test_no_invalid_request_prepared_during_multi_page_radar_flush() -> None:
    """Guard: flush-only radar path must not emit SQL during PREPARED."""
    make_session, engine, _ = _session_factory()
    session = make_session()
    now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    session.add(
        ExplosiveChannelSettings(
            id=1,
            max_age_days=30,
            min_views=1000,
            min_viral_coeff=1.0,
            upload_period="week",
            updated_at=now,
        ),
    )
    session.commit()
    service = ExplosiveChannelsService()

    async def run_pages() -> None:
        for idx in range(2):
            await service.process_radar_videos(
                session,
                [_video(f"p{idx}")],
                upload_period="week",
                register_channels=True,
            )
        session.commit()

    try:
        asyncio.run(run_pages())
    except InvalidRequestError as exc:
        assert "prepared" not in str(exc).lower()
        raise
    session.close()
    engine.dispose()
