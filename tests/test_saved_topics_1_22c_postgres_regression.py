"""1.22C PostgreSQL regression on a dedicated test database only."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.models.orm import AttentionRun, SavedTopic, SavedTopicObservation
from app.services.attention_engine_types import (
    AttentionEngineResult,
    AttentionSummary,
    PatternCandidate,
    PatternFamily,
    VideoWinner,
    youtube_watch_url,
)
from app.services.attention_read_model import persist_attention_result
from app.services.saved_topics import save_topic

UTC = timezone.utc
NOW = datetime(2026, 10, 6, 15, 0, tzinfo=UTC)


def _resolve_test_url() -> str:
    url = os.environ.get("SAVED_TOPICS_POSTGRES_TEST_URL", "").strip()
    if not url:
        base = os.environ.get("DATABASE_URL", "").strip()
        if base and "/" in base:
            url = base.rsplit("/", 1)[0] + "/youtube_radar_saved_topics_test"
    if not url:
        raise SystemExit(
            "Set SAVED_TOPICS_POSTGRES_TEST_URL to a dedicated PostgreSQL test database "
            "(name must contain 'test').",
        )
    lowered = url.lower()
    if "saved_topics_test" not in lowered and "_test" not in lowered and "test_" not in lowered:
        raise SystemExit(f"Refusing non-test database URL: {url}")
    prod = os.environ.get("DATABASE_URL", "")
    if prod and url.split("@")[-1] == prod.split("@")[-1]:
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
    session.execute(text("TRUNCATE saved_topic_observations, saved_topic_events, saved_topic_feedback RESTART IDENTITY CASCADE"))
    session.execute(text("TRUNCATE saved_topics RESTART IDENTITY CASCADE"))
    session.execute(text("TRUNCATE attention_pattern_family_videos, attention_pattern_family_members RESTART IDENTITY CASCADE"))
    session.execute(text("TRUNCATE attention_pattern_families, attention_pattern_videos RESTART IDENTITY CASCADE"))
    session.execute(text("TRUNCATE attention_patterns, attention_video_winners, attention_channel_momentum RESTART IDENTITY CASCADE"))
    session.execute(text("TRUNCATE attention_runs RESTART IDENTITY CASCADE"))
    session.commit()


def _family() -> PatternFamily:
    return PatternFamily(
        family_key="family:pg:test",
        label="pg family",
        family_kind="title_phrase",
        member_pattern_keys=("phrase:pg",),
        member_labels=("pg",),
        video_ids=("vid-pg",),
        channel_ids=("ch-pg",),
        keyword_ids=(1,),
        video_count=1,
        channel_count=1,
        keyword_count=1,
        breakout_eligible_count=0,
        videos_last_24h=1,
        videos_previous_24h=0,
        videos_previous_48_24h=0,
        grouping_reasons=(),
        quality_flags=(),
        support_sources=("title_phrase",),
        first_seen_at=NOW,
        latest_seen_at=NOW,
    )


def _result(*, run_id: str, include_family: bool = True) -> AttentionEngineResult:
    families = (_family(),) if include_family else ()
    return AttentionEngineResult(
        summary=AttentionSummary(
            run_id=run_id,
            computed_at=NOW,
            timezone_name="UTC",
            window_hours=24,
            window_start=NOW,
            window_end=NOW,
            source="snapshot",
            candidate_video_count=1,
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
                pattern_key="phrase:pg",
                kind="title_phrase",
                label="pg",
                video_count=1,
                channel_count=1,
                keyword_count=1,
                breakout_video_count=0,
                small_channel_winner_count=0,
                first_seen_at=NOW,
                latest_seen_at=NOW,
                videos_last_24h=1,
                videos_previous_24h=0,
                videos_previous_48_24h=0,
                participating_video_ids=("vid-pg",),
                participating_channel_ids=("ch-pg",),
                participating_keyword_ids=(1,),
                reason_codes=(),
                human_reasons=(),
            ),
        ),
        channels=(),
        families=families,
    )


def test_observation_failure_rolls_back_replacement(session: Session) -> None:
    persist_attention_result(session, _result(run_id="pg_run_a"), run_id="pg_run_a")
    session.commit()
    save_topic(session, family_key="family:pg:test")
    session.commit()
    with patch(
        "app.services.attention_read_model.append_saved_topic_observations_for_result",
        side_effect=RuntimeError("observation failed"),
    ):
        try:
            persist_attention_result(session, _result(run_id="pg_run_b"), run_id="pg_run_b")
            session.commit()
            raise AssertionError("expected failure")
        except RuntimeError:
            session.rollback()
    run = session.scalar(select(AttentionRun))
    assert run is not None
    assert run.run_id == "pg_run_a"


def test_frozen_and_history_survive_replacement(session: Session) -> None:
    persist_attention_result(session, _result(run_id="pg_run_a"), run_id="pg_run_a")
    session.commit()
    saved = save_topic(session, family_key="family:pg:test")
    session.commit()
    frozen = saved.topic.frozen_snapshot_json
    persist_attention_result(session, _result(run_id="pg_run_b"), run_id="pg_run_b")
    session.commit()
    topic = session.get(SavedTopic, saved.topic.id)
    assert topic is not None
    assert topic.frozen_snapshot_json == frozen
    run_ids = set(session.scalars(select(SavedTopicObservation.attention_run_id)).all())
    assert run_ids == {"pg_run_a", "pg_run_b"}


def test_unique_observation_per_run(session: Session) -> None:
    persist_attention_result(session, _result(run_id="pg_run_a"), run_id="pg_run_a")
    session.commit()
    saved = save_topic(session, family_key="family:pg:test")
    session.commit()
    topic_id = saved.topic.id
    session.add(
        SavedTopicObservation(
            saved_topic_id=topic_id,
            attention_run_id="pg_run_a",
            captured_at=NOW,
            payload_json="{}",
        ),
    )
    try:
        session.commit()
        raise AssertionError("expected IntegrityError")
    except IntegrityError:
        session.rollback()


def main() -> None:
    url = _resolve_test_url()
    engine = _engine(url)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    _reset(session)
    tests = [
        test_observation_failure_rolls_back_replacement,
        test_frozen_and_history_survive_replacement,
        test_unique_observation_per_run,
    ]
    for test in tests:
        test(session)
        _reset(session)
        print(f"OK {test.__name__}")
    session.close()
    print(f"PostgreSQL regression OK on {url.split('@')[-1]}")


if __name__ == "__main__":
    main()
