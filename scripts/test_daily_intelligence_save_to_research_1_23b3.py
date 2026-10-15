"""Stage 1.23B.3 — Daily Intelligence save-to-research tests."""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
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
from app.api.routes import daily_intelligence as daily_intelligence_routes
from app.models.db import Base, get_db
from app.models.orm import (
    Channel,
    DailyIntelligenceReport,
    DailyIntelligenceReportFamilyFinding,
    DailyIntelligenceReportWinnerFinding,
    SavedFamily,
    SavedFamilyObservation,
    SavedVideo,
    SavedVideoObservation,
    Video,
)
from app.services.attention_engine_types import video_winner_to_dict, pattern_family_to_dict, VideoWinner, PatternFamily, youtube_watch_url
from app.services.saved_research import archive_video, save_video
from app.services.saved_research_daily_intelligence import (
    DAILY_INTELLIGENCE_SAVE_ANCHOR_KIND,
    save_family_from_daily_intelligence,
    save_video_from_daily_intelligence,
)
from app.services.metrics import ensure_utc
from app.services.saved_research_validation import compute_video_validation, measurement_source_for_video

UTC = timezone.utc
REPORT_DATE = date(2026, 10, 10)
RUN_ID = "attention_20261010T140809Z"
COMPUTED = datetime(2026, 10, 10, 14, 8, 9, tzinfo=UTC)


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


def _winner(video_id: str = "hist-vid-1") -> VideoWinner:
    return VideoWinner(
        video_id=video_id,
        title="Historical Title",
        channel_id="ch-1",
        channel_title="Channel One",
        youtube_url=youtube_watch_url(video_id),
        published_at=COMPUTED,
        age_hours=10.0,
        views=50000,
        vph=4000.0,
        subscribers=12000,
        breakout_rank=12,
        breakout_eligible=True,
        channel_relative_signal=None,
        acceleration_state="stable",
        delayed_outcome_state="pending",
        delayed_outcome_growth=None,
        reason_codes=("high_current_vph",),
        human_reasons=("historical reason",),
        keyword_ids=(42,),
    )


def _family(family_key: str = "family:hist:1") -> PatternFamily:
    return PatternFamily(
        family_key=family_key,
        label="Historical Family",
        family_kind="keyword_provenance",
        member_pattern_keys=("pat:1",),
        member_labels=("kw group",),
        video_ids=("hist-vid-1",),
        channel_ids=("ch-1",),
        keyword_ids=(99,),
        video_count=3,
        channel_count=2,
        keyword_count=1,
        breakout_eligible_count=1,
        videos_last_24h=2,
        videos_previous_24h=1,
        videos_previous_48_24h=0,
        grouping_reasons=("shared keyword",),
        quality_flags=("keyword_only",),
        support_sources=("keyword_provenance",),
        first_seen_at=COMPUTED,
        latest_seen_at=COMPUTED,
    )


def _seed_di(session: Session) -> None:
    session.add(
        Channel(id="ch-1", title="Channel One", subscribers_count=12000, created_at=COMPUTED),
    )
    session.add(
        Video(
            id="hist-vid-1",
            channel_id="ch-1",
            title="Historical Title",
            views_count=50000,
            published_at=COMPUTED,
        ),
    )
    session.add(
        DailyIntelligenceReport(
            report_date=REPORT_DATE,
            status="provisional",
            source_run_id=RUN_ID,
            source_computed_at=COMPUTED,
            generated_at=COMPUTED,
            publish_attempt=1,
        ),
    )
    w = _winner()
    session.add(
        DailyIntelligenceReportWinnerFinding(
            report_date=REPORT_DATE,
            video_id=w.video_id,
            rank=1,
            title=w.title,
            channel_id=w.channel_id,
            channel_title=w.channel_title,
            youtube_url=w.youtube_url,
            discovery_provenance_json=json.dumps({"available": True, "keyword_id": 42}),
            payload_json=json.dumps(video_winner_to_dict(w), ensure_ascii=False),
        ),
    )
    f = _family()
    session.add(
        DailyIntelligenceReportFamilyFinding(
            report_date=REPORT_DATE,
            family_key=f.family_key,
            rank=1,
            label=f.label,
            video_count=f.video_count,
            channel_count=f.channel_count,
            payload_json=json.dumps(pattern_family_to_dict(f), ensure_ascii=False),
        ),
    )
    session.commit()


def _client(session_factory) -> TestClient:
    app = FastAPI()
    app.include_router(daily_intelligence_routes.router, prefix="/api/daily-intelligence")

    def override_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_historical_winner_without_live_attention() -> None:
    SessionLocal = sessionmaker(bind=_engine())
    session = SessionLocal()
    _seed_di(session)
    with patch("app.services.saved_research._load_attention_snapshot", return_value=None):
        result = save_video_from_daily_intelligence(
            session,
            report_date=REPORT_DATE,
            video_id="hist-vid-1",
        )
        session.commit()
    assert result.created is True
    frozen = json.loads(result.item.frozen_payload_json)
    assert frozen["context"]["decision_source"]["kind"] == "daily_intelligence"
    assert frozen["context"]["decision_source"]["report_date"] == "2026-10-10"
    assert frozen["evidence"]["views"] == 50000
    obs = session.scalars(
        select(SavedVideoObservation).where(SavedVideoObservation.saved_video_id == result.item.id),
    ).all()
    assert len(obs) == 1
    payload = json.loads(obs[0].payload_json)
    assert payload["observation_kind"] == DAILY_INTELLIGENCE_SAVE_ANCHOR_KIND
    assert obs[0].video_present_in_attention is False
    assert obs[0].delayed_outcome_state is None
    assert ensure_utc(obs[0].observed_at) == COMPUTED
    assert measurement_source_for_video(obs[0]) == "daily_intelligence_anchor"
    session.close()


def test_historical_family_without_live_attention() -> None:
    SessionLocal = sessionmaker(bind=_engine())
    session = SessionLocal()
    _seed_di(session)
    with patch("app.services.saved_research._load_attention_snapshot", return_value=None):
        result = save_family_from_daily_intelligence(
            session,
            report_date=REPORT_DATE,
            family_key="family:hist:1",
        )
        session.commit()
    assert result.created is True
    frozen = json.loads(result.item.frozen_payload_json)
    assert frozen["family"]["video_count"] == 3
    assert frozen["context"]["decision_source"]["rank_at_save"] == 1
    obs = session.scalars(
        select(SavedFamilyObservation).where(SavedFamilyObservation.saved_family_id == result.item.id),
    ).all()
    assert len(obs) == 1
    assert json.loads(obs[0].payload_json)["observation_kind"] == DAILY_INTELLIGENCE_SAVE_ANCHOR_KIND
    assert obs[0].family_present is False
    session.close()


def test_idempotent_and_archived_409() -> None:
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    _seed_di(session)
    save_video_from_daily_intelligence(session, report_date=REPORT_DATE, video_id="hist-vid-1")
    session.commit()
    second = save_video_from_daily_intelligence(session, report_date=REPORT_DATE, video_id="hist-vid-1")
    assert second.idempotent is True
    archive_video(session, second.item.id)
    session.commit()
    client = _client(SessionLocal)
    res = client.post(
        f"/api/daily-intelligence/reports/{REPORT_DATE.isoformat()}/winners/hist-vid-1/save-to-research",
    )
    assert res.status_code == 409
    session.close()


def test_missing_finding_404() -> None:
    SessionLocal = sessionmaker(bind=_engine())
    session = SessionLocal()
    _seed_di(session)
    client = _client(SessionLocal)
    res = client.post(
        f"/api/daily-intelligence/reports/{REPORT_DATE.isoformat()}/winners/missing/save-to-research",
    )
    assert res.status_code == 404
    session.close()


def test_frozen_compatible_with_validation() -> None:
    SessionLocal = sessionmaker(bind=_engine())
    session = SessionLocal()
    _seed_di(session)
    result = save_video_from_daily_intelligence(session, report_date=REPORT_DATE, video_id="hist-vid-1")
    session.commit()
    frozen = json.loads(result.item.frozen_payload_json)
    obs = session.scalar(
        select(SavedVideoObservation).where(SavedVideoObservation.saved_video_id == result.item.id),
    )
    report = compute_video_validation(
        frozen=frozen,
        live=obs,
        saved_at=result.item.saved_at,
        observation_count=1,
    )
    assert report["delayed_72h_state"] is None
    assert report["latest_measurement_source"] == "daily_intelligence_anchor"
    session.close()


def test_live_save_unchanged() -> None:
    """Opportunities save path still uses attention snapshot when patched."""
    from app.services.attention_engine_types import AttentionEngineResult, AttentionSummary

    SessionLocal = sessionmaker(bind=_engine())
    session = SessionLocal()
    session.add(Channel(id="ch-a", title="A", subscribers_count=1, created_at=COMPUTED))
    session.add(
        Video(id="vid-a", channel_id="ch-a", title="T", views_count=1, published_at=COMPUTED),
    )
    session.commit()
    w = _winner("vid-a")
    summary = AttentionSummary(
        run_id="live-run",
        computed_at=COMPUTED,
        timezone_name="UTC",
        window_hours=24,
        window_start=COMPUTED,
        window_end=COMPUTED,
        source="test",
        candidate_video_count=1,
        winner_count=1,
        pattern_count=0,
        channel_momentum_count=0,
        video_limit=50,
        pattern_limit=20,
        channel_limit=20,
        notes={},
    )
    live = AttentionEngineResult(summary=summary, video_winners=(w,), patterns=(), channels=(), families=())
    with patch("app.services.saved_research._load_attention_snapshot", return_value=live):
        r = save_video(session, video_id="vid-a")
        session.commit()
    assert r.created is True
    frozen = json.loads(r.item.frozen_payload_json)
    assert frozen["context"].get("decision_source") is None
    session.close()


def main() -> None:
    test_historical_winner_without_live_attention()
    test_historical_family_without_live_attention()
    test_idempotent_and_archived_409()
    test_missing_finding_404()
    test_frozen_compatible_with_validation()
    test_live_save_unchanged()
    print("OK: test_daily_intelligence_save_to_research_1_23b3")


if __name__ == "__main__":
    main()
