"""Stage 1.22D.2 — explicit analyst feedback tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.orm  # noqa: F401
from app.api.routes import saved_research as saved_research_routes
from app.models.db import Base, get_db
from app.models.orm import SavedResearchEvent, SavedResearchFeedback, SavedVideo, SavedVideoObservation
from app.services.saved_research import save_family, save_video
from app.services.saved_research_feedback import append_analyst_feedback
from scripts.test_saved_research_1_22c import _persist_run, _seed_video_corpus


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


def _seed(engine) -> tuple[TestClient, int, int]:
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    _seed_video_corpus(db)
    _persist_run(db, "attention_run_1")
    v = save_video(db, video_id="vid-a")
    f = save_family(db, family_key="family:test:one")
    db.commit()
    vid, fid = v.item.id, f.item.id
    db.close()
    return _client(engine), vid, fid


def test_append_only_and_latest_ordering() -> None:
    engine = _engine()
    client, vid, _ = _seed(engine)
    r1 = client.post(f"/api/saved-videos/{vid}/feedback", json={"verdict": "USEFUL", "reason": "a"})
    assert r1.status_code == 200
    r2 = client.post(
        f"/api/saved-videos/{vid}/feedback",
        json={"verdict": "NOT_RELEVANT", "reason": "b"},
    )
    assert r2.status_code == 200
    hist = client.get(f"/api/saved-videos/{vid}/feedback").json()
    assert hist["total"] == 2
    assert hist["latest"]["verdict"] == "NOT_RELEVANT"
    assert hist["items"][0]["verdict"] == "NOT_RELEVANT"
    assert hist["items"][1]["verdict"] == "USEFUL"


def test_video_family_isolation() -> None:
    engine = _engine()
    client, vid, fid = _seed(engine)
    client.post(f"/api/saved-videos/{vid}/feedback", json={"verdict": "USEFUL"})
    client.post(f"/api/saved-families/{fid}/feedback", json={"verdict": "TOO_BROAD"})
    vh = client.get(f"/api/saved-videos/{vid}/feedback").json()
    fh = client.get(f"/api/saved-families/{fid}/feedback").json()
    assert vh["total"] == 1 and vh["latest"]["verdict"] == "USEFUL"
    assert fh["total"] == 1 and fh["latest"]["verdict"] == "TOO_BROAD"


def test_pagination() -> None:
    engine = _engine()
    client, vid, _ = _seed(engine)
    for i in range(5):
        client.post(
            f"/api/saved-videos/{vid}/feedback",
            json={"verdict": "NEEDS_RESEARCH", "reason": f"n{i}"},
        )
    page = client.get(f"/api/saved-videos/{vid}/feedback", params={"limit": 2, "offset": 2}).json()
    assert page["total"] == 5
    assert page["limit"] == 2
    assert page["offset"] == 2
    assert len(page["items"]) == 2


def test_invalid_verdict_and_reason_length() -> None:
    engine = _engine()
    client, vid, _ = _seed(engine)
    bad = client.post(f"/api/saved-videos/{vid}/feedback", json={"verdict": "GREAT"})
    assert bad.status_code == 422
    long_reason = "x" * 1001
    bad2 = client.post(
        f"/api/saved-videos/{vid}/feedback",
        json={"verdict": "USEFUL", "reason": long_reason},
    )
    assert bad2.status_code == 422
    assert client.get(f"/api/saved-videos/{vid}/feedback").json()["total"] == 0


def test_archived_rejects_post_preserves_history() -> None:
    engine = _engine()
    client, vid, _ = _seed(engine)
    client.post(f"/api/saved-videos/{vid}/feedback", json={"verdict": "USEFUL"})
    client.post(f"/api/saved-videos/{vid}/archive")
    blocked = client.post(f"/api/saved-videos/{vid}/feedback", json={"verdict": "USEFUL"})
    assert blocked.status_code == 409
    hist = client.get(f"/api/saved-videos/{vid}/feedback").json()
    assert hist["total"] == 1


def test_feedback_rollback_no_rows() -> None:
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    _seed_video_corpus(db)
    _persist_run(db, "attention_run_1")
    save_video(db, video_id="vid-a")
    db.commit()
    saved_id = db.scalars(select(SavedVideo)).first().id
    db.close()

    db = SessionLocal()
    try:
        append_analyst_feedback(
            db,
            entity_kind="video",
            entity_id=saved_id,
            verdict="INVALID",
        )
        db.commit()
    except ValueError:
        db.rollback()
    db.close()

    db = SessionLocal()
    count = db.scalar(select(func.count()).select_from(SavedResearchFeedback))
    assert count == 0
    db.close()


def test_no_mutation_frozen_observations_status() -> None:
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    _seed_video_corpus(db)
    _persist_run(db, "attention_run_1")
    save_video(db, video_id="vid-a")
    db.commit()
    row = db.scalars(select(SavedVideo)).first()
    saved_id = row.id
    frozen_before = row.frozen_payload_json
    status_before = row.status
    obs_before = db.scalar(select(func.count()).select_from(SavedVideoObservation))
    events_before = db.scalar(select(func.count()).select_from(SavedResearchEvent))
    db.close()

    client = _client(engine)
    client.post(f"/api/saved-videos/{saved_id}/feedback", json={"verdict": "USEFUL", "reason": "ok"})

    db = SessionLocal()
    row = db.get(SavedVideo, saved_id)
    assert row.frozen_payload_json == frozen_before
    assert row.status == status_before
    obs_after = db.scalar(select(func.count()).select_from(SavedVideoObservation))
    events_after = db.scalar(select(func.count()).select_from(SavedResearchEvent))
    assert obs_after == obs_before
    assert events_after == events_before
    db.close()


def test_list_includes_latest_verdict() -> None:
    engine = _engine()
    client, vid, fid = _seed(engine)
    client.post(f"/api/saved-videos/{vid}/feedback", json={"verdict": "NOISE_OR_DUPLICATE"})
    client.post(f"/api/saved-families/{fid}/feedback", json={"verdict": "NEEDS_RESEARCH"})
    vlist = client.get("/api/saved-videos").json()["items"]
    flist = client.get("/api/saved-families").json()["items"]
    vrow = next(x for x in vlist if x["id"] == vid)
    frow = next(x for x in flist if x["id"] == fid)
    assert vrow["latest_analyst_verdict"] == "NOISE_OR_DUPLICATE"
    assert frow["latest_analyst_verdict"] == "NEEDS_RESEARCH"


def main() -> None:
    test_append_only_and_latest_ordering()
    test_video_family_isolation()
    test_pagination()
    test_invalid_verdict_and_reason_length()
    test_archived_rejects_post_preserves_history()
    test_feedback_rollback_no_rows()
    test_no_mutation_frozen_observations_status()
    test_list_includes_latest_verdict()
    print("OK saved research feedback 1.22D.2 tests")


if __name__ == "__main__":
    main()
