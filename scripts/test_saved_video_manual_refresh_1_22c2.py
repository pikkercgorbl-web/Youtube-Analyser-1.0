"""Stage 1.22C.2 — manual SavedVideo metrics refresh tests."""

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
from app.api.deps import get_youtube_client
from app.api.routes import saved_research as saved_research_routes
from app.integrations.youtube.client import YouTubeVideoDetails
from app.models.db import Base, get_db
from app.models.orm import SavedVideo, SavedVideoObservation, Video, VideoSnapshot
from app.services.saved_research import save_video
from app.services.saved_video_manual_refresh import (
    MANUAL_SAVED_VIDEO_REFRESH_SOURCE,
    MANUAL_RUN_ID_PREFIX,
    refresh_saved_video_metrics,
)
from scripts.test_saved_research_1_22c import (
    _persist_run,
    _seed_video_corpus,
)

UTC = timezone.utc
T0 = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
T1 = T0 + timedelta(minutes=1)


class _MockYt:
    def __init__(self, *, by_id: dict[str, YouTubeVideoDetails] | None = None, fail: bool = False) -> None:
        self.by_id = by_id or {}
        self.fail = fail
        self.calls: list[list[str]] = []

    def get_videos(self, video_ids: list[str]) -> list[YouTubeVideoDetails]:
        self.calls.append(list(video_ids))
        if self.fail:
            raise RuntimeError("youtube down")
        return [self.by_id[v] for v in video_ids if v in self.by_id]


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _details(views: int = 90000) -> YouTubeVideoDetails:
    return YouTubeVideoDetails(
        video_id="vid-a",
        channel_id="ch-a",
        title="Title",
        published_at=T0 - timedelta(hours=24),
        duration_seconds=600,
        views_count=views,
        likes_count=10,
        comments_count=2,
    )


def _api_client(engine, *, youtube: _MockYt | None = None) -> TestClient:
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
    if youtube is not None:
        app.dependency_overrides[get_youtube_client] = lambda: youtube
    return TestClient(app)


def test_successful_manual_refresh() -> None:
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    _seed_video_corpus(db)
    _persist_run(db, "attention_run_1")
    db.close()

    client = _api_client(engine)
    vid = client.post("/api/saved-videos", json={"video_id": "vid-a"}).json()["item"]["id"]
    frozen_before = client.get(f"/api/saved-videos/{vid}").json()["frozen_snapshot"]

    refresh_client = _api_client(engine, youtube=_MockYt(by_id={"vid-a": _details(95000)}))
    with patch("app.services.revisit_executor.utc_now", return_value=T1):
        r = refresh_client.post(f"/api/saved-videos/{vid}/refresh-metrics", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["metrics_source"] == "youtube_data_api"
    assert body["capture_run_id"].startswith(MANUAL_RUN_ID_PREFIX)
    assert body["item"]["live_observation"]["views"] == 95000
    assert body["item"]["live_observation"]["breakout_rank"] is None
    assert body["item"]["live_observation"]["delayed_outcome_state"] is None
    assert body["item"]["frozen_snapshot"] == frozen_before

    db = SessionLocal()
    snap = db.scalar(
        select(VideoSnapshot).where(VideoSnapshot.source == MANUAL_SAVED_VIDEO_REFRESH_SOURCE),
    )
    assert snap is not None
    assert snap.run_id == body["capture_run_id"]
    obs_count = db.scalar(select(func.count()).select_from(SavedVideoObservation))
    assert obs_count == 2
    db.close()


def test_missing_video_in_youtube_response() -> None:
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    _seed_video_corpus(db)
    _persist_run(db, "attention_run_1")
    db.close()
    client = _api_client(engine)
    vid = client.post("/api/saved-videos", json={"video_id": "vid-a"}).json()["item"]["id"]
    refresh_client = _api_client(engine, youtube=_MockYt(by_id={}))
    r = refresh_client.post(f"/api/saved-videos/{vid}/refresh-metrics", json={})
    assert r.status_code == 404
    db = SessionLocal()
    assert db.scalar(select(func.count()).select_from(VideoSnapshot)) == 0
    db.close()


def test_youtube_error_rollback() -> None:
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    _seed_video_corpus(db)
    _persist_run(db, "attention_run_1")
    db.close()
    client = _api_client(engine)
    vid = client.post("/api/saved-videos", json={"video_id": "vid-a"}).json()["item"]["id"]
    refresh_client = _api_client(engine, youtube=_MockYt(fail=True))
    r = refresh_client.post(f"/api/saved-videos/{vid}/refresh-metrics", json={})
    assert r.status_code == 502
    db = SessionLocal()
    assert db.scalar(select(func.count()).select_from(VideoSnapshot)) == 0
    assert db.scalar(select(func.count()).select_from(SavedVideoObservation)) == 1
    db.close()


def test_idempotent_same_capture_run_id() -> None:
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    _seed_video_corpus(db)
    _persist_run(db, "attention_run_1")
    db.close()
    client = _api_client(engine)
    vid = client.post("/api/saved-videos", json={"video_id": "vid-a"}).json()["item"]["id"]
    run_id = f"{MANUAL_RUN_ID_PREFIX}test_idempotent_1"
    mock = _MockYt(by_id={"vid-a": _details()})
    refresh_client = _api_client(engine, youtube=mock)
    with patch("app.services.revisit_executor.utc_now", return_value=T1):
        r1 = refresh_client.post(
            f"/api/saved-videos/{vid}/refresh-metrics",
            json={"capture_run_id": run_id},
        )
        r2 = refresh_client.post(
            f"/api/saved-videos/{vid}/refresh-metrics",
            json={"capture_run_id": run_id},
        )
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r2.json()["idempotent"] is True
    assert len(mock.calls) == 1
    db = SessionLocal()
    assert db.scalar(select(func.count()).select_from(SavedVideoObservation)) == 2
    db.close()


def test_cooldown() -> None:
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    _seed_video_corpus(db)
    _persist_run(db, "attention_run_1")
    db.close()
    client = _api_client(engine)
    vid = client.post("/api/saved-videos", json={"video_id": "vid-a"}).json()["item"]["id"]
    mock = _MockYt(by_id={"vid-a": _details()})
    refresh_client = _api_client(engine, youtube=mock)
    with patch("app.services.revisit_executor.utc_now", return_value=T1):
        assert refresh_client.post(f"/api/saved-videos/{vid}/refresh-metrics", json={}).status_code == 200
    with patch("app.services.saved_video_manual_refresh.utc_now", return_value=T1 + timedelta(minutes=2)):
        r = refresh_client.post(f"/api/saved-videos/{vid}/refresh-metrics", json={})
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_persistence_failure_rollback() -> None:
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    _seed_video_corpus(db)
    _persist_run(db, "attention_run_1")
    save_video(db, video_id="vid-a")
    db.commit()
    saved = db.scalars(select(SavedVideo)).first()
    assert saved is not None
    saved_id = saved.id
    frozen = saved.frozen_payload_json
    db.close()

    db = SessionLocal()
    mock = _MockYt(by_id={"vid-a": _details()})
    with patch("app.services.revisit_executor.utc_now", return_value=T1):
        with patch(
            "app.services.saved_video_manual_refresh._apply_video_observation_row",
            side_effect=RuntimeError("obs write failed"),
        ):
            try:
                refresh_saved_video_metrics(db, saved_id, mock)
                db.commit()
            except RuntimeError:
                db.rollback()
    db.close()

    db = SessionLocal()
    assert db.scalar(select(func.count()).select_from(VideoSnapshot)) == 0
    row = db.get(SavedVideo, saved_id)
    assert row is not None
    assert row.frozen_payload_json == frozen
    db.close()


def test_history_includes_manual_and_attention() -> None:
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    _seed_video_corpus(db)
    _persist_run(db, "attention_run_1")
    db.close()
    client = _api_client(engine)
    vid = client.post("/api/saved-videos", json={"video_id": "vid-a"}).json()["item"]["id"]
    refresh_client = _api_client(engine, youtube=_MockYt(by_id={"vid-a": _details(88000)}))
    with patch("app.services.revisit_executor.utc_now", return_value=T1):
        refresh_client.post(f"/api/saved-videos/{vid}/refresh-metrics", json={})
    hist = client.get(f"/api/saved-videos/{vid}/history").json()
    assert hist["total"] == 2
    kinds = {row["payload"].get("observation_kind") for row in hist["items"]}
    assert MANUAL_SAVED_VIDEO_REFRESH_SOURCE in kinds
    assert None in kinds or "manual_saved_video_refresh" in kinds


def main() -> None:
    test_successful_manual_refresh()
    test_missing_video_in_youtube_response()
    test_youtube_error_rollback()
    test_idempotent_same_capture_run_id()
    test_cooldown()
    test_persistence_failure_rollback()
    test_history_includes_manual_and_attention()
    print("OK saved video manual refresh 1.22C.2 tests")


if __name__ == "__main__":
    main()
