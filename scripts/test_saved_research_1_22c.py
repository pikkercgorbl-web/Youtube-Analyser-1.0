"""Stage 1.22C — Saved Research (SavedVideo + SavedFamily) tests."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
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
from app.api.routes import saved_research as saved_research_routes
from app.models.db import Base, get_db
from app.models.orm import Channel, SavedFamily, SavedFamilyObservation, SavedVideo, SavedVideoObservation, Video
from app.services.attention_engine_types import (
    AttentionEngineResult,
    AttentionSummary,
    ChannelRelativeSignal,
    PatternCandidate,
    PatternFamily,
    VideoWinner,
    youtube_watch_url,
)
from app.services.attention_read_model import persist_attention_result
from app.services.saved_research import (
    VIDEO_ABSENCE_MESSAGE,
    save_family,
    save_video,
)
from app.services.saved_topics import FAMILY_ABSENCE_MESSAGE

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


def _channel_relative() -> ChannelRelativeSignal:
    return ChannelRelativeSignal(
        status="production_ready",
        baseline_quality="production_ready",
        comparable_video_count=6,
        vph_vs_channel_median=2.25,
        notes=("age_aligned_baseline",),
    )


def _winner(video_id: str = "vid-a", *, with_channel_relative: bool = False) -> VideoWinner:
    return VideoWinner(
        video_id=video_id,
        title="Title",
        channel_id="ch-a",
        channel_title="Channel A",
        youtube_url=youtube_watch_url(video_id),
        published_at=NOW,
        age_hours=12.0,
        views=84000,
        vph=12000.0,
        subscribers=18000,
        breakout_rank=4,
        breakout_eligible=True,
        channel_relative_signal=_channel_relative() if with_channel_relative else None,
        acceleration_state="accelerating",
        delayed_outcome_state="pending",
        delayed_outcome_growth=None,
        reason_codes=("breakout_high_rank",),
        human_reasons=("breakout rank 4",),
        keyword_ids=(1,),
    )


def _family() -> PatternFamily:
    return PatternFamily(
        family_key="family:test:one",
        label="AI Minecraft NPC",
        family_kind="title_phrase",
        member_pattern_keys=("phrase:abcd",),
        member_labels=("ai npc",),
        video_ids=("vid-a", "vid-b"),
        channel_ids=("ch-a", "ch-b"),
        keyword_ids=(1,),
        video_count=2,
        channel_count=2,
        keyword_count=1,
        breakout_eligible_count=1,
        videos_last_24h=2,
        videos_previous_24h=0,
        videos_previous_48_24h=0,
        grouping_reasons=("singleton",),
        quality_flags=(),
        support_sources=("title_phrase",),
        first_seen_at=NOW,
        latest_seen_at=NOW,
    )


def _result(*, run_id: str, with_channel_relative: bool = False) -> AttentionEngineResult:
    return AttentionEngineResult(
        summary=AttentionSummary(
            run_id=run_id,
            computed_at=NOW,
            timezone_name="UTC",
            window_hours=24,
            window_start=NOW,
            window_end=NOW,
            source="snapshot",
            candidate_video_count=2,
            winner_count=1,
            pattern_count=1,
            channel_momentum_count=0,
            video_limit=50,
            pattern_limit=20,
            channel_limit=20,
            notes={},
        ),
        video_winners=(_winner(with_channel_relative=with_channel_relative),),
        patterns=(
            PatternCandidate(
                pattern_key="phrase:abcd",
                kind="title_phrase",
                label="ai npc",
                video_count=2,
                channel_count=2,
                keyword_count=1,
                breakout_video_count=1,
                small_channel_winner_count=0,
                first_seen_at=NOW,
                latest_seen_at=NOW,
                videos_last_24h=2,
                videos_previous_24h=0,
                videos_previous_48_24h=0,
                participating_video_ids=("vid-a", "vid-b"),
                participating_channel_ids=("ch-a", "ch-b"),
                participating_keyword_ids=(1,),
                reason_codes=("multi_video_evidence",),
                human_reasons=("2 related videos",),
            ),
        ),
        families=(_family(),),
        channels=(),
    )


def _seed_video_corpus(session: Session) -> None:
    session.add(Channel(id="ch-a", title="Channel A", subscribers_count=1000, created_at=NOW))
    session.add(
        Video(
            id="vid-a",
            title="Title",
            views_count=84000,
            likes_count=0,
            comments_count=0,
            published_at=NOW,
            duration_seconds=600,
            channel_id="ch-a",
        ),
    )
    session.commit()


def _persist_run(session: Session, run_id: str, *, with_channel_relative: bool = False) -> None:
    persist_attention_result(
        session,
        _result(run_id=run_id, with_channel_relative=with_channel_relative),
        run_id=run_id,
    )
    session.commit()


def test_save_video_and_family() -> None:
    session = _session()
    _seed_video_corpus(session)
    _persist_run(session, "attention_run_1")
    v = save_video(session, video_id="vid-a")
    f = save_family(session, family_key="family:test:one")
    session.commit()
    assert v.created and f.created
    assert session.scalar(select(func.count()).select_from(SavedVideoObservation)) == 1
    assert session.scalar(select(func.count()).select_from(SavedFamilyObservation)) == 1
    frozen = json.loads(v.item.frozen_payload_json)
    assert frozen["context"]["family_memberships"][0]["label"] == "AI Minecraft NPC"


def test_duplicate_save_idempotent() -> None:
    session = _session()
    _seed_video_corpus(session)
    _persist_run(session, "attention_run_1")
    save_video(session, video_id="vid-a")
    session.commit()
    again = save_video(session, video_id="vid-a")
    session.commit()
    assert again.idempotent
    assert session.scalar(select(func.count()).select_from(SavedVideo)) == 1


def test_refresh_appends_observation() -> None:
    session = _session()
    _seed_video_corpus(session)
    _persist_run(session, "attention_run_1")
    save_video(session, video_id="vid-a")
    session.commit()
    _persist_run(session, "attention_run_2")
    assert session.scalar(select(func.count()).select_from(SavedVideoObservation)) == 2


def test_video_absent_from_attention_still_observation() -> None:
    session = _session()
    _seed_video_corpus(session)
    _persist_run(session, "attention_run_1")
    save_video(session, video_id="vid-a")
    session.commit()
    empty_winners = _result(run_id="attention_run_2")
    from dataclasses import replace

    empty = replace(empty_winners, video_winners=())
    persist_attention_result(session, empty, run_id="attention_run_2")
    session.commit()
    obs = session.scalars(
        select(SavedVideoObservation).order_by(SavedVideoObservation.id.desc()),
    ).first()
    assert obs is not None
    assert obs.video_present_in_attention is False
    payload = json.loads(obs.payload_json)
    assert payload.get("absence_message") == VIDEO_ABSENCE_MESSAGE


def test_family_absence_semantics() -> None:
    session = _session()
    _seed_video_corpus(session)
    _persist_run(session, "attention_run_1")
    save_family(session, family_key="family:test:one")
    session.commit()
    from dataclasses import replace

    no_families = replace(_result(run_id="attention_run_2"), families=())
    persist_attention_result(session, no_families, run_id="attention_run_2")
    session.commit()
    obs = session.scalars(
        select(SavedFamilyObservation).order_by(SavedFamilyObservation.id.desc()),
    ).first()
    assert obs.family_present is False
    payload = json.loads(obs.payload_json)
    assert payload.get("absence_message") == FAMILY_ABSENCE_MESSAGE


def test_frozen_channel_relative_and_youtube_url() -> None:
    session = _session()
    _seed_video_corpus(session)
    _persist_run(session, "attention_run_1", with_channel_relative=True)
    v = save_video(session, video_id="vid-a")
    session.commit()
    frozen = json.loads(v.item.frozen_payload_json)
    assert frozen["identity"]["youtube_url"] == youtube_watch_url("vid-a")
    rel = frozen["evidence"]["channel_relative_signal"]
    assert rel["status"] == "production_ready"
    assert rel["vph_vs_channel_median"] == 2.25
    assert rel["comparable_video_count"] == 6


def test_observation_payload_preserves_winner_channel_relative() -> None:
    session = _session()
    _seed_video_corpus(session)
    _persist_run(session, "attention_run_1", with_channel_relative=True)
    save_video(session, video_id="vid-a")
    session.commit()
    obs = session.scalars(select(SavedVideoObservation)).first()
    assert obs is not None
    payload = json.loads(obs.payload_json)
    rel = payload["winner"]["channel_relative_signal"]
    assert rel["vph_vs_channel_median"] == 2.25


def test_api_history_pagination() -> None:
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)

    def override_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(saved_research_routes.router, prefix="/api")
    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)

    db = SessionLocal()
    _seed_video_corpus(db)
    _persist_run(db, "attention_run_1")
    save_video(db, video_id="vid-a")
    db.commit()
    _persist_run(db, "attention_run_2")
    db.commit()
    vid = db.scalars(select(SavedVideo)).first()
    assert vid is not None
    item_id = vid.id
    db.close()

    full = client.get(f"/api/saved-videos/{item_id}/history", params={"limit": 50, "offset": 0})
    assert full.status_code == 200
    body = full.json()
    assert isinstance(body["items"], list)
    assert body["total"] == 2
    assert len(body["items"]) == 2
    page = client.get(f"/api/saved-videos/{item_id}/history", params={"limit": 1, "offset": 0})
    assert page.json()["total"] == 2
    assert len(page.json()["items"]) == 1


def test_api_patch_does_not_mutate_frozen() -> None:
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)

    def override_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(saved_research_routes.router, prefix="/api")
    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)

    db = SessionLocal()
    _seed_video_corpus(db)
    _persist_run(db, "attention_run_1", with_channel_relative=True)
    db.close()

    r = client.post("/api/saved-videos", json={"video_id": "vid-a"})
    vid = r.json()["item"]["id"]
    before = r.json()["item"]["frozen_snapshot"]
    client.patch(f"/api/saved-videos/{vid}", json={"notes": "changed", "status": "DROPPED"})
    after = client.get(f"/api/saved-videos/{vid}").json()["frozen_snapshot"]
    assert after == before


def test_api_patch_and_archive() -> None:
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)

    def override_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(saved_research_routes.router, prefix="/api")
    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)

    db = SessionLocal()
    _seed_video_corpus(db)
    _persist_run(db, "attention_run_1")
    db.close()

    r = client.post("/api/saved-videos", json={"video_id": "vid-a"})
    assert r.status_code == 200
    vid = r.json()["item"]["id"]
    r2 = client.patch(f"/api/saved-videos/{vid}", json={"status": "TESTING", "tags": ["minecraft"]})
    assert r2.status_code == 200
    assert r2.json()["status"] == "TESTING"
    r3 = client.post(f"/api/saved-videos/{vid}/archive")
    assert r3.status_code == 200
    assert r3.json()["archived_at"] is not None
    r4 = client.post(f"/api/saved-videos/{vid}/restore")
    assert r4.status_code == 200
    assert r4.json()["archived_at"] is None


def main() -> None:
    test_save_video_and_family()
    test_duplicate_save_idempotent()
    test_refresh_appends_observation()
    test_video_absent_from_attention_still_observation()
    test_family_absence_semantics()
    test_frozen_channel_relative_and_youtube_url()
    test_observation_payload_preserves_winner_channel_relative()
    test_api_history_pagination()
    test_api_patch_does_not_mutate_frozen()
    test_api_patch_and_archive()
    print("OK saved research 1.22C tests")


if __name__ == "__main__":
    main()
