"""Product Fix 1A — unified research portfolio (SQLite fixtures only)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.models.orm import (
    SavedFamily,
    SavedFamilyObservation,
    SavedResearchEvent,
    SavedResearchFeedback,
    SavedTopic,
    SavedVideo,
    SavedVideoObservation,
)
from app.models.db import get_db
from app.services.research_portfolio_report import (
    NEW_ANALYTICAL_OBSERVATION_IN_PERIOD_DEFINITION,
    build_research_portfolio_report,
)
from app.services.saved_research_daily_intelligence import DAILY_INTELLIGENCE_SAVE_ANCHOR_KIND
from app.services.saved_research_decisions import record_status_change
from app.services.saved_topic_validation import build_validation_report
from app.services.saved_topics import patch_topic

UTC = timezone.utc
T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
T_SAVE = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
T_DECISION = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
T_AFTER = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


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


def _video(
    session: Session,
    *,
    saved_at: datetime,
    video_id: str = "vid-portfolio-1",
    archived_at: datetime | None = None,
) -> SavedVideo:
    row = SavedVideo(
        video_id=video_id,
        saved_at=saved_at,
        status="WATCHING",
        notes="",
        tags_json="[]",
        frozen_title="Portfolio Video",
        frozen_channel_id="ch1",
        frozen_channel_title="Channel",
        frozen_payload_json=json.dumps({"identity": {"title": "Portfolio Video"}, "evidence": {"views": 100}}),
        created_at=saved_at,
        updated_at=saved_at,
        archived_at=archived_at,
    )
    session.add(row)
    session.flush()
    row.latest_observed_at = saved_at
    session.add(
        SavedVideoObservation(
            saved_video_id=row.id,
            attention_run_id="run-1",
            observed_at=saved_at,
            video_present_in_attention=True,
            monitoring_snapshot_available=True,
            views=100,
            vph=1.0,
            payload_json="{}",
        ),
    )
    return row


def _family(session: Session, *, key: str, saved_at: datetime, archived_at: datetime | None = None) -> SavedFamily:
    row = SavedFamily(
        family_key=key,
        saved_at=saved_at,
        status="WATCHING",
        notes="",
        tags_json="[]",
        frozen_label=f"Label {key}",
        frozen_kind="keyword",
        frozen_payload_json=json.dumps(
            {"family": {"label": key, "video_count": 2, "channel_count": 1, "family_kind": "keyword"}},
        ),
        created_at=saved_at,
        updated_at=saved_at,
        archived_at=archived_at,
    )
    session.add(row)
    session.flush()
    session.add(
        SavedFamilyObservation(
            saved_family_id=row.id,
            attention_run_id="run-1",
            observed_at=saved_at,
            family_present=True,
            video_count=2,
            channel_count=1,
            payload_json="{}",
        ),
    )
    row.latest_observed_at = saved_at
    return row


def _append_video_obs(
    session: Session,
    *,
    saved_video_id: int,
    observed_at: datetime,
    run_id: str = "run-follow-up",
    payload: dict | None = None,
) -> None:
    session.add(
        SavedVideoObservation(
            saved_video_id=saved_video_id,
            attention_run_id=run_id,
            observed_at=observed_at,
            video_present_in_attention=True,
            monitoring_snapshot_available=True,
            views=200,
            vph=2.0,
            payload_json=json.dumps(payload or {"attention_run_id": run_id}),
        ),
    )


def _append_family_obs(
    session: Session,
    *,
    saved_family_id: int,
    observed_at: datetime,
    run_id: str = "run-follow-up",
    payload: dict | None = None,
) -> None:
    session.add(
        SavedFamilyObservation(
            saved_family_id=saved_family_id,
            attention_run_id=run_id,
            observed_at=observed_at,
            family_present=True,
            video_count=3,
            channel_count=1,
            payload_json=json.dumps(payload or {}),
        ),
    )


def test_combined_total_three_no_topics() -> None:
    session = _session()
    _video(session, saved_at=T_SAVE)
    _family(session, key="family:a", saved_at=T_SAVE)
    _family(session, key="family:b", saved_at=T_SAVE)
    session.commit()
    legacy = build_validation_report(session, period_start=None, period_end=None)
    portfolio = build_research_portfolio_report(
        session,
        period_start=None,
        period_end=None,
        legacy_topics_saved_in_period=legacy["topics_saved_in_period"],
    )
    assert portfolio["saved_in_period"]["combined_total"] == 3
    assert portfolio["saved_in_period"]["videos"] == 1
    assert portfolio["saved_in_period"]["families"] == 2
    video_item = next(i for i in portfolio["saved_in_period_items"] if i["kind"] == "video")
    assert video_item["video_id"] == "vid-portfolio-1"
    assert video_item["latest_observed_at"] is not None


def test_save_before_period_decision_inside_period() -> None:
    session = _session()
    video = _video(session, saved_at=T0)
    session.commit()
    record_status_change(
        session,
        entity_kind="video",
        entity_id=video.id,
        previous="WATCHING",
        new="TESTING",
    )
    for ev in session.scalars(select(SavedResearchEvent)):
        ev.occurred_at = T_DECISION
    session.commit()
    period_start = datetime(2026, 10, 9, tzinfo=UTC)
    period_end = datetime(2026, 10, 11, tzinfo=UTC)
    legacy = build_validation_report(session, period_start=period_start, period_end=period_end)
    portfolio = build_research_portfolio_report(
        session,
        period_start=period_start,
        period_end=period_end,
        legacy_topics_saved_in_period=legacy["topics_saved_in_period"],
    )
    assert portfolio["saved_in_period"]["videos"] == 0
    assert portfolio["decisions_in_period"]["status_changed_events"] == 1
    assert portfolio["decisions_in_period"]["status_transition_events"]["to_TESTING"] == 1


def test_save_inside_period_decision_after_period() -> None:
    session = _session()
    video = _video(session, saved_at=T_SAVE)
    session.commit()
    record_status_change(
        session,
        entity_kind="video",
        entity_id=video.id,
        previous="WATCHING",
        new="WANT_TO_TEST",
    )
    for ev in session.scalars(select(SavedResearchEvent)):
        ev.occurred_at = T_AFTER
    session.commit()
    period_start = datetime(2026, 10, 1, tzinfo=UTC)
    period_end = datetime(2026, 10, 15, tzinfo=UTC)
    portfolio = build_research_portfolio_report(
        session,
        period_start=period_start,
        period_end=period_end,
        legacy_topics_saved_in_period=0,
    )
    assert portfolio["saved_in_period"]["videos"] == 1
    assert portfolio["decisions_in_period"]["status_changed_events"] == 0


def test_archived_still_in_saved_cohort() -> None:
    session = _session()
    archived_at = T_AFTER
    _family(session, key="family:arch", saved_at=T_SAVE, archived_at=archived_at)
    session.commit()
    portfolio = build_research_portfolio_report(
        session,
        period_start=None,
        period_end=None,
        legacy_topics_saved_in_period=0,
    )
    assert portfolio["saved_in_period"]["families"] == 1
    assert portfolio["current_status_counts"].get("ARCHIVED") == 1


def test_legacy_topic_backward_compat() -> None:
    session = _session()
    topic = SavedTopic(
        family_key="family:legacy",
        status="WATCHING",
        notes="",
        tags_json="[]",
        frozen_snapshot_json=json.dumps({"family": {"family_kind": "keyword", "support_sources": ["keyword"]}}),
        created_at=T_SAVE,
        updated_at=T_SAVE,
    )
    session.add(topic)
    session.flush()
    patch_topic(session, topic.id, status="TESTING")
    session.commit()
    legacy = build_validation_report(session, period_start=None, period_end=None)
    assert legacy["topics_saved_in_period"] == 1
    assert legacy["status_transition_events"]["to_TESTING"] == 1
    portfolio = build_research_portfolio_report(
        session,
        period_start=None,
        period_end=None,
        legacy_topics_saved_in_period=legacy["topics_saved_in_period"],
    )
    assert portfolio["saved_in_period"]["legacy_topics"] == 1
    assert portfolio["saved_in_period"]["combined_total"] == 1


def test_feedback_counts_no_double_entity() -> None:
    session = _session()
    video = _video(session, saved_at=T_SAVE)
    session.add(
        SavedResearchFeedback(
            entity_kind="video",
            entity_id=video.id,
            verdict="USEFUL",
            reason="ok",
            created_at=T_SAVE,
        ),
    )
    session.commit()
    portfolio = build_research_portfolio_report(
        session,
        period_start=None,
        period_end=None,
        legacy_topics_saved_in_period=0,
    )
    assert portfolio["latest_feedback"]["cohort_with_latest_feedback"] == 1
    assert portfolio["latest_feedback"]["research_verdict_distribution"]["USEFUL"] == 1
    assert portfolio["portfolio_hints"]["has_decisions_in_period"] is True


def test_api_response_includes_portfolio_and_legacy_fields() -> None:
    session = _session()
    _video(session, saved_at=T_SAVE)
    session.commit()

    def _override_db():
        yield session

    from fastapi.testclient import TestClient

    from app.main import app

    app.dependency_overrides[get_db] = _override_db
    client = TestClient(app)
    try:
        resp = client.get("/api/validation/report")
        assert resp.status_code == 200
        data = resp.json()
        assert "topics_saved_in_period" in data
        assert data["research_portfolio"]["saved_in_period"]["videos"] == 1
    finally:
        app.dependency_overrides.clear()


def test_query_count_bounded() -> None:
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    for i in range(8):
        _video(session, saved_at=T_SAVE + timedelta(hours=i), video_id=f"vid-portfolio-{i}")
        _family(session, key=f"family:{i}", saved_at=T_SAVE + timedelta(hours=i))
    session.commit()

    count = {"n": 0}

    def _before(_conn, _cursor, _statement, _parameters, _context, _executemany):
        count["n"] += 1

    event.listen(engine, "before_cursor_execute", _before)
    try:
        legacy = build_validation_report(session, period_start=None, period_end=None)
        build_research_portfolio_report(
            session,
            period_start=None,
            period_end=None,
            legacy_topics_saved_in_period=legacy["topics_saved_in_period"],
        )
    finally:
        event.remove(engine, "before_cursor_execute", _before)

    assert count["n"] < 25, f"expected batched queries, got {count['n']}"


def test_new_analytical_obs_family_saved_before_period() -> None:
    """Scenario 1: saved before period, follow-up observation inside period counts."""
    session = _session()
    family = _family(session, key="family:old", saved_at=T0)
    _append_family_obs(session, saved_family_id=family.id, observed_at=T_AFTER, run_id="run-2")
    session.commit()
    period_start = datetime(2026, 10, 15, tzinfo=UTC)
    period_end = datetime(2026, 10, 21, tzinfo=UTC)
    portfolio = build_research_portfolio_report(
        session,
        period_start=period_start,
        period_end=period_end,
        legacy_topics_saved_in_period=0,
    )
    assert portfolio["saved_in_period"]["families"] == 0
    assert portfolio["observations"]["cohort_with_new_analytical_observation_in_period"] == 1


def test_new_analytical_obs_initial_save_only_not_counted() -> None:
    """Scenario 2: only first analytical row at save — not a new measurement."""
    session = _session()
    _video(session, saved_at=T_SAVE)
    session.commit()
    portfolio = build_research_portfolio_report(
        session,
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 31, tzinfo=UTC),
        legacy_topics_saved_in_period=0,
    )
    assert portfolio["saved_in_period"]["videos"] == 1
    assert portfolio["observations"]["cohort_with_new_analytical_observation_in_period"] == 0


def test_new_analytical_obs_status_change_only() -> None:
    """Scenario 3: user status event without observation rows."""
    session = _session()
    video = _video(session, saved_at=T0)
    session.commit()
    record_status_change(
        session,
        entity_kind="video",
        entity_id=video.id,
        previous="WATCHING",
        new="TESTING",
    )
    for ev in session.scalars(select(SavedResearchEvent)):
        ev.occurred_at = T_AFTER
    session.commit()
    portfolio = build_research_portfolio_report(
        session,
        period_start=datetime(2026, 10, 15, tzinfo=UTC),
        period_end=datetime(2026, 10, 21, tzinfo=UTC),
        legacy_topics_saved_in_period=0,
    )
    assert portfolio["decisions_in_period"]["status_changed_events"] == 1
    assert portfolio["observations"]["cohort_with_new_analytical_observation_in_period"] == 0


def test_new_analytical_obs_duplicate_rows_one_entity() -> None:
    """Scenario 4: multiple in-period follow-ups still count once."""
    session = _session()
    video = _video(session, saved_at=T0)
    _append_video_obs(session, saved_video_id=video.id, observed_at=T_DECISION, run_id="run-2")
    _append_video_obs(session, saved_video_id=video.id, observed_at=T_AFTER, run_id="run-3")
    session.commit()
    portfolio = build_research_portfolio_report(
        session,
        period_start=datetime(2026, 10, 9, tzinfo=UTC),
        period_end=datetime(2026, 10, 21, tzinfo=UTC),
        legacy_topics_saved_in_period=0,
    )
    assert portfolio["observations"]["cohort_with_new_analytical_observation_in_period"] == 1


def test_new_analytical_obs_empty_period_and_mixed_cohort() -> None:
    """Scenario 5: null without bounds; video + family each with one follow-up."""
    session = _session()
    video = _video(session, saved_at=T0, video_id="vid-mix")
    family = _family(session, key="family:mix", saved_at=T0)
    _append_video_obs(session, saved_video_id=video.id, observed_at=T_AFTER, run_id="run-v2")
    _append_family_obs(session, saved_family_id=family.id, observed_at=T_AFTER, run_id="run-f2")
    session.commit()
    all_time = build_research_portfolio_report(
        session,
        period_start=None,
        period_end=None,
        legacy_topics_saved_in_period=0,
    )
    assert all_time["observations"]["cohort_with_new_analytical_observation_in_period"] is None

    bounded = build_research_portfolio_report(
        session,
        period_start=datetime(2026, 10, 15, tzinfo=UTC),
        period_end=datetime(2026, 10, 21, tzinfo=UTC),
        legacy_topics_saved_in_period=0,
    )
    assert bounded["observations"]["cohort_with_new_analytical_observation_in_period"] == 2


def test_daily_intelligence_anchor_excluded_from_new_analytical() -> None:
    session = _session()
    video = _video(session, saved_at=T0)
    _append_video_obs(
        session,
        saved_video_id=video.id,
        observed_at=T_AFTER,
        run_id="di-anchor-only",
        payload={"observation_kind": DAILY_INTELLIGENCE_SAVE_ANCHOR_KIND},
    )
    session.commit()
    portfolio = build_research_portfolio_report(
        session,
        period_start=datetime(2026, 10, 15, tzinfo=UTC),
        period_end=datetime(2026, 10, 21, tzinfo=UTC),
        legacy_topics_saved_in_period=0,
    )
    assert portfolio["observations"]["cohort_with_new_analytical_observation_in_period"] == 0
    assert "saved_video_observations" in NEW_ANALYTICAL_OBSERVATION_IN_PERIOD_DEFINITION
    assert "archived" in NEW_ANALYTICAL_OBSERVATION_IN_PERIOD_DEFINITION.lower()


def test_observation_kind_sqlite_uses_json_extract() -> None:
    from sqlalchemy import func, select
    from sqlalchemy.dialects import sqlite

    from app.models.orm import SavedVideoObservation
    from app.services.research_portfolio_report import _observation_kind_expr

    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        kind = _observation_kind_expr(session, SavedVideoObservation.payload_json)
        sql = str(
            select(kind)
            .limit(1)
            .compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}),
        )
    assert "json_extract" in sql


def main() -> None:
    tests = [
        test_combined_total_three_no_topics,
        test_save_before_period_decision_inside_period,
        test_save_inside_period_decision_after_period,
        test_archived_still_in_saved_cohort,
        test_legacy_topic_backward_compat,
        test_feedback_counts_no_double_entity,
        test_api_response_includes_portfolio_and_legacy_fields,
        test_query_count_bounded,
        test_new_analytical_obs_family_saved_before_period,
        test_new_analytical_obs_initial_save_only_not_counted,
        test_new_analytical_obs_status_change_only,
        test_new_analytical_obs_duplicate_rows_one_entity,
        test_new_analytical_obs_empty_period_and_mixed_cohort,
        test_daily_intelligence_anchor_excluded_from_new_analytical,
        test_observation_kind_sqlite_uses_json_extract,
    ]
    for test in tests:
        test()
        print(f"OK {test.__name__}")
    print(f"All {len(tests)} Fix 1A tests passed.")


if __name__ == "__main__":
    main()
