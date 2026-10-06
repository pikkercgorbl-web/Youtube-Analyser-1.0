"""Stage 1.22B — pattern detail hydrate is snapshot read-path only."""

from __future__ import annotations

import sys
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes import attention as attention_routes
from app.models.db import get_db
from app.services.attention_engine_types import AttentionEngineConfig
from app.services.attention_read_model import refresh_attention_engine
from scripts.test_attention_engine_1_22a import NOW, _engine, _seed_pair


def test_pattern_detail_hydrates_members_without_recompute() -> None:
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
    listed = client.get("/api/attention/patterns")
    assert listed.json()["data_source"] == "snapshot"
    items = listed.json()["items"]
    assert items
    key = items[0]["pattern_key"]
    with patch("app.api.routes.attention.compute_attention_engine") as live:
        detail = client.get(f"/api/attention/patterns/{key}")
        families = client.get("/api/attention/pattern-families")
        live.assert_not_called()
    body = detail.json()
    assert body["data_source"] == "snapshot"
    assert families.json()["data_source"] == "snapshot"
    assert families.json()["items"]
    body = detail.json()
    assert body["data_source"] == "snapshot"
    assert body["pattern"]["pattern_key"] == key
    assert len(body["videos"]) == body["pattern"]["video_count"]
    assert {row["video_id"] for row in body["videos"]} == set(body["pattern"]["participating_video_ids"])
    assert all(row["youtube_url"].startswith("https://www.youtube.com/watch?v=") for row in body["videos"])
    assert "channels" in body
    assert "related_keywords" in body
