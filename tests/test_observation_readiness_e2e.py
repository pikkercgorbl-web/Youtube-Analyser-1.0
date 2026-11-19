"""Full Saved Topics / observation API path on dedicated PostgreSQL test DB (Stage 1.22 readiness)."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

import app.models.orm  # noqa: F401
from app.api.routes import saved_topics as saved_topics_routes
from app.api.routes import validation as validation_routes
from app.models.db import Base, get_db
from app.models.orm import SavedTopic, SavedTopicEvent, SavedTopicFeedback, SavedTopicObservation
from app.services.attention_engine_types import (
    AttentionEngineResult,
    AttentionSummary,
    PatternCandidate,
    PatternFamily,
)
from app.services.attention_read_model import persist_attention_result

UTC = timezone.utc
NOW = datetime(2026, 10, 6, 16, 0, tzinfo=UTC)
FAMILY_KEY = "family:e2e:readiness"


def _resolve_test_url() -> str:
    url = os.environ.get("SAVED_TOPICS_POSTGRES_TEST_URL", "").strip()
    if not url:
        base = os.environ.get("DATABASE_URL", "").strip()
        if base and "/" in base:
            url = base.rsplit("/", 1)[0] + "/youtube_radar_saved_topics_test"
    if not url or "test" not in url.lower():
        raise SystemExit("Refusing: set SAVED_TOPICS_POSTGRES_TEST_URL to a dedicated test database.")
    prod = os.environ.get("DATABASE_URL", "")
    if prod and prod.rstrip("/") == url.rstrip("/"):
        raise SystemExit("Test URL must not equal production DATABASE_URL")
    return url


def _engine(url: str):
    engine = create_engine(url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    from app.db.migrations import ensure_saved_topics_1_22d_tables, ensure_saved_topics_tables

    ensure_saved_topics_tables(engine)
    ensure_saved_topics_1_22d_tables(engine)
    return engine


def _reset(session: Session) -> None:
    session.execute(
        text(
            "TRUNCATE saved_topic_observations, saved_topic_events, saved_topic_feedback "
            "RESTART IDENTITY CASCADE",
        ),
    )
    session.execute(text("TRUNCATE saved_topics RESTART IDENTITY CASCADE"))
    session.execute(
        text(
            "TRUNCATE attention_pattern_family_videos, attention_pattern_family_members, "
            "attention_pattern_families, attention_pattern_videos, attention_patterns, "
            "attention_video_winners, attention_channel_momentum, attention_runs RESTART IDENTITY CASCADE",
        ),
    )
    session.commit()


def _family() -> PatternFamily:
    return PatternFamily(
        family_key=FAMILY_KEY,
        label="e2e readiness family",
        family_kind="title_phrase",
        member_pattern_keys=("phrase:e2e",),
        member_labels=("e2e",),
        video_ids=("vid-e2e",),
        channel_ids=("ch-e2e",),
        keyword_ids=(1,),
        video_count=3,
        channel_count=2,
        keyword_count=1,
        breakout_eligible_count=1,
        videos_last_24h=1,
        videos_previous_24h=1,
        videos_previous_48_24h=0,
        grouping_reasons=("singleton",),
        quality_flags=(),
        support_sources=("title_phrase",),
        first_seen_at=NOW,
        latest_seen_at=NOW,
    )


def _result(*, run_id: str, video_count: int = 3) -> AttentionEngineResult:
    fam = _family()
    if video_count != fam.video_count:
        fam = replace(
            fam,
            video_count=video_count,
            video_ids=tuple(f"vid-{i}" for i in range(video_count)),
        )
    return AttentionEngineResult(
        summary=AttentionSummary(
            run_id=run_id,
            computed_at=NOW,
            timezone_name="UTC",
            window_hours=24,
            window_start=NOW,
            window_end=NOW,
            source="snapshot",
            candidate_video_count=video_count,
            winner_count=0,
            pattern_count=1,
            channel_momentum_count=0,
            video_limit=50,
            pattern_limit=20,
            channel_limit=20,
            notes={},
        ),
        video_winners=(),
        patterns=(
            PatternCandidate(
                pattern_key="phrase:e2e",
                kind="title_phrase",
                label="e2e",
                video_count=video_count,
                channel_count=2,
                keyword_count=1,
                breakout_video_count=0,
                small_channel_winner_count=0,
                first_seen_at=NOW,
                latest_seen_at=NOW,
                videos_last_24h=1,
                videos_previous_24h=1,
                videos_previous_48_24h=0,
                participating_video_ids=tuple(f"vid-{i}" for i in range(video_count)),
                participating_channel_ids=("ch-e2e", "ch-e2e-b"),
                participating_keyword_ids=(1,),
                reason_codes=(),
                human_reasons=(),
            ),
        ),
        channels=(),
        families=(fam,),
    )


def _client(session: Session) -> TestClient:
    app = FastAPI()
    app.include_router(saved_topics_routes.router, prefix="/api/saved-topics")
    app.include_router(validation_routes.router, prefix="/api/validation")

    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def run_e2e(session: Session) -> None:
    persist_attention_result(session, _result(run_id="e2e_run_a"), run_id="e2e_run_a")
    session.commit()
    client = _client(session)

    save = client.post("/api/saved-topics", json={"family_key": FAMILY_KEY})
    assert save.status_code == 200, save.text
    body = save.json()
    assert body["created"] is True
    topic_id = body["item"]["id"]
    frozen_at_save = json.dumps(body["item"]["frozen_snapshot"], sort_keys=True)
    obs0 = session.scalar(select(func.count()).select_from(SavedTopicObservation))
    assert obs0 == 1

    patch = client.patch(f"/api/saved-topics/{topic_id}", json={"status": "WANT_TO_TEST"})
    assert patch.status_code == 200
    events = session.scalar(
        select(func.count()).select_from(SavedTopicEvent).where(SavedTopicEvent.event_type == "status_changed"),
    )
    assert events == 1

    fb = client.post(
        f"/api/saved-topics/{topic_id}/feedback",
        json={
            "finding_rating": "USEFUL",
            "reason_comment": "e2e smoke",
            "own_test_outcome": "UNKNOWN",
        },
    )
    assert fb.status_code == 200
    fb_count = session.scalar(select(func.count()).select_from(SavedTopicFeedback))
    assert fb_count == 1

    report = client.get("/api/validation/report")
    assert report.status_code == 200
    assert report.json()["topics_saved_in_period"] >= 1

    archive = client.post(f"/api/saved-topics/{topic_id}/archive")
    assert archive.status_code == 200
    assert archive.json()["archived_at"] is not None

    persist_attention_result(session, _result(run_id="e2e_run_b", video_count=5), run_id="e2e_run_b")
    session.commit()
    obs_mid = session.scalar(select(func.count()).select_from(SavedTopicObservation))
    assert obs_mid == 1, "archived topic must not get observation on refresh"

    restore = client.post(f"/api/saved-topics/{topic_id}/restore")
    assert restore.status_code == 200
    assert restore.json()["archived_at"] is None

    persist_attention_result(session, _result(run_id="e2e_run_c", video_count=5), run_id="e2e_run_c")
    session.commit()
    obs_final = session.scalar(select(func.count()).select_from(SavedTopicObservation))
    assert obs_final == 3, f"expected 3 observations, got {obs_final}"

    dup_attempt = session.scalar(
        select(func.count())
        .select_from(SavedTopicObservation)
        .where(
            SavedTopicObservation.saved_topic_id == topic_id,
            SavedTopicObservation.attention_run_id == "e2e_run_a",
        ),
    )
    assert dup_attempt == 1

    topic = session.get(SavedTopic, topic_id)
    assert topic is not None
    frozen_after = json.dumps(json.loads(topic.frozen_snapshot_json), sort_keys=True)
    assert frozen_after == frozen_at_save

    timeline = client.get(f"/api/saved-topics/{topic_id}/timeline")
    assert timeline.status_code == 200
    kinds = {item["kind"] for item in timeline.json()["items"]}
    assert "observation" in kinds
    assert "event" in kinds

    detail = client.get(f"/api/saved-topics/{topic_id}")
    assert detail.status_code == 200
    live = detail.json().get("live_observation") or {}
    payload = live.get("payload") or {}
    assert payload.get("present_in_snapshot") is True
    counts = payload.get("counts") or {}
    assert counts.get("video_count") == 5
    deltas = detail.json().get("count_deltas")
    assert deltas is not None
    assert deltas.get("video_count") == 2


def test_observation_failure_rolls_back(session: Session) -> None:
    persist_attention_result(session, _result(run_id="e2e_fail_a"), run_id="e2e_fail_a")
    session.commit()
    client = _client(session)
    client.post("/api/saved-topics", json={"family_key": FAMILY_KEY})
    session.commit()
    with patch(
        "app.services.attention_read_model.append_saved_topic_observations_for_result",
        side_effect=RuntimeError("observation failed"),
    ):
        try:
            persist_attention_result(session, _result(run_id="e2e_fail_b"), run_id="e2e_fail_b")
            session.commit()
            raise AssertionError("expected rollback path")
        except RuntimeError:
            session.rollback()
    from app.models.orm import AttentionRun

    run = session.scalar(select(AttentionRun))
    assert run is not None
    assert run.run_id == "e2e_fail_a"


def main() -> None:
    url = _resolve_test_url()
    engine = _engine(url)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    _reset(session)
    run_e2e(session)
    print("OK full API path e2e")
    _reset(session)
    test_observation_failure_rolls_back(session)
    print("OK observation failure rollback")
    session.close()
    print(f"Observation readiness E2E passed on {url.split('@')[-1]}")


if __name__ == "__main__":
    main()
