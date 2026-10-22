"""Channel momentum representative video hydration (read path)."""

from __future__ import annotations

import sys
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.orm  # noqa: F401
from app.api.routes import attention as attention_routes
from app.models.db import Base, get_db
from app.models.orm import Channel, Video, VideoFormat, VideoSnapshot
from app.services.video_published_at import PUBLISHED_AT_SOURCE_API
from app.services.attention_channel_momentum_hydrate import (
    MEASUREMENT_SOURCE_FROZEN,
    hydrate_channel_representative_videos,
    resolve_channel_representative_videos,
)
from app.services.attention_engine_types import (
    AttentionEngineConfig,
    ChannelMomentum,
    ChannelRepresentativeVideoEvidence,
)
from app.services.attention_read_model import refresh_attention_engine
from scripts.test_attention_engine_1_22a import NOW, _channel, _engine, _seed_pair, _snap, _video

UTC = timezone.utc


def test_hydrate_representative_batch_age_aligned_vph() -> None:
    engine = _engine()
    factory = sessionmaker(bind=engine)
    session = factory()
    ch = _channel(session, "UCm1", "Momentum Channel", subs=5000)
    prev_v = _video(session, "prev-a", ch.id, title="Previous A", views=1000, published_hours_ago=24 * 10)
    _snap(session, prev_v, views=240, captured_hours_after_publish=24.0, vph=10.0)
    prev_b = _video(session, "prev-b", ch.id, title="Previous B", views=1000, published_hours_ago=24 * 11)
    _snap(session, prev_b, views=480, captured_hours_after_publish=24.0, vph=20.0)
    recent_strong = _video(
        session,
        "rep-strong",
        ch.id,
        title="Recent Strong",
        views=5000,
        published_hours_ago=24 * 2,
    )
    _snap(session, recent_strong, views=1200, captured_hours_after_publish=24.0, vph=50.0)
    for vid in (prev_v, prev_b, recent_strong):
        vid.published_at_source = PUBLISHED_AT_SOURCE_API
    session.commit()

    channel_row = ChannelMomentum(
        channel_id=ch.id,
        channel_title=ch.title,
        subscriber_count_latest=5000,
        observed_video_count=3,
        recent_video_count=1,
        previous_video_count=2,
        breakout_video_count=0,
        confirmed_72h_count=0,
        recent_median_vph=50.0,
        previous_median_vph=15.0,
        recent_median_vph_vs_previous=3.33,
        subscriber_growth_absolute=None,
        subscriber_growth_pct=None,
        subscriber_growth_available=False,
        first_observed_at=None,
        latest_observed_at=None,
        representative_video_ids=("rep-strong",),
        reason_codes=("repeated_age_aligned_improvement",),
        human_reasons=(),
        recent_window_days=7,
        previous_window_days=7,
        momentum_horizon_hours=24,
        momentum_horizon_tolerance_hours=6.0,
        recent_measurable_count=1,
        previous_measurable_count=2,
        recent_improvement_count=1,
        improvement_ratio_threshold=1.5,
        previous_baseline_zero=False,
        incompleteness_notes=(),
    )
    hydrated = hydrate_channel_representative_videos(session, [channel_row])
    rep = hydrated[ch.id][0]
    assert rep["video_id"] == "rep-strong"
    assert rep["title"] == "Recent Strong"
    assert rep["horizon_vph"] is not None
    assert abs(float(rep["horizon_vph"]) - 50.0) < 0.01
    assert rep["measured_at"] is not None
    assert rep["vs_previous_median_ratio"] is not None
    assert rep["meets_improvement_threshold"] is True
    assert rep["unavailable_reason"] is None
    session.close()


def test_channels_api_includes_representative_videos_without_live_recompute() -> None:
    engine = _engine()
    factory = sessionmaker(bind=engine)
    session = factory()
    _seed_pair(session)
    refresh_attention_engine(session, config=AttentionEngineConfig(), now=NOW)
    session.commit()
    session.close()

    api = FastAPI()
    api.include_router(attention_routes.router, prefix="/api/attention")

    def override_get_db() -> Generator[Session, None, None]:
        db = factory()
        try:
            yield db
        finally:
            db.close()

    api.dependency_overrides[get_db] = override_get_db
    client = TestClient(api)
    with patch("app.api.routes.attention.compute_attention_engine") as live:
        response = client.get("/api/attention/channels")
        live.assert_not_called()
    assert response.status_code == 200
    body = response.json()
    for row in body["items"]:
        assert "representative_videos" in row
        assert len(row["representative_videos"]) == len(row["representative_video_ids"])
        for rep in row["representative_videos"]:
            assert rep["youtube_url"].startswith("https://www.youtube.com/watch?v=")


def test_later_snapshot_does_not_change_replay_with_attention_cutoff() -> None:
    engine = _engine()
    factory = sessionmaker(bind=engine)
    session = factory()
    attention_at = NOW
    ch = _channel(session, "UCm2", "Stable Channel", subs=1000)
    video = _video(
        session,
        "rep-stable",
        ch.id,
        title="Stable Rep",
        views=5000,
        published_hours_ago=24 * 3,
    )
    _snap(session, video, views=240, captured_hours_after_publish=24.0, vph=10.0)
    video.published_at_source = PUBLISHED_AT_SOURCE_API
    session.commit()

    channel_row = ChannelMomentum(
        channel_id=ch.id,
        channel_title=ch.title,
        subscriber_count_latest=1000,
        observed_video_count=1,
        recent_video_count=1,
        previous_video_count=2,
        breakout_video_count=0,
        confirmed_72h_count=0,
        recent_median_vph=10.0,
        previous_median_vph=5.0,
        recent_median_vph_vs_previous=2.0,
        subscriber_growth_absolute=None,
        subscriber_growth_pct=None,
        subscriber_growth_available=False,
        first_observed_at=None,
        latest_observed_at=None,
        representative_video_ids=("rep-stable",),
        reason_codes=("repeated_age_aligned_improvement",),
        human_reasons=(),
        recent_window_days=7,
        previous_window_days=7,
        momentum_horizon_hours=24,
        momentum_horizon_tolerance_hours=6.0,
        recent_measurable_count=1,
        previous_measurable_count=2,
        recent_improvement_count=1,
        improvement_ratio_threshold=1.5,
        previous_baseline_zero=False,
        incompleteness_notes=(),
    )

    before = resolve_channel_representative_videos(
        session,
        [channel_row],
        attention_computed_at=attention_at,
    )[ch.id][0]
    assert before["horizon_vph"] is not None

    # Insert a newer snapshot (after Attention publish) that would win without cutoff.
    captured_later = attention_at + timedelta(hours=2)
    session.add(
        VideoSnapshot(
            video_id=video.id,
            channel_id=video.channel_id,
            captured_at=captured_later,
            published_at=video.published_at,
            age_hours=26.0,
            views=5200,
            subscribers=1000,
            vph=200.0,
            source="test",
            fetch_status="ok",
            run_id="later",
        ),
    )
    session.commit()

    after = resolve_channel_representative_videos(
        session,
        [channel_row],
        attention_computed_at=attention_at,
    )[ch.id][0]
    assert after["horizon_vph"] == before["horizon_vph"]
    assert after["measured_at"] == before["measured_at"]
    assert after["measurement_source"] == "video_snapshot_replay_before_attention"
    session.close()


def test_frozen_evidence_ignores_later_snapshots() -> None:
    engine = _engine()
    factory = sessionmaker(bind=engine)
    session = factory()
    attention_at = NOW
    ch = _channel(session, "UCm3", "Frozen Channel", subs=1000)
    video = _video(
        session,
        "rep-frozen",
        ch.id,
        title="Frozen Rep",
        views=5000,
        published_hours_ago=24 * 3,
    )
    _snap(session, video, views=240, captured_hours_after_publish=24.0, vph=10.0)
    video.published_at_source = PUBLISHED_AT_SOURCE_API
    session.commit()
    measured_at = video.published_at + timedelta(hours=24.0)
    snap_row = session.scalars(
        select(VideoSnapshot).where(VideoSnapshot.video_id == video.id),
    ).first()

    frozen = ChannelRepresentativeVideoEvidence(
        video_id="rep-frozen",
        horizon_vph=10.0,
        measured_at=measured_at,
        actual_age_hours=24.0,
        vs_previous_median_ratio=2.0,
        meets_improvement_threshold=True,
        snapshot_row_id=int(snap_row.id) if snap_row is not None else None,
    )
    channel_row = ChannelMomentum(
        channel_id=ch.id,
        channel_title=ch.title,
        subscriber_count_latest=1000,
        observed_video_count=1,
        recent_video_count=1,
        previous_video_count=2,
        breakout_video_count=0,
        confirmed_72h_count=0,
        recent_median_vph=10.0,
        previous_median_vph=5.0,
        recent_median_vph_vs_previous=2.0,
        subscriber_growth_absolute=None,
        subscriber_growth_pct=None,
        subscriber_growth_available=False,
        first_observed_at=None,
        latest_observed_at=None,
        representative_video_ids=("rep-frozen",),
        representative_video_evidence=(frozen,),
        reason_codes=("repeated_age_aligned_improvement",),
        human_reasons=(),
        recent_window_days=7,
        previous_window_days=7,
        momentum_horizon_hours=24,
        momentum_horizon_tolerance_hours=6.0,
        recent_measurable_count=1,
        previous_measurable_count=2,
        recent_improvement_count=1,
        improvement_ratio_threshold=1.5,
        previous_baseline_zero=False,
        incompleteness_notes=(),
    )

    first = resolve_channel_representative_videos(
        session,
        [channel_row],
        attention_computed_at=attention_at,
    )[ch.id][0]
    session.add(
        VideoSnapshot(
            video_id=video.id,
            channel_id=video.channel_id,
            captured_at=attention_at + timedelta(hours=3),
            published_at=video.published_at,
            age_hours=27.0,
            views=9000,
            subscribers=1000,
            vph=333.0,
            source="test",
            fetch_status="ok",
            run_id="later2",
        ),
    )
    session.commit()
    second = resolve_channel_representative_videos(
        session,
        [channel_row],
        attention_computed_at=attention_at,
    )[ch.id][0]
    assert second["measurement_source"] == MEASUREMENT_SOURCE_FROZEN
    assert second["horizon_vph"] == first["horizon_vph"] == 10.0
    assert snap_row is not None
    assert second["snapshot_row_id"] == int(snap_row.id)
    session.close()


if __name__ == "__main__":
    test_hydrate_representative_batch_age_aligned_vph()
    test_later_snapshot_does_not_change_replay_with_attention_cutoff()
    test_frozen_evidence_ignores_later_snapshots()
    test_channels_api_includes_representative_videos_without_live_recompute()
    print("ok")
