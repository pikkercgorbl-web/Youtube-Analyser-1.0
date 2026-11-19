"""Stage 1.22C — Saved Topics / Watchlist regression tests (isolated SQLite DB)."""

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
from app.api.routes import saved_topics as saved_topics_routes
from app.models.db import Base, get_db
from app.models.orm import SavedTopic, SavedTopicObservation
from app.services.attention_engine_types import (
    AttentionEngineResult,
    AttentionSummary,
    PatternCandidate,
    PatternFamily,
    VideoWinner,
    youtube_watch_url,
)
from app.services.attention_read_model import persist_attention_result
from app.services.saved_topics import (
    FAMILY_ABSENCE_MESSAGE,
    append_saved_topic_observations_for_result,
    save_topic,
)

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


def _winner(video_id: str = "vid-a") -> VideoWinner:
    return VideoWinner(
        video_id=video_id,
        title="Title",
        channel_id="ch-a",
        channel_title="Channel A",
        youtube_url=youtube_watch_url(video_id),
        published_at=NOW,
        age_hours=12.0,
        views=1000,
        vph=80.0,
        subscribers=None,
        breakout_rank=1,
        breakout_eligible=True,
        channel_relative_signal=None,
        acceleration_state="unavailable",
        delayed_outcome_state="pending",
        delayed_outcome_growth=None,
        reason_codes=("breakout_high_rank",),
        human_reasons=("breakout_v1 rank 1",),
        keyword_ids=(1,),
    )


def _pattern() -> PatternCandidate:
    return PatternCandidate(
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
    )


def _family() -> PatternFamily:
    return PatternFamily(
        family_key="family:test:one",
        label="ai npc family",
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


def _result(*, run_id: str, stamp: datetime = NOW, include_family: bool = True) -> AttentionEngineResult:
    families = (_family(),) if include_family else ()
    return AttentionEngineResult(
        summary=AttentionSummary(
            run_id=run_id,
            computed_at=stamp,
            timezone_name="UTC",
            window_hours=24,
            window_start=stamp,
            window_end=stamp,
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
        video_winners=(_winner(),),
        patterns=(_pattern(),),
        channels=(),
        families=families,
    )


def _api_client(session: Session) -> TestClient:
    app = FastAPI()
    app.include_router(saved_topics_routes.router, prefix="/api/saved-topics")

    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_save_and_initial_observation_atomic() -> None:
    session = _session()
    persist_attention_result(session, _result(run_id="run_a"), run_id="run_a")
    session.commit()
    outcome = save_topic(session, family_key="family:test:one")
    session.commit()
    assert outcome.created
    obs_count = session.scalar(
        select(func.count()).select_from(SavedTopicObservation).where(
            SavedTopicObservation.saved_topic_id == outcome.topic.id,
        ),
    )
    assert obs_count == 1


def test_duplicate_save_idempotent() -> None:
    session = _session()
    persist_attention_result(session, _result(run_id="run_a"), run_id="run_a")
    session.commit()
    first = save_topic(session, family_key="family:test:one")
    session.commit()
    frozen = first.topic.frozen_snapshot_json
    second = save_topic(session, family_key="family:test:one")
    session.commit()
    assert second.idempotent
    assert second.topic.frozen_snapshot_json == frozen


def test_frozen_unchanged_after_refresh() -> None:
    session = _session()
    persist_attention_result(session, _result(run_id="run_a"), run_id="run_a")
    session.commit()
    saved = save_topic(session, family_key="family:test:one")
    session.commit()
    frozen_before = saved.topic.frozen_snapshot_json
    stamp_b = NOW.replace(hour=13)
    persist_attention_result(session, _result(run_id="run_b", stamp=stamp_b), run_id="run_b")
    session.commit()
    topic = session.get(SavedTopic, saved.topic.id)
    assert topic is not None
    assert topic.frozen_snapshot_json == frozen_before
    obs_count = session.scalar(
        select(func.count()).select_from(SavedTopicObservation).where(
            SavedTopicObservation.saved_topic_id == topic.id,
        ),
    )
    assert obs_count == 2


def test_history_survives_snapshot_replacement() -> None:
    session = _session()
    persist_attention_result(session, _result(run_id="run_a"), run_id="run_a")
    session.commit()
    save_topic(session, family_key="family:test:one")
    session.commit()
    persist_attention_result(session, _result(run_id="run_b", stamp=NOW.replace(hour=14)), run_id="run_b")
    session.commit()
    run_ids = session.scalars(select(SavedTopicObservation.attention_run_id)).all()
    assert set(run_ids) == {"run_a", "run_b"}


def test_no_duplicate_observation_same_run() -> None:
    session = _session()
    result = _result(run_id="run_a")
    persist_attention_result(session, result, run_id="run_a")
    session.commit()
    save_topic(session, family_key="family:test:one")
    session.commit()
    append_saved_topic_observations_for_result(session, run_id="run_a", result=result)
    session.commit()
    count = session.scalar(select(func.count()).select_from(SavedTopicObservation))
    assert count == 1


def test_absence_not_zero_counts() -> None:
    session = _session()
    persist_attention_result(session, _result(run_id="run_a"), run_id="run_a")
    session.commit()
    save_topic(session, family_key="family:test:one")
    session.commit()
    persist_attention_result(
        session,
        _result(run_id="run_b", stamp=NOW.replace(hour=15), include_family=False),
        run_id="run_b",
    )
    session.commit()
    latest = session.scalars(
        select(SavedTopicObservation).order_by(SavedTopicObservation.captured_at.desc()),
    ).first()
    assert latest is not None
    payload = json.loads(latest.payload_json)
    assert payload["present_in_snapshot"] is False
    assert payload["absence_message"] == FAMILY_ABSENCE_MESSAGE
    assert "counts" not in payload


def test_archive_restore() -> None:
    session = _session()
    persist_attention_result(session, _result(run_id="run_a"), run_id="run_a")
    session.commit()
    saved = save_topic(session, family_key="family:test:one")
    session.commit()
    saved.topic.archived_at = NOW
    session.commit()
    persist_attention_result(session, _result(run_id="run_b", stamp=NOW.replace(hour=16)), run_id="run_b")
    session.commit()
    count_after_archive = session.scalar(select(func.count()).select_from(SavedTopicObservation))
    assert count_after_archive == 1
    from app.services.saved_topics import restore_topic

    restore_topic(session, saved.topic.id)
    session.commit()
    topic = session.get(SavedTopic, saved.topic.id)
    assert topic is not None
    assert topic.archived_at is None
    count_after_restore = session.scalar(select(func.count()).select_from(SavedTopicObservation))
    assert count_after_restore == 2


def test_observation_failure_rolls_back_publication() -> None:
    from app.models.orm import AttentionRun

    session = _session()
    persist_attention_result(session, _result(run_id="run_a"), run_id="run_a")
    session.commit()
    save_topic(session, family_key="family:test:one")
    session.commit()
    with patch(
        "app.services.attention_read_model.append_saved_topic_observations_for_result",
        side_effect=RuntimeError("observation failed"),
    ):
        try:
            persist_attention_result(session, _result(run_id="run_b", stamp=NOW.replace(hour=17)), run_id="run_b")
            session.commit()
            raised = False
        except RuntimeError:
            session.rollback()
            raised = True
    assert raised
    run = session.scalar(select(AttentionRun))
    assert run is not None
    assert run.run_id == "run_a"


def test_api_save_and_list() -> None:
    session = _session()
    persist_attention_result(session, _result(run_id="run_api"), run_id="run_api")
    session.commit()
    client = _api_client(session)
    response = client.post("/api/saved-topics", json={"family_key": "family:test:one"})
    assert response.status_code == 200
    body = response.json()
    assert body["created"] is True
    listed = client.get("/api/saved-topics")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1


def main() -> None:
    tests = [
        test_save_and_initial_observation_atomic,
        test_duplicate_save_idempotent,
        test_frozen_unchanged_after_refresh,
        test_history_survives_snapshot_replacement,
        test_no_duplicate_observation_same_run,
        test_absence_not_zero_counts,
        test_archive_restore,
        test_observation_failure_rolls_back_publication,
        test_api_save_and_list,
    ]
    for test in tests:
        test()
        print(f"OK {test.__name__}")
    print(f"All {len(tests)} saved-topics tests passed.")


if __name__ == "__main__":
    main()
