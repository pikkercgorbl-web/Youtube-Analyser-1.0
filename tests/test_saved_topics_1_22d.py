"""Stage 1.22D — events, feedback, validation (SQLite)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.models.orm import SavedTopic, SavedTopicEvent, SavedTopicFeedback
from app.services.saved_topic_decisions import append_feedback
from app.services.saved_topic_validation import build_validation_report
from app.services.saved_topics import archive_topic, patch_topic, restore_topic

UTC = timezone.utc
NOW = datetime(2026, 10, 6, 14, 0, tzinfo=UTC)


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


def _topic(session: Session) -> SavedTopic:
    topic = SavedTopic(
        family_key="family:test:feedback",
        status="WATCHING",
        notes="",
        tags_json="[]",
        frozen_snapshot_json=json.dumps(
            {
                "family": {
                    "label": "Test",
                    "family_kind": "title_phrase",
                    "support_sources": ["title_phrase", "keyword"],
                },
            },
        ),
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(topic)
    session.flush()
    return topic


def test_status_event_atomic_and_no_duplicate_same_status() -> None:
    session = _session()
    topic = _topic(session)
    patch_topic(session, topic.id, status="WANT_TO_TEST")
    session.commit()
    events = session.scalars(select(SavedTopicEvent).where(SavedTopicEvent.saved_topic_id == topic.id)).all()
    assert len(events) == 1
    assert events[0].event_type == "status_changed"
    patch_topic(session, topic.id, status="WANT_TO_TEST")
    session.commit()
    count = session.scalar(select(func.count()).select_from(SavedTopicEvent))
    assert count == 1


def test_archive_restore_events() -> None:
    session = _session()
    topic = _topic(session)
    session.commit()
    archive_topic(session, topic.id)
    session.commit()
    restore_topic(session, topic.id)
    session.commit()
    types = session.scalars(select(SavedTopicEvent.event_type).order_by(SavedTopicEvent.id.asc())).all()
    assert types == ["archived", "restored"]


def test_feedback_append_only_and_event() -> None:
    session = _session()
    topic = _topic(session)
    session.commit()
    first = append_feedback(session, topic.id, finding_rating="USEFUL", reason_comment="helpful")
    second = append_feedback(session, topic.id, finding_rating="NOT_USEFUL", reason_comment="changed mind")
    session.commit()
    assert first is not None and second is not None
    assert first.id != second.id
    fb_count = session.scalar(select(func.count()).select_from(SavedTopicFeedback))
    assert fb_count == 2
    ev_count = session.scalar(
        select(func.count()).select_from(SavedTopicEvent).where(SavedTopicEvent.event_type == "feedback_added"),
    )
    assert ev_count == 2


def test_feedback_url_validation() -> None:
    session = _session()
    topic = _topic(session)
    session.commit()
    try:
        append_feedback(session, topic.id, finding_rating="UNCLEAR", own_test_video_url="not-a-url")
        raise AssertionError("expected ValueError")
    except ValueError:
        session.rollback()


def test_validation_report_counts() -> None:
    session = _session()
    topic = _topic(session)
    session.commit()
    patch_topic(session, topic.id, status="TESTING")
    append_feedback(
        session,
        topic.id,
        finding_rating="USEFUL",
        own_test_video_url="https://www.youtube.com/watch?v=abc",
        own_test_outcome="BETTER",
    )
    session.commit()
    report = build_validation_report(session, period_start=None, period_end=None)
    assert report["topics_saved_in_period"] == 1
    assert report["status_transition_events"]["to_TESTING"] == 1
    assert report["latest_finding_rating_distribution"]["USEFUL"] == 1
    assert report["topics_with_known_own_test_outcome"] == 1


def main() -> None:
    tests = [
        test_status_event_atomic_and_no_duplicate_same_status,
        test_archive_restore_events,
        test_feedback_append_only_and_event,
        test_feedback_url_validation,
        test_validation_report_counts,
    ]
    for test in tests:
        test()
        print(f"OK {test.__name__}")
    print(f"All {len(tests)} Stage 1.22D tests passed.")


if __name__ == "__main__":
    main()
