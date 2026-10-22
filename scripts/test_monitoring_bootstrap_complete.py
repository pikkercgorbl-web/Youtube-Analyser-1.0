#!/usr/bin/env python3
"""Bootstrap monitoring: enrichment snapshots + discovery hit selection (offline)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.orm  # noqa: F401
from app.integrations.youtube.client import YouTubeVideoDetails
from app.models.db import Base
from app.models.orm import (
    Channel,
    KeywordDiscoveryHit,
    TargetKeyword,
    Video,
    VideoFormat,
    VideoFormatEnrichmentAttempt,
    VideoSnapshot,
)
from app.services.channel_subscriber_backfill import SUBSCRIBERS_API_KNOWN
from app.services.format_enrichment_snapshot import FORMAT_ENRICHMENT_SNAPSHOT_SOURCE
from app.services.historical_video_format_verification import OUTCOME_CONFIRMED_REGULAR
from app.services.monitoring_cycle import run_monitoring_cycle
from app.services.monitoring_video_source import load_monitored_video_states
from app.services.snapshot_collection_policy import plan_video_revisits
from app.services.snapshot_measurement import (
    derive_latest_measurement,
    select_discovery_hit_for_measurement,
    vph_series_from_snapshots,
)
from app.services.video_format_batch_apply import apply_format_details_for_batch
from app.services.metrics import ensure_utc
from app.services.video_published_at import PUBLISHED_AT_SOURCE_API

UTC = timezone.utc


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _channel(session, pub: datetime) -> None:
    session.add(
        Channel(
            id="ch1",
            title="Ch",
            subscribers_count=1000,
            subscribers_api_status=SUBSCRIBERS_API_KNOWN,
            subscribers_api_checked_at=pub,
            created_at=pub,
        ),
    )


def test_invalid_early_hit_skipped_later_valid_used() -> None:
    pub = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    session = _session()
    _channel(session, pub)
    session.add(
        Video(
            id="v1",
            title="t",
            channel_id="ch1",
            published_at=pub,
            published_at_source=PUBLISHED_AT_SOURCE_API,
            content_format=VideoFormat.MEDIUM,
            views_count=0,
            duration_seconds=60,
        ),
    )
    session.add(TargetKeyword(id=1, keyword="k", lifecycle_status="active"))
    session.add(
        KeywordDiscoveryHit(
            keyword_id=1,
            video_id="v1",
            channel_id="ch1",
            discovery_run_id="r1",
            discovered_at=pub - timedelta(hours=2),
            views_at_discovery=100,
        ),
    )
    good_at = pub + timedelta(hours=6)
    session.add(
        KeywordDiscoveryHit(
            keyword_id=1,
            video_id="v1",
            channel_id="ch1",
            discovery_run_id="r2",
            discovered_at=good_at,
            views_at_discovery=600,
        ),
    )
    session.commit()
    video = session.get(Video, "v1")
    hits = list(session.scalars(select(KeywordDiscoveryHit).where(KeywordDiscoveryHit.video_id == "v1")))
    picked = select_discovery_hit_for_measurement(video=video, hits=hits)
    assert picked is not None
    assert ensure_utc(picked.discovered_at) == ensure_utc(good_at)
    m = derive_latest_measurement(video=video, latest_snapshot=None, discovery_hits=hits)
    assert m.average_vph == round(600 / 6.0, 4)


def test_enrichment_persist_and_bootstrap_vph() -> None:
    pub = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    stamp = pub + timedelta(hours=8)
    session = _session()
    _channel(session, pub)
    session.add(
        Video(
            id="expl1",
            title="Expl",
            channel_id="ch1",
            published_at=pub,
            published_at_source=PUBLISHED_AT_SOURCE_API,
            content_format=VideoFormat.UNKNOWN,
            views_count=0,
            duration_seconds=600,
        ),
    )
    session.commit()
    details = YouTubeVideoDetails(
        video_id="expl1",
        channel_id="ch1",
        title="Expl",
        published_at=pub,
        views_count=800,
        likes_count=0,
        comments_count=0,
        duration_seconds=600,
    )
    apply_format_details_for_batch(session, ["expl1"], {"expl1": details}, attempted_at=stamp)
    session.commit()
    snap = session.scalars(select(VideoSnapshot).where(VideoSnapshot.video_id == "expl1")).first()
    assert snap is not None
    assert snap.source == FORMAT_ENRICHMENT_SNAPSHOT_SOURCE
    assert snap.raw_metadata.get("checkpoint_age_hours") is None
    session.commit()
    now = pub + timedelta(hours=10)
    state = load_monitored_video_states(session, now=now)[0]
    assert state.raw_vph == round(800 / 8.0, 4)


def test_missing_api_views_no_enrichment_snapshot() -> None:
    pub = datetime(2026, 9, 1, tzinfo=UTC)
    session = _session()
    _channel(session, pub)
    session.add(
        Video(
            id="v2",
            title="t",
            channel_id="ch1",
            published_at=pub,
            published_at_source=PUBLISHED_AT_SOURCE_API,
            content_format=VideoFormat.UNKNOWN,
            views_count=0,
            duration_seconds=60,
        ),
    )
    session.commit()
    details = YouTubeVideoDetails(
        video_id="v2",
        channel_id="ch1",
        title="t",
        published_at=pub,
        views_count=None,
        likes_count=0,
        comments_count=0,
        duration_seconds=60,
    )
    apply_format_details_for_batch(session, ["v2"], {"v2": details}, attempted_at=pub + timedelta(hours=1))
    session.commit()
    assert session.scalars(select(VideoSnapshot).where(VideoSnapshot.video_id == "v2")).first() is None


def test_explicit_zero_views_persisted() -> None:
    pub = datetime(2026, 9, 1, tzinfo=UTC)
    stamp = pub + timedelta(hours=5)
    session = _session()
    _channel(session, pub)
    session.add(
        Video(
            id="vz",
            title="t",
            channel_id="ch1",
            published_at=pub,
            published_at_source=PUBLISHED_AT_SOURCE_API,
            content_format=VideoFormat.MEDIUM,
            views_count=99,
            duration_seconds=60,
        ),
    )
    session.commit()
    details = YouTubeVideoDetails(
        video_id="vz",
        channel_id="ch1",
        title="t",
        published_at=pub,
        views_count=0,
        likes_count=0,
        comments_count=0,
        duration_seconds=60,
    )
    apply_format_details_for_batch(session, ["vz"], {"vz": details}, attempted_at=stamp)
    session.commit()
    snap = session.scalars(select(VideoSnapshot).where(VideoSnapshot.video_id == "vz")).first()
    assert snap.views == 0


def test_reapply_enrichment_no_duplicate() -> None:
    pub = datetime(2026, 9, 1, tzinfo=UTC)
    stamp = pub + timedelta(hours=4)
    session = _session()
    _channel(session, pub)
    session.add(
        Video(
            id="vd",
            title="t",
            channel_id="ch1",
            published_at=pub,
            published_at_source=PUBLISHED_AT_SOURCE_API,
            content_format=VideoFormat.MEDIUM,
            views_count=0,
            duration_seconds=60,
        ),
    )
    session.commit()
    details = YouTubeVideoDetails(
        video_id="vd",
        channel_id="ch1",
        title="t",
        published_at=pub,
        views_count=100,
        likes_count=0,
        comments_count=0,
        duration_seconds=60,
    )
    apply_format_details_for_batch(session, ["vd"], {"vd": details}, attempted_at=stamp)
    apply_format_details_for_batch(session, ["vd"], {"vd": details}, attempted_at=stamp)
    session.commit()
    snaps = list(session.scalars(select(VideoSnapshot).where(VideoSnapshot.video_id == "vd")))
    assert len(snaps) == 1


def test_enrichment_not_fulfilled_late() -> None:
    pub = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    captured = pub + timedelta(hours=30)
    session = _session()
    _channel(session, pub)
    session.add(
        Video(
            id="vfl",
            title="t",
            channel_id="ch1",
            published_at=pub,
            published_at_source=PUBLISHED_AT_SOURCE_API,
            content_format=VideoFormat.MEDIUM,
            views_count=0,
            duration_seconds=600,
        ),
    )
    session.add(
        VideoSnapshot(
            video_id="vfl",
            channel_id="ch1",
            captured_at=captured,
            published_at=pub,
            age_hours=30.0,
            views=1000,
            source=FORMAT_ENRICHMENT_SNAPSHOT_SOURCE,
            run_id="format_enrichment:vfl",
            fetch_status="ok",
            raw_metadata={"measurement_kind": "format_enrichment_api"},
        ),
    )
    session.commit()
    from app.services.snapshot_collection_policy import existing_snapshot_from_orm

    snap = session.scalars(select(VideoSnapshot).where(VideoSnapshot.video_id == "vfl")).first()
    plan = plan_video_revisits(
        video_id="vfl",
        published_at=pub,
        existing_snapshots=[existing_snapshot_from_orm(snap)],
        current_time=pub + timedelta(hours=31),
        content_format="regular",
    )
    cp24 = next(c for c in plan.checkpoints if c.target_age_hours == 24)
    assert cp24.status != "fulfilled_late"


def test_compute_before_excludes_future_snapshot() -> None:
    pub = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    session = _session()
    _channel(session, pub)
    session.add(
        Video(
            id="vc",
            title="t",
            channel_id="ch1",
            published_at=pub,
            published_at_source=PUBLISHED_AT_SOURCE_API,
            content_format=VideoFormat.MEDIUM,
            views_count=0,
            duration_seconds=60,
        ),
    )
    early = pub + timedelta(hours=6)
    future = pub + timedelta(hours=100)
    session.add(
        VideoSnapshot(
            video_id="vc",
            channel_id="ch1",
            captured_at=early,
            published_at=pub,
            age_hours=6.0,
            views=600,
            source="t",
            run_id="r1",
            fetch_status="ok",
        ),
    )
    session.add(
        VideoSnapshot(
            video_id="vc",
            channel_id="ch1",
            captured_at=future,
            published_at=pub,
            age_hours=100.0,
            views=99999,
            source="t",
            run_id="r2",
            fetch_status="ok",
        ),
    )
    session.commit()
    video = session.get(Video, "vc")
    compute = pub + timedelta(hours=24)
    series = vph_series_from_snapshots(video=video, snapshots=session.scalars(select(VideoSnapshot)).all(), compute_before=compute)
    assert len(series) == 1
    assert series[0] == round(600 / 6.0, 4)


class _MockClient:
    def get_videos(self, video_ids: list[str]):
        from app.integrations.youtube.client import YouTubeVideoDetails

        return [
            YouTubeVideoDetails(
                video_id=vid,
                channel_id="ch1",
                title="t",
                published_at=datetime(2026, 9, 1, 0, 0, tzinfo=UTC),
                views_count=5000,
                likes_count=0,
                comments_count=0,
                duration_seconds=600,
            )
            for vid in video_ids
        ]


def test_keyword_path_selected_inserted_at_checkpoint() -> None:
    pub = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    disc = pub + timedelta(hours=6)
    session = _session()
    _channel(session, pub)
    session.add(
        Video(
            id="kw1",
            title="t",
            channel_id="ch1",
            published_at=pub,
            published_at_source=PUBLISHED_AT_SOURCE_API,
            content_format=VideoFormat.MEDIUM,
            views_count=0,
            duration_seconds=600,
        ),
    )
    session.add(
        VideoFormatEnrichmentAttempt(
            video_id="kw1",
            last_attempt_at=disc,
            last_outcome=OUTCOME_CONFIRMED_REGULAR,
        ),
    )
    session.add(TargetKeyword(id=1, keyword="k", lifecycle_status="active"))
    session.add(
        KeywordDiscoveryHit(
            keyword_id=1,
            video_id="kw1",
            channel_id="ch1",
            discovery_run_id="r1",
            discovered_at=disc,
            views_at_discovery=6000,
        ),
    )
    session.commit()
    now = disc + timedelta(hours=7)
    summary = run_monitoring_cycle(
        session,
        youtube_client=_MockClient(),
        dry_run=False,
        current_time=now,
        run_id="monitoring_kw_bootstrap_abcd1234",
    )
    assert summary.selected_request_count >= 1
    assert summary.inserted_snapshot_count >= 1


def main() -> int:
    test_invalid_early_hit_skipped_later_valid_used()
    test_enrichment_persist_and_bootstrap_vph()
    test_missing_api_views_no_enrichment_snapshot()
    test_explicit_zero_views_persisted()
    test_reapply_enrichment_no_duplicate()
    test_enrichment_not_fulfilled_late()
    test_compute_before_excludes_future_snapshot()
    test_keyword_path_selected_inserted_at_checkpoint()
    print("OK monitoring bootstrap complete regression")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
