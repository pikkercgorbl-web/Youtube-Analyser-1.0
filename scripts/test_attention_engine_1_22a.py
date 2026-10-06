"""Stage 1.22A — Attention Engine core."""

from __future__ import annotations

import json
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
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.orm  # noqa: F401
from app.api.routes import attention as attention_routes
from app.models.db import Base, get_db
from app.models.orm import (
    Channel,
    ChannelSnapshot,
    KeywordDiscoveryHit,
    KeywordLifecycleEvent,
    TargetKeyword,
    Video,
    VideoFormat,
    VideoSnapshot,
)
from app.services.attention_acceleration import classify_acceleration
from app.services.attention_engine_service import compute_attention_engine
from app.services.attention_engine_types import AttentionEngineConfig, youtube_watch_url
from app.services.attention_read_model import load_attention_snapshot, refresh_attention_engine
from app.services.attention_title_normalization import phrase_pattern_key, significant_tokens, title_ngrams

UTC = timezone.utc
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


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


def _channel(session: Session, channel_id: str, title: str, subs: int | None = None) -> Channel:
    row = Channel(
        id=channel_id,
        title=title,
        subscribers_count=subs if subs is not None else 0,
        created_at=NOW - timedelta(days=400),
    )
    session.add(row)
    return row


def _video(
    session: Session,
    video_id: str,
    channel_id: str,
    *,
    title: str,
    views: int,
    published_hours_ago: float,
    topic: str | None = None,
) -> Video:
    row = Video(
        id=video_id,
        title=title,
        views_count=views,
        likes_count=0,
        comments_count=0,
        published_at=NOW - timedelta(hours=published_hours_ago),
        duration_seconds=600,
        content_format=VideoFormat.MEDIUM,
        topic=topic,
        tags=[],
        channel_id=channel_id,
    )
    session.add(row)
    return row


def _snap(
    session: Session,
    video: Video,
    *,
    views: int,
    captured_hours_after_publish: float,
    subscribers: int | None = None,
    vph: float | None = None,
) -> VideoSnapshot:
    captured = video.published_at + timedelta(hours=captured_hours_after_publish)
    age = captured_hours_after_publish
    session.add(
        VideoSnapshot(
            video_id=video.id,
            channel_id=video.channel_id,
            captured_at=captured,
            published_at=video.published_at,
            age_hours=age,
            views=views,
            subscribers=subscribers,
            vph=vph if vph is not None else (views / age if age else None),
            source="test",
            run_id="t",
            fetch_status="ok",
        ),
    )


def _hit(session: Session, keyword_id: int, video: Video, *, views: int | None) -> None:
    session.add(
        KeywordDiscoveryHit(
            keyword_id=keyword_id,
            video_id=video.id,
            discovery_run_id="disc1",
            discovered_at=video.published_at + timedelta(minutes=30),
            channel_id=video.channel_id,
            content_format="regular",
            views_at_discovery=views,
            vph_at_discovery=None,
            qualification_state="rejected",
        ),
    )


def _seed_pair(session: Session) -> tuple[Video, Video, TargetKeyword]:
    _channel(session, "ch-a", "Channel A", subs=8_000)
    _channel(session, "ch-b", "Channel B", subs=12_000)
    kw = TargetKeyword(keyword="ai npc minecraft", lifecycle_status="active")
    session.add(kw)
    session.flush()
    v1 = _video(
        session,
        "vid-win",
        "ch-a",
        title="AI NPC Minecraft Village Survival",
        views=80_000,
        published_hours_ago=20,
        topic="ai npc",
    )
    v2 = _video(
        session,
        "vid-peer",
        "ch-b",
        title="Minecraft AI NPC Adventure",
        views=40_000,
        published_hours_ago=18,
        topic="ai npc",
    )
    _snap(session, v1, views=80_000, captured_hours_after_publish=19, subscribers=8_000, vph=4000)
    _snap(session, v2, views=40_000, captured_hours_after_publish=17, subscribers=12_000, vph=2300)
    _hit(session, kw.id, v1, views=1000)
    _hit(session, kw.id, v2, views=800)
    session.commit()
    return v1, v2, kw


def test_youtube_url() -> None:
    assert youtube_watch_url("abc") == "https://www.youtube.com/watch?v=abc"


def test_missing_subscribers_not_zero() -> None:
    session = _session()
    _channel(session, "ch-z", "Zero Channel", subs=0)
    v = _video(session, "vz", "ch-z", title="Quiet upload", views=50_000, published_hours_ago=10)
    _snap(session, v, views=50_000, captured_hours_after_publish=9, subscribers=None, vph=5000)
    session.commit()
    result = compute_attention_engine(session, now=NOW, config=AttentionEngineConfig(video_limit=50))
    winners = [w for w in result.video_winners if w.video_id == "vz"]
    assert winners
    assert winners[0].subscribers is None


def test_one_snapshot_acceleration_unavailable() -> None:
    assert classify_acceleration([100.0]) == "unavailable"


def test_three_snapshots_accelerating() -> None:
    assert classify_acceleration([100.0, 300.0, 900.0]) == "accelerating"


def test_three_snapshots_decelerating() -> None:
    assert classify_acceleration([900.0, 300.0, 100.0]) == "decelerating"


def test_winner_and_pattern_member() -> None:
    session = _session()
    v1, v2, kw = _seed_pair(session)
    result = compute_attention_engine(session, now=NOW, config=AttentionEngineConfig())
    winner_ids = {w.video_id for w in result.video_winners}
    assert v1.id in winner_ids
    assert result.patterns
    member_ids = set()
    for pattern in result.patterns:
        member_ids.update(pattern.participating_video_ids)
    assert v1.id in member_ids
    assert v2.id in member_ids


def test_pattern_requires_cross_video_and_channel_diversity() -> None:
    session = _session()
    _channel(session, "ch-only", "Solo", subs=9_000)
    kw = TargetKeyword(keyword="solo topic", lifecycle_status="active")
    session.add(kw)
    session.flush()
    a = _video(session, "s1", "ch-only", title="Solo AI NPC 1", views=60_000, published_hours_ago=12)
    b = _video(session, "s2", "ch-only", title="Solo AI NPC 2", views=55_000, published_hours_ago=11)
    _snap(session, a, views=60_000, captured_hours_after_publish=11, subscribers=9_000, vph=5000)
    _snap(session, b, views=55_000, captured_hours_after_publish=10, subscribers=9_000, vph=5000)
    _hit(session, kw.id, a, views=10)
    _hit(session, kw.id, b, views=10)
    session.commit()
    result = compute_attention_engine(session, now=NOW, config=AttentionEngineConfig())
    assert all(p.channel_count >= 2 for p in result.patterns)
    assert all(p.video_count >= 2 for p in result.patterns)


def test_deterministic_pattern_id() -> None:
    assert phrase_pattern_key("ai npc minecraft") == phrase_pattern_key("ai npc minecraft")
    session = _session()
    _seed_pair(session)
    a = compute_attention_engine(session, now=NOW, config=AttentionEngineConfig())
    b = compute_attention_engine(session, now=NOW, config=AttentionEngineConfig())
    keys_a = [p.pattern_key for p in a.patterns]
    keys_b = [p.pattern_key for p in b.patterns]
    assert keys_a == keys_b
    assert all(k.startswith(("kw:", "phrase:", "topic:")) for k in keys_a)


def test_conservative_title_grouping_and_no_unrelated_merge() -> None:
    tokens_a = significant_tokens("AI NPC Minecraft Village #12")
    tokens_b = significant_tokens("Minecraft AI NPC Adventure")
    assert "ai" in tokens_a and "npc" in tokens_a
    phrases = set(title_ngrams("AI NPC Minecraft Village")) & set(title_ngrams("Minecraft AI NPC Adventure"))
    assert "ai npc" in phrases or "npc minecraft" in phrases or "minecraft ai" in phrases
    session = _session()
    _channel(session, "c1", "C1", subs=10_000)
    _channel(session, "c2", "C2", subs=11_000)
    _channel(session, "c3", "C3", subs=12_000)
    _channel(session, "c4", "C4", subs=13_000)
    v1 = _video(session, "u1", "c1", title="Sourdough Starter Guide", views=70_000, published_hours_ago=10)
    v2 = _video(session, "u2", "c2", title="Sourdough Starter Overnight", views=65_000, published_hours_ago=9)
    v3 = _video(session, "u3", "c3", title="Jet Engine Overhaul", views=90_000, published_hours_ago=8)
    v4 = _video(session, "u4", "c4", title="Jet Engine Maintenance", views=88_000, published_hours_ago=7)
    for v in (v1, v2, v3, v4):
        _snap(session, v, views=v.views_count, captured_hours_after_publish=6, subscribers=10_000, vph=10_000)
    session.commit()
    result = compute_attention_engine(session, now=NOW, config=AttentionEngineConfig())
    labels = " ".join(p.label.lower() for p in result.patterns)
    sourdough = [p for p in result.patterns if "sourdough" in p.label]
    jet = [p for p in result.patterns if "jet" in p.label]
    assert sourdough
    assert jet
    for p in sourdough:
        assert "u3" not in p.participating_video_ids
        assert "u4" not in p.participating_video_ids


def test_reason_codes_and_no_hidden_score() -> None:
    session = _session()
    _seed_pair(session)
    result = compute_attention_engine(session, now=NOW, config=AttentionEngineConfig())
    assert result.video_winners
    from dataclasses import asdict

    for row in result.video_winners:
        assert row.reason_codes
        assert row.human_reasons
        blob = json.dumps(asdict(row), default=str).lower()
        assert "opportunity_score" not in blob
        assert "success_probability" not in blob
    for row in result.patterns:
        assert row.reason_codes
        assert "channel_diversity" in row.reason_codes


def test_missing_72h_stays_missing() -> None:
    session = _session()
    _channel(session, "ch-m", "M", subs=9_000)
    kw = TargetKeyword(keyword="old hit", lifecycle_status="active")
    session.add(kw)
    session.flush()
    v = _video(session, "oldv", "ch-m", title="Old enough", views=30_000, published_hours_ago=100)
    _snap(session, v, views=1_000, captured_hours_after_publish=2, subscribers=9_000, vph=500)
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id=v.id,
            discovery_run_id="disc1",
            discovered_at=NOW - timedelta(hours=90),
            channel_id=v.channel_id,
            content_format="regular",
            views_at_discovery=1000,
            qualification_state="passed",
        ),
    )
    session.commit()
    from app.models.orm import VideoSnapshot
    from app.services.attention_delayed_outcome import delayed_outcome_for_video

    snaps = list(session.scalars(select(VideoSnapshot).where(VideoSnapshot.video_id == "oldv")).all())
    hits = list(session.scalars(select(KeywordDiscoveryHit).where(KeywordDiscoveryHit.video_id == "oldv")).all())
    state, growth = delayed_outcome_for_video(video_id="oldv", hits=hits, snapshots=snaps, now=NOW)
    assert state == "missing"
    assert growth is None


def test_no_subscriber_growth_without_history() -> None:
    session = _session()
    _seed_pair(session)
    result = compute_attention_engine(session, now=NOW, config=AttentionEngineConfig())
    for row in result.channels:
        if not row.subscriber_growth_available:
            assert row.subscriber_growth_absolute is None
            assert row.subscriber_growth_pct is None
            assert "subscriber_growth" not in row.reason_codes


def test_subscriber_growth_when_snapshots_exist() -> None:
    session = _session()
    _seed_pair(session)
    session.add(
        ChannelSnapshot(
            channel_id="ch-a",
            subscribers_count=5_000,
            total_views=1,
            video_count=1,
            recorded_at=NOW - timedelta(days=10),
        ),
    )
    session.add(
        ChannelSnapshot(
            channel_id="ch-a",
            subscribers_count=8_000,
            total_views=2,
            video_count=2,
            recorded_at=NOW - timedelta(hours=1),
        ),
    )
    extra = _video(
        session,
        "vid-win-2",
        "ch-a",
        title="AI NPC follow up",
        views=20_000,
        published_hours_ago=30,
    )
    _snap(session, extra, views=20_000, captured_hours_after_publish=20, subscribers=8_000, vph=1000)
    session.commit()
    result = compute_attention_engine(session, now=NOW, config=AttentionEngineConfig())
    ch = next((c for c in result.channels if c.channel_id == "ch-a"), None)
    if ch is not None:
        assert ch.subscriber_growth_available is True
        assert ch.subscriber_growth_absolute == 3_000


def test_bounded_output() -> None:
    session = _session()
    _seed_pair(session)
    cfg = AttentionEngineConfig(video_limit=1, pattern_limit=1, channel_limit=1)
    result = compute_attention_engine(session, now=NOW, config=cfg)
    assert len(result.video_winners) <= 1
    assert len(result.patterns) <= 1
    assert len(result.channels) <= 1


def test_no_lifecycle_writes() -> None:
    session = _session()
    _seed_pair(session)
    before = session.scalar(select(func.count()).select_from(KeywordLifecycleEvent)) or 0
    compute_attention_engine(session, now=NOW, config=AttentionEngineConfig())
    after = session.scalar(select(func.count()).select_from(KeywordLifecycleEvent)) or 0
    assert after == before


def test_no_youtube_http_or_llm() -> None:
    session = _session()
    _seed_pair(session)
    with patch("httpx.AsyncClient") as http_client, patch(
        "app.integrations.youtube.client.fetch_channel_subscribers_from_homepage",
    ) as fetch:
        compute_attention_engine(session, now=NOW, config=AttentionEngineConfig())
        http_client.assert_not_called()
        fetch.assert_not_called()


def test_api_reads_snapshot_not_history() -> None:
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
        summary = client.get("/api/attention/summary")
        videos = client.get("/api/attention/videos")
        live.assert_not_called()
    assert summary.json()["data_source"] == "snapshot"
    assert videos.json()["data_source"] == "snapshot"
    assert videos.json()["items"]
    assert videos.json()["items"][0]["youtube_url"].startswith("https://www.youtube.com/watch?v=")
    empty_engine = _engine()
    empty_factory = sessionmaker(bind=empty_engine)

    def override_empty() -> Generator[Session, None, None]:
        db = empty_factory()
        try:
            yield db
        finally:
            db.close()

    api.dependency_overrides[get_db] = override_empty
    empty_client = TestClient(api)
    empty = empty_client.get("/api/attention/summary")
    assert empty.json()["data_source"] == "unavailable"


def test_refresh_roundtrip() -> None:
    session = _session()
    _seed_pair(session)
    written = refresh_attention_engine(session, config=AttentionEngineConfig(), now=NOW)
    session.commit()
    loaded = load_attention_snapshot(session)
    assert loaded is not None
    assert loaded.summary.candidate_video_count == written.summary.candidate_video_count
    assert [w.video_id for w in loaded.video_winners] == [w.video_id for w in written.video_winners]


def test_phrase_duplicate_collapse() -> None:
    from app.services.attention_patterns import _should_skip_phrase

    kept = [("ai npc minecraft", {"a", "b", "c"})]
    assert _should_skip_phrase("ai npc", {"a", "b"}, kept) is True
    assert _should_skip_phrase("jet engine", {"x", "y"}, kept) is False


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_") and callable(value)]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"OK {fn.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
            raise
    if failed:
        raise SystemExit(1)
    print(f"Passed {len(tests)} tests")
