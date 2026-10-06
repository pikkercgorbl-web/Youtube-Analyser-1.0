"""Read-only validation report for Saved Topics (Stage 1.22D)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.orm import SavedTopic, SavedTopicEvent
from app.services.saved_topic_decisions import latest_feedback_by_topic_ids
from app.services.saved_topics import count_deltas, latest_observations_by_topic_ids


def build_validation_report(
    session: Session,
    *,
    period_start: datetime | None,
    period_end: datetime | None,
) -> dict[str, Any]:
    """
    Aggregates persisted saved-topic data only. No Attention recompute.
    """
    topic_stmt = select(SavedTopic)
    if period_start is not None:
        topic_stmt = topic_stmt.where(SavedTopic.created_at >= period_start)
    if period_end is not None:
        topic_stmt = topic_stmt.where(SavedTopic.created_at <= period_end)
    topics = list(session.scalars(topic_stmt).all())
    topic_ids = [t.id for t in topics]

    current_status_counts: dict[str, int] = {}
    for topic in topics:
        if topic.archived_at is not None:
            key = "ARCHIVED"
        else:
            key = topic.status
        current_status_counts[key] = current_status_counts.get(key, 0) + 1

    events: list[SavedTopicEvent] = []
    if topic_ids:
        event_stmt = select(SavedTopicEvent).where(SavedTopicEvent.saved_topic_id.in_(topic_ids))
        if period_start is not None:
            event_stmt = event_stmt.where(SavedTopicEvent.occurred_at >= period_start)
        if period_end is not None:
            event_stmt = event_stmt.where(SavedTopicEvent.occurred_at <= period_end)
        events = list(session.scalars(event_stmt).all())

    transition_event_counts = {
        "to_WANT_TO_TEST": 0,
        "to_TESTING": 0,
        "to_DROPPED": 0,
    }
    for event in events:
        if event.event_type != "status_changed":
            continue
        try:
            payload = json.loads(event.payload_json or "{}")
        except json.JSONDecodeError:
            continue
        new_status = payload.get("new_status")
        if new_status == "WANT_TO_TEST":
            transition_event_counts["to_WANT_TO_TEST"] += 1
        elif new_status == "TESTING":
            transition_event_counts["to_TESTING"] += 1
        elif new_status == "DROPPED":
            transition_event_counts["to_DROPPED"] += 1

    latest_feedback = latest_feedback_by_topic_ids(session, topic_ids)
    finding_distribution: dict[str, int] = {"USEFUL": 0, "NOT_USEFUL": 0, "UNCLEAR": 0}
    topics_with_own_test_url = 0
    topics_with_known_test_outcome = 0
    for _tid, fb in latest_feedback.items():
        finding_distribution[fb.finding_rating] = finding_distribution.get(fb.finding_rating, 0) + 1
        if fb.own_test_video_url:
            topics_with_own_test_url += 1
        if fb.own_test_outcome and fb.own_test_outcome != "UNKNOWN":
            topics_with_known_test_outcome += 1

    live_map = latest_observations_by_topic_ids(session, topic_ids)
    observation_presence = {"present_in_latest_sample": 0, "not_in_latest_sample": 0, "no_observation": 0}
    comparable_delta_topics = 0
    for topic in topics:
        obs = live_map.get(topic.id)
        if obs is None:
            observation_presence["no_observation"] += 1
            continue
        try:
            payload = json.loads(obs.payload_json or "{}")
        except json.JSONDecodeError:
            observation_presence["no_observation"] += 1
            continue
        if payload.get("present_in_snapshot"):
            observation_presence["present_in_latest_sample"] += 1
            frozen = json.loads(topic.frozen_snapshot_json or "{}")
            if count_deltas(frozen, payload):
                comparable_delta_topics += 1
        else:
            observation_presence["not_in_latest_sample"] += 1

    support_breakdown: dict[str, int] = {}
    family_kind_breakdown: dict[str, int] = {}
    for topic in topics:
        try:
            frozen = json.loads(topic.frozen_snapshot_json or "{}")
        except json.JSONDecodeError:
            continue
        family = frozen.get("family") or {}
        kind = str(family.get("family_kind") or "unknown")
        family_kind_breakdown[kind] = family_kind_breakdown.get(kind, 0) + 1
        for src in family.get("support_sources") or []:
            key = str(src)
            support_breakdown[key] = support_breakdown.get(key, 0) + 1

    return {
        "period": {
            "start": period_start.isoformat() if period_start else None,
            "end": period_end.isoformat() if period_end else None,
        },
        "topics_saved_in_period": len(topics),
        "current_status_counts": current_status_counts,
        "status_transition_events": transition_event_counts,
        "latest_finding_rating_distribution": finding_distribution,
        "topics_with_latest_feedback": len(latest_feedback),
        "topics_with_own_test_video_url": topics_with_own_test_url,
        "topics_with_known_own_test_outcome": topics_with_known_test_outcome,
        "latest_observation_presence": observation_presence,
        "topics_with_comparable_count_deltas": comparable_delta_topics,
        "frozen_support_source_breakdown": support_breakdown,
        "frozen_family_kind_breakdown": family_kind_breakdown,
        "interpretation_notes": [
            "Counts reflect bounded Attention Engine samples, not proven market growth.",
            "A family missing from the latest sample is not treated as topic failure.",
            "Count deltas are shown only when the latest observation is present and comparable.",
            "Support/source breakdown is taken from frozen snapshots at save time.",
            "Finding ratings describe analyst feedback, not signal-level usefulness.",
        ],
    }
