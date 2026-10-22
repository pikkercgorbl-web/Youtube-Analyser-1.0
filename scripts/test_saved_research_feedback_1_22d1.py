"""Stage 1.22D.1 — Saved Research feedback & validation tests."""

from __future__ import annotations

import json
import sys
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
from app.api.routes import saved_research as saved_research_routes
from app.integrations.youtube.client import YouTubeVideoDetails
from app.models.db import Base, get_db
from app.models.orm import SavedResearchEvent, SavedVideo, SavedVideoObservation
from app.services.saved_research import save_video
from app.services.saved_research_validation import compute_video_validation, observation_is_manual
from app.services.saved_video_manual_refresh import MANUAL_RUN_ID_PREFIX
from scripts.test_saved_research_1_22c import _persist_run, _seed_video_corpus

UTC = timezone.utc
T0 = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _client(engine) -> TestClient:
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
    return TestClient(app)


def test_decision_events_on_save_and_patch() -> None:
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    _seed_video_corpus(db)
    _persist_run(db, "attention_run_1")
    db.close()

    client = _client(engine)
    vid = client.post("/api/saved-videos", json={"video_id": "vid-a"}).json()["item"]["id"]
    events = client.get(f"/api/saved-videos/{vid}/decision-events").json()
    assert events["total"] >= 1
    assert any(e["event_type"] == "saved" for e in events["items"])

    client.patch(f"/api/saved-videos/{vid}", json={"status": "TESTING"})
    types = [e["event_type"] for e in client.get(f"/api/saved-videos/{vid}/decision-events").json()["items"]]
    assert "status_changed" in types

    client.post(f"/api/saved-videos/{vid}/archive")
    types = [e["event_type"] for e in client.get(f"/api/saved-videos/{vid}/decision-events").json()["items"]]
    assert "archived" in types
    client.post(f"/api/saved-videos/{vid}/restore")
    types = [e["event_type"] for e in client.get(f"/api/saved-videos/{vid}/decision-events").json()["items"]]
    assert "restored" in types


def test_patch_rollback_no_orphan_events() -> None:
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    _seed_video_corpus(db)
    _persist_run(db, "attention_run_1")
    save_video(db, video_id="vid-a")
    db.commit()
    saved_id = db.scalars(select(SavedVideo)).first().id
    before = db.scalar(select(func.count()).select_from(SavedResearchEvent))
    db.close()

    db = SessionLocal()
    from app.services.saved_research import patch_video

    try:
        with patch("app.services.saved_research.validate_notes", side_effect=ValueError("bad notes")):
            patch_video(db, saved_id, notes="x")
            db.commit()
    except ValueError:
        db.rollback()
    db.close()

    db = SessionLocal()
    after = db.scalar(select(func.count()).select_from(SavedResearchEvent))
    assert after == before
    db.close()


def test_video_validation_growth_and_identical() -> None:
    frozen = {"evidence": {"views": 1000, "vph": 100.0}}
    live = SavedVideoObservation(
        saved_video_id=1,
        attention_run_id="attention_run_2",
        observed_at=T0 + timedelta(hours=24),
        video_present_in_attention=True,
        monitoring_snapshot_available=True,
        views=1500,
        vph=120.0,
        subscriber_count=100,
        family_keys_json="[]",
        reason_codes_json="[]",
        payload_json='{"observation_kind": "attention"}',
    )
    v = compute_video_validation(
        frozen=frozen,
        live=live,
        saved_at=T0,
        observation_count=2,
    )
    assert v["view_delta"] == 500
    assert v["evidence_state"] == "validated"

    live2 = SavedVideoObservation(
        saved_video_id=1,
        attention_run_id="manual_saved_video_refresh:x",
        observed_at=T0 + timedelta(hours=1),
        video_present_in_attention=False,
        monitoring_snapshot_available=True,
        views=1000,
        vph=100.0,
        subscriber_count=None,
        family_keys_json="[]",
        reason_codes_json="[]",
        payload_json=json.dumps({"observation_kind": "manual_saved_video_refresh"}),
    )
    assert observation_is_manual(live2)
    v2 = compute_video_validation(frozen=frozen, live=live2, saved_at=T0, observation_count=2)
    assert v2["view_delta"] == 0
    assert v2["delayed_72h_state"] is None


def test_feedback_overview_pagination() -> None:
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    _seed_video_corpus(db)
    _persist_run(db, "attention_run_1")
    db.close()
    client = _client(engine)
    client.post("/api/saved-videos", json={"video_id": "vid-a"})
    r = client.get("/api/saved-research/feedback-overview", params={"video_limit": 1, "video_offset": 0})
    assert r.status_code == 200
    body = r.json()
    assert "evidence_summary" in body
    assert body["videos"]["total"] >= 1
    assert len(body["videos"]["items"]) <= 1


def main() -> None:
    test_decision_events_on_save_and_patch()
    test_patch_rollback_no_orphan_events()
    test_video_validation_growth_and_identical()
    test_feedback_overview_pagination()
    print("OK saved research feedback 1.22D.1 tests")


if __name__ == "__main__":
    main()
