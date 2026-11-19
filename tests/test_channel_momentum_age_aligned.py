"""Channel Momentum age-aligned improvement rules."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.orm  # noqa: F401
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
from app.services.attention_channel_momentum import build_channel_momentum
from app.services.attention_engine_types import AttentionEngineConfig
from app.services.attention_evidence import load_attention_evidence
from app.services.video_format_outcomes import OUTCOME_CONFIRMED_REGULAR
from app.services.video_published_at import PUBLISHED_AT_SOURCE_API

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


def _channel(session: Session, channel_id: str, subs: int = 5_000) -> None:
    session.add(
        Channel(
            id=channel_id,
            title=f"Channel {channel_id}",
            subscribers_count=subs,
            subscribers_api_status="known",
            created_at=NOW - timedelta(days=400),
        ),
    )


def _video(
    session: Session,
    video_id: str,
    *,
    published_hours_ago: float,
    fmt: VideoFormat = VideoFormat.MEDIUM,
) -> Video:
    row = Video(
        id=video_id,
        title=f"Video {video_id}",
        views_count=1,
        likes_count=0,
        comments_count=0,
        published_at=NOW - timedelta(hours=published_hours_ago),
        published_at_source=PUBLISHED_AT_SOURCE_API,
        duration_seconds=600,
        content_format=fmt,
        tags=[],
        channel_id="ch-m",
    )
    session.add(row)
    return row


def _confirm(session: Session, video_id: str) -> None:
    session.add(
        VideoFormatEnrichmentAttempt(
            video_id=video_id,
            last_attempt_at=NOW,
            last_outcome=OUTCOME_CONFIRMED_REGULAR,
        ),
    )


def _snap_at_horizon(
    session: Session,
    video: Video,
    *,
    hours_after_publish: float,
    views: int,
) -> None:
    captured = video.published_at + timedelta(hours=hours_after_publish)
    session.add(
        VideoSnapshot(
            video_id=video.id,
            channel_id=video.channel_id,
            captured_at=captured,
            published_at=video.published_at,
            age_hours=hours_after_publish,
            views=views,
            vph=views / hours_after_publish if hours_after_publish else None,
            source="test",
            run_id="t",
            fetch_status="ok",
        ),
    )


def _snap_latest_inflated(session: Session, video: Video, *, views: int) -> None:
    captured = NOW - timedelta(minutes=30)
    age = (captured - video.published_at).total_seconds() / 3600.0
    session.add(
        VideoSnapshot(
            video_id=video.id,
            channel_id=video.channel_id,
            captured_at=captured,
            published_at=video.published_at,
            age_hours=age,
            views=views,
            vph=views / age if age > 0 else None,
            source="test",
            run_id="t2",
            fetch_status="ok",
        ),
    )


def _seed_window_anchor(session: Session, video: Video) -> None:
    kw = TargetKeyword(keyword="anchor", lifecycle_status="active")
    session.add(kw)
    session.flush()
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id=video.id,
            discovery_run_id="disc",
            discovered_at=NOW - timedelta(hours=2),
            channel_id=video.channel_id,
            content_format="regular",
            views_at_discovery=10,
            qualification_state="passed",
        ),
    )


def _bundle(session: Session):
    cfg = AttentionEngineConfig()
    ws, we = NOW - timedelta(hours=cfg.window_hours), NOW
    lb = we - timedelta(days=cfg.channel_recent_days + cfg.channel_previous_days)
    return load_attention_evidence(session, window_start=ws, window_end=we, channel_lookback_start=lb)


def _confirmed_ids(session: Session, bundle) -> frozenset[str]:
    from app.services.video_format_api_verification import load_api_format_confirmed_video_ids

    ids = list(bundle.records.keys())
    for rows in bundle.extra_channel_videos.values():
        ids.extend(v.id for v in rows)
    return load_api_format_confirmed_video_ids(session, list(dict.fromkeys(ids)))


def test_current_age_does_not_inflate_signal() -> None:
    session = _session()
    _channel(session, "ch-m")
    prev_a = _video(session, "p1", published_hours_ago=24 * 10)
    prev_b = _video(session, "p2", published_hours_ago=24 * 11)
    rec_a = _video(session, "r1", published_hours_ago=24 * 2)
    rec_b = _video(session, "r2", published_hours_ago=24 * 3)
    for v in (prev_a, prev_b, rec_a, rec_b):
        _confirm(session, v.id)
        _snap_at_horizon(session, v, hours_after_publish=24, views=100 if v.id.startswith("p") else 200)
    _snap_latest_inflated(session, rec_a, views=1_000_000)
    _seed_window_anchor(session, rec_a)
    session.commit()
    bundle = _bundle(session)
    confirmed = _confirmed_ids(session, bundle)
    rows = build_channel_momentum(bundle, AttentionEngineConfig(), now=NOW, publishable_confirmed_ids=confirmed)
    assert len(rows) == 1
    assert rows[0].recent_improvement_count >= 2


def test_one_strong_recent_fails() -> None:
    session = _session()
    _channel(session, "ch-m")
    anchor = None
    for vid, hrs, views in (
        ("p1", 24 * 10, 100),
        ("p2", 24 * 11, 100),
        ("r1", 24 * 2, 200),
        ("r2", 24 * 3, 50),
    ):
        v = _video(session, vid, published_hours_ago=hrs)
        if vid == "r1":
            anchor = v
        _confirm(session, vid)
        _snap_at_horizon(session, v, hours_after_publish=24, views=views)
    assert anchor is not None
    _seed_window_anchor(session, anchor)
    session.commit()
    bundle = _bundle(session)
    confirmed = _confirmed_ids(session, bundle)
    rows = build_channel_momentum(bundle, AttentionEngineConfig(), now=NOW, publishable_confirmed_ids=confirmed)
    assert rows == []


def test_two_improving_recent_pass() -> None:
    session = _session()
    _channel(session, "ch-m")
    for vid, hrs, views in (
        ("p1", 24 * 10, 100),
        ("p2", 24 * 11, 100),
        ("r1", 24 * 2, 200),
        ("r2", 24 * 3, 180),
    ):
        v = _video(session, vid, published_hours_ago=hrs)
        _confirm(session, vid)
        _snap_at_horizon(session, v, hours_after_publish=24, views=views)
        if vid == "r1":
            _seed_window_anchor(session, v)
    session.commit()
    bundle = _bundle(session)
    confirmed = _confirmed_ids(session, bundle)
    rows = build_channel_momentum(bundle, AttentionEngineConfig(), now=NOW, publishable_confirmed_ids=confirmed)
    assert len(rows) == 1
    assert "repeated_age_aligned_improvement" in rows[0].reason_codes


def test_missing_snapshots_insufficient_data() -> None:
    session = _session()
    _channel(session, "ch-m")
    anchor = None
    for vid, hrs in (("p1", 24 * 10), ("p2", 24 * 11), ("r1", 24 * 2), ("r2", 24 * 3)):
        v = _video(session, vid, published_hours_ago=hrs)
        if vid == "r1":
            anchor = v
        _confirm(session, vid)
    assert anchor is not None
    _seed_window_anchor(session, anchor)
    session.commit()
    bundle = _bundle(session)
    confirmed = _confirmed_ids(session, bundle)
    rows = build_channel_momentum(bundle, AttentionEngineConfig(), now=NOW, publishable_confirmed_ids=confirmed)
    assert rows == []


def test_live_and_unconfirmed_do_not_support_signal() -> None:
    session = _session()
    _channel(session, "ch-m")
    live = _video(session, "live1", published_hours_ago=24 * 2, fmt=VideoFormat.LIVE)
    _snap_at_horizon(session, live, hours_after_publish=24, views=999_999)
    unconfirmed = _video(session, "u1", published_hours_ago=24 * 2)
    _snap_at_horizon(session, unconfirmed, hours_after_publish=24, views=500)
    _seed_window_anchor(session, unconfirmed)
    session.commit()
    bundle = _bundle(session)
    confirmed = _confirmed_ids(session, bundle)
    rows = build_channel_momentum(bundle, AttentionEngineConfig(), now=NOW, publishable_confirmed_ids=confirmed)
    assert rows == []


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
        print(f"OK {fn.__name__}")
    print(f"Passed {len(tests)} tests")
