"""Saved Topic user decisions, events, and feedback (Stage 1.22D)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.orm import SavedTopic, SavedTopicEvent, SavedTopicFeedback
from app.services.metrics import ensure_utc, utc_now

FindingRating = Literal["USEFUL", "NOT_USEFUL", "UNCLEAR"]
OwnTestOutcome = Literal["UNKNOWN", "BETTER", "AS_EXPECTED", "WORSE"]

MAX_FEEDBACK_COMMENT = 2000
MAX_FEEDBACK_URL = 512
MAX_MANUAL_METRIC_NOTES = 500

FINDING_RATINGS: frozenset[str] = frozenset({"USEFUL", "NOT_USEFUL", "UNCLEAR"})
OWN_TEST_OUTCOMES: frozenset[str] = frozenset({"UNKNOWN", "BETTER", "AS_EXPECTED", "WORSE"})

EventType = Literal["status_changed", "archived", "restored", "feedback_added"]


def _add_event(
    session: Session,
    *,
    topic: SavedTopic,
    event_type: EventType,
    payload: dict[str, Any],
    occurred_at: datetime | None = None,
) -> SavedTopicEvent:
    row = SavedTopicEvent(
        saved_topic_id=topic.id,
        occurred_at=occurred_at or utc_now(),
        event_type=event_type,
        payload_json=json.dumps(payload, ensure_ascii=False),
    )
    session.add(row)
    return row


def record_status_change(
    session: Session,
    topic: SavedTopic,
    *,
    previous: str,
    new: str,
) -> SavedTopicEvent | None:
    if previous == new:
        return None
    return _add_event(
        session,
        topic=topic,
        event_type="status_changed",
        payload={"previous_status": previous, "new_status": new},
    )


def record_archived(session: Session, topic: SavedTopic) -> SavedTopicEvent:
    return _add_event(session, topic=topic, event_type="archived", payload={})


def record_restored(session: Session, topic: SavedTopic) -> SavedTopicEvent:
    return _add_event(session, topic=topic, event_type="restored", payload={})


def validate_feedback_url(url: str | None) -> str | None:
    if url is None or not str(url).strip():
        return None
    text = str(url).strip()
    if len(text) > MAX_FEEDBACK_URL:
        raise ValueError(f"URL must be at most {MAX_FEEDBACK_URL} characters")
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("URL must use http or https with a host")
    return text


def validate_manual_metrics(raw: dict[str, Any] | None) -> dict[str, Any]:
    if not raw:
        return {}
    out: dict[str, Any] = {}
    if "measured_at" in raw and raw["measured_at"]:
        val = raw["measured_at"]
        if isinstance(val, datetime):
            out["measured_at"] = ensure_utc(val).isoformat()
        else:
            out["measured_at"] = ensure_utc(datetime.fromisoformat(str(val).replace("Z", "+00:00"))).isoformat()
    if "views" in raw and raw["views"] is not None:
        views = int(raw["views"])
        if views < 0:
            raise ValueError("views must be non-negative")
        out["views"] = views
    if "vph" in raw and raw["vph"] is not None:
        vph = float(raw["vph"])
        if vph < 0:
            raise ValueError("vph must be non-negative")
        out["vph"] = vph
    if "notes" in raw and raw["notes"]:
        notes = str(raw["notes"]).strip()
        if len(notes) > MAX_MANUAL_METRIC_NOTES:
            raise ValueError(f"manual metric notes must be at most {MAX_MANUAL_METRIC_NOTES} characters")
        out["notes"] = notes
    return out


def append_feedback(
    session: Session,
    topic_id: int,
    *,
    finding_rating: FindingRating,
    reason_comment: str = "",
    own_test_video_url: str | None = None,
    own_test_video_published_at: datetime | None = None,
    own_test_outcome: OwnTestOutcome = "UNKNOWN",
    manual_metrics: dict[str, Any] | None = None,
) -> SavedTopicFeedback | None:
    topic = session.get(SavedTopic, topic_id)
    if topic is None:
        return None
    rating = finding_rating.upper()
    if rating not in FINDING_RATINGS:
        raise ValueError("finding_rating must be USEFUL, NOT_USEFUL, or UNCLEAR")
    outcome = own_test_outcome.upper()
    if outcome not in OWN_TEST_OUTCOMES:
        raise ValueError("own_test_outcome must be UNKNOWN, BETTER, AS_EXPECTED, or WORSE")
    comment = reason_comment.strip()
    if len(comment) > MAX_FEEDBACK_COMMENT:
        raise ValueError(f"Comment must be at most {MAX_FEEDBACK_COMMENT} characters")
    url = validate_feedback_url(own_test_video_url)
    metrics = validate_manual_metrics(manual_metrics)
    published = ensure_utc(own_test_video_published_at) if own_test_video_published_at else None
    now = utc_now()
    row = SavedTopicFeedback(
        saved_topic_id=topic.id,
        recorded_at=now,
        finding_rating=rating,
        reason_comment=comment,
        own_test_video_url=url,
        own_test_video_published_at=published,
        own_test_outcome=outcome,
        manual_metrics_json=json.dumps(metrics, ensure_ascii=False),
    )
    session.add(row)
    session.flush()
    _add_event(
        session,
        topic=topic,
        event_type="feedback_added",
        payload={"feedback_id": row.id, "finding_rating": rating, "own_test_outcome": outcome},
        occurred_at=now,
    )
    topic.updated_at = now
    session.flush()
    return row


def latest_feedback_by_topic_ids(session: Session, topic_ids: list[int]) -> dict[int, SavedTopicFeedback]:
    if not topic_ids:
        return {}
    subq = (
        select(
            SavedTopicFeedback.saved_topic_id,
            func.max(SavedTopicFeedback.recorded_at).label("max_recorded"),
        )
        .where(SavedTopicFeedback.saved_topic_id.in_(topic_ids))
        .group_by(SavedTopicFeedback.saved_topic_id)
        .subquery()
    )
    rows = session.scalars(
        select(SavedTopicFeedback)
        .join(
            subq,
            (SavedTopicFeedback.saved_topic_id == subq.c.saved_topic_id)
            & (SavedTopicFeedback.recorded_at == subq.c.max_recorded),
        )
        .order_by(SavedTopicFeedback.id.desc()),
    ).all()
    out: dict[int, SavedTopicFeedback] = {}
    for row in rows:
        out.setdefault(row.saved_topic_id, row)
    return out


def list_feedback_history(
    session: Session,
    topic_id: int,
    *,
    limit: int,
    offset: int,
) -> tuple[list[SavedTopicFeedback], int]:
    total = session.scalar(
        select(func.count()).select_from(SavedTopicFeedback).where(SavedTopicFeedback.saved_topic_id == topic_id),
    )
    total = int(total or 0)
    rows = session.scalars(
        select(SavedTopicFeedback)
        .where(SavedTopicFeedback.saved_topic_id == topic_id)
        .order_by(SavedTopicFeedback.recorded_at.desc(), SavedTopicFeedback.id.desc())
        .offset(offset)
        .limit(limit),
    ).all()
    return list(rows), total


def list_events(
    session: Session,
    topic_id: int,
    *,
    limit: int,
    offset: int,
) -> tuple[list[SavedTopicEvent], int]:
    total = session.scalar(
        select(func.count()).select_from(SavedTopicEvent).where(SavedTopicEvent.saved_topic_id == topic_id),
    )
    total = int(total or 0)
    rows = session.scalars(
        select(SavedTopicEvent)
        .where(SavedTopicEvent.saved_topic_id == topic_id)
        .order_by(SavedTopicEvent.occurred_at.desc(), SavedTopicEvent.id.desc())
        .offset(offset)
        .limit(limit),
    ).all()
    return list(rows), total


def feedback_to_dict(row: SavedTopicFeedback) -> dict[str, Any]:
    try:
        metrics = json.loads(row.manual_metrics_json or "{}")
    except json.JSONDecodeError:
        metrics = {}
    return {
        "id": row.id,
        "recorded_at": ensure_utc(row.recorded_at).isoformat(),
        "finding_rating": row.finding_rating,
        "reason_comment": row.reason_comment,
        "own_test_video_url": row.own_test_video_url,
        "own_test_video_published_at": (
            ensure_utc(row.own_test_video_published_at).isoformat() if row.own_test_video_published_at else None
        ),
        "own_test_outcome": row.own_test_outcome,
        "manual_metrics": metrics,
    }


def event_to_dict(row: SavedTopicEvent) -> dict[str, Any]:
    try:
        payload = json.loads(row.payload_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    return {
        "id": row.id,
        "occurred_at": ensure_utc(row.occurred_at).isoformat(),
        "event_type": row.event_type,
        "payload": payload,
    }
