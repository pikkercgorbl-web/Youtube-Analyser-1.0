"""Saved Topics / Watchlist (Stage 1.22C)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.orm import SavedTopic, SavedTopicObservation, SavedTopicStatus
from app.services.saved_topic_decisions import record_archived, record_restored, record_status_change
from app.services.attention_engine_types import (
    AttentionEngineResult,
    PatternCandidate,
    PatternFamily,
    VideoWinner,
    pattern_family_to_dict,
    pattern_to_dict,
    video_winner_to_dict,
)
from app.services.metrics import ensure_utc, utc_now


def _load_attention_snapshot(session: Session):
    from app.services.attention_read_model import load_attention_snapshot

    return load_attention_snapshot(session)

FAMILY_ABSENCE_MESSAGE = "Тема не представлена в текущей выборке Attention Engine"

MAX_NOTES_LENGTH = 4000
MAX_TAGS = 20
MAX_TAG_LENGTH = 64

SavedTopicUserStatus = Literal["WATCHING", "WANT_TO_TEST", "TESTING", "DROPPED"]


class SavedTopicError(Exception):
    """Base for saved-topic domain errors."""


class SavedTopicFamilyNotInSnapshotError(SavedTopicError):
    """Family is absent from the current Attention snapshot (save blocked)."""


class SavedTopicArchivedError(SavedTopicError):
    """Topic exists but is archived; restore required before re-save."""


@dataclass(frozen=True, slots=True)
class SavedTopicSaveResult:
    topic: SavedTopic
    created: bool
    idempotent: bool


def _parse_tags(raw: str) -> list[str]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data]


def validate_tags(tags: list[str]) -> list[str]:
    if len(tags) > MAX_TAGS:
        raise ValueError(f"At most {MAX_TAGS} tags allowed")
    cleaned: list[str] = []
    for tag in tags:
        text = tag.strip()
        if not text:
            continue
        if len(text) > MAX_TAG_LENGTH:
            raise ValueError(f"Each tag must be at most {MAX_TAG_LENGTH} characters")
        cleaned.append(text)
    return cleaned


def validate_notes(notes: str) -> str:
    if len(notes) > MAX_NOTES_LENGTH:
        raise ValueError(f"Notes must be at most {MAX_NOTES_LENGTH} characters")
    return notes


def _family_map(result: AttentionEngineResult) -> dict[str, PatternFamily]:
    return {row.family_key: row for row in result.families}


def _pattern_map(result: AttentionEngineResult) -> dict[str, PatternCandidate]:
    return {row.pattern_key: row for row in result.patterns}


def _winner_map(result: AttentionEngineResult) -> dict[str, VideoWinner]:
    return {row.video_id: row for row in result.video_winners}


def _breakout_evidence_for_family(
    family: PatternFamily,
    *,
    patterns_by_key: dict[str, PatternCandidate],
    winners_by_id: dict[str, VideoWinner],
) -> list[dict[str, Any]]:
    family_video_ids = set(family.video_ids)
    evidence: list[dict[str, Any]] = []
    for video_id in family_video_ids:
        winner = winners_by_id.get(video_id)
        if winner is None:
            continue
        if winner.breakout_eligible or winner.breakout_rank is not None:
            evidence.append(video_winner_to_dict(winner))
    return evidence


def _member_pattern_breakout(
    family: PatternFamily,
    patterns_by_key: dict[str, PatternCandidate],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in family.member_pattern_keys:
        pattern = patterns_by_key.get(key)
        if pattern is None:
            continue
        rows.append(
            {
                "pattern_key": pattern.pattern_key,
                "label": pattern.label,
                "breakout_video_count": pattern.breakout_video_count,
                "small_channel_winner_count": pattern.small_channel_winner_count,
            },
        )
    return rows


def build_frozen_snapshot(
    *,
    family: PatternFamily,
    result: AttentionEngineResult,
) -> dict[str, Any]:
    patterns_by_key = _pattern_map(result)
    winners_by_id = _winner_map(result)
    member_patterns = [
        pattern_to_dict(patterns_by_key[key])
        for key in family.member_pattern_keys
        if key in patterns_by_key
    ]
    return {
        "attention_run_id": result.summary.run_id,
        "attention_computed_at": result.summary.computed_at.isoformat(),
        "family": pattern_family_to_dict(family),
        "member_patterns": member_patterns,
        "video_ids": list(family.video_ids),
        "keyword_ids": list(family.keyword_ids),
        "breakout_video_evidence": _breakout_evidence_for_family(
            family,
            patterns_by_key=patterns_by_key,
            winners_by_id=winners_by_id,
        ),
        "member_pattern_breakout": _member_pattern_breakout(family, patterns_by_key),
    }


def build_observation_payload(
    *,
    family: PatternFamily | None,
    result: AttentionEngineResult,
) -> dict[str, Any]:
    run_id = result.summary.run_id
    computed_at = ensure_utc(result.summary.computed_at).isoformat()
    if family is None:
        return {
            "present_in_snapshot": False,
            "absence_message": FAMILY_ABSENCE_MESSAGE,
            "attention_run_id": run_id,
            "attention_computed_at": computed_at,
        }
    patterns_by_key = _pattern_map(result)
    winners_by_id = _winner_map(result)
    family_dict = pattern_family_to_dict(family)
    return {
        "present_in_snapshot": True,
        "attention_run_id": run_id,
        "attention_computed_at": computed_at,
        "counts": {
            "video_count": family_dict["video_count"],
            "channel_count": family_dict["channel_count"],
            "keyword_count": family_dict["keyword_count"],
            "breakout_eligible_count": family_dict.get("breakout_eligible_count"),
            "videos_last_24h": family_dict.get("videos_last_24h"),
            "videos_previous_24h": family_dict.get("videos_previous_24h"),
            "videos_previous_48_24h": family_dict.get("videos_previous_48_24h"),
        },
        "activity_windows": {
            "first_seen_at": family_dict.get("first_seen_at"),
            "latest_seen_at": family_dict.get("latest_seen_at"),
        },
        "member_pattern_keys": list(family.member_pattern_keys),
        "breakout_video_evidence": _breakout_evidence_for_family(
            family,
            patterns_by_key=patterns_by_key,
            winners_by_id=winners_by_id,
        ),
        "member_pattern_breakout": _member_pattern_breakout(family, patterns_by_key),
    }


def _add_observation(
    session: Session,
    *,
    topic: SavedTopic,
    run_id: str,
    captured_at: datetime,
    payload: dict[str, Any],
) -> SavedTopicObservation:
    row = SavedTopicObservation(
        saved_topic_id=topic.id,
        attention_run_id=run_id,
        captured_at=captured_at,
        payload_json=json.dumps(payload, ensure_ascii=False),
    )
    session.add(row)
    return row


def observation_exists(session: Session, *, saved_topic_id: int, attention_run_id: str) -> bool:
    existing = session.scalar(
        select(SavedTopicObservation.id)
        .where(
            SavedTopicObservation.saved_topic_id == saved_topic_id,
            SavedTopicObservation.attention_run_id == attention_run_id,
        )
        .limit(1),
    )
    return existing is not None


def append_saved_topic_observations_for_result(
    session: Session,
    *,
    run_id: str,
    result: AttentionEngineResult,
) -> int:
    """
    Append observations for all non-archived saved topics after snapshot persist.

    Caller owns commit/rollback. Does not commit.
    """
    topics = session.scalars(
        select(SavedTopic).where(SavedTopic.archived_at.is_(None)).order_by(SavedTopic.id.asc()),
    ).all()
    if not topics:
        return 0
    families = _family_map(result)
    captured_at = ensure_utc(result.summary.computed_at)
    topic_ids = [topic.id for topic in topics]
    existing_pairs = session.execute(
        select(SavedTopicObservation.saved_topic_id, SavedTopicObservation.attention_run_id).where(
            SavedTopicObservation.saved_topic_id.in_(topic_ids),
            SavedTopicObservation.attention_run_id == run_id,
        ),
    ).all()
    skip_ids = {row[0] for row in existing_pairs}
    added = 0
    for topic in topics:
        if topic.id in skip_ids:
            continue
        family = families.get(topic.family_key)
        payload = build_observation_payload(family=family, result=result)
        _add_observation(
            session,
            topic=topic,
            run_id=run_id,
            captured_at=captured_at,
            payload=payload,
        )
        added += 1
    if added:
        session.flush()
    return added


def save_topic(session: Session, *, family_key: str) -> SavedTopicSaveResult:
    """
    Create saved topic + initial observation atomically (flush only).

    Idempotent when an active row exists. Archived rows are not overwritten.
    """
    result = _load_attention_snapshot(session)
    if result is None:
        raise SavedTopicFamilyNotInSnapshotError("Attention snapshot unavailable")
    family = _family_map(result).get(family_key)
    if family is None:
        raise SavedTopicFamilyNotInSnapshotError(
            f"Pattern family {family_key!r} not found in current Attention snapshot",
        )

    existing = session.scalar(select(SavedTopic).where(SavedTopic.family_key == family_key).limit(1))
    if existing is not None:
        if existing.archived_at is not None:
            raise SavedTopicArchivedError(
                f"Saved topic for {family_key!r} is archived; use restore before saving again",
            )
        return SavedTopicSaveResult(topic=existing, created=False, idempotent=True)

    now = utc_now()
    frozen = build_frozen_snapshot(family=family, result=result)
    topic = SavedTopic(
        family_key=family_key,
        status=SavedTopicStatus.WATCHING.value,
        notes="",
        tags_json="[]",
        frozen_snapshot_json=json.dumps(frozen, ensure_ascii=False),
        created_at=now,
        updated_at=now,
    )
    session.add(topic)
    session.flush()

    payload = build_observation_payload(family=family, result=result)
    _add_observation(
        session,
        topic=topic,
        run_id=result.summary.run_id,
        captured_at=ensure_utc(result.summary.computed_at),
        payload=payload,
    )
    session.flush()
    return SavedTopicSaveResult(topic=topic, created=True, idempotent=False)


def patch_topic(
    session: Session,
    topic_id: int,
    *,
    status: SavedTopicUserStatus | None = None,
    notes: str | None = None,
    tags: list[str] | None = None,
) -> SavedTopic | None:
    topic = session.get(SavedTopic, topic_id)
    if topic is None:
        return None
    if status is not None:
        previous = topic.status
        if previous != status:
            record_status_change(session, topic, previous=previous, new=status)
        topic.status = status
    if notes is not None:
        topic.notes = validate_notes(notes)
    if tags is not None:
        topic.tags_json = json.dumps(validate_tags(tags), ensure_ascii=False)
    topic.updated_at = utc_now()
    session.flush()
    return topic


def archive_topic(session: Session, topic_id: int) -> SavedTopic | None:
    topic = session.get(SavedTopic, topic_id)
    if topic is None:
        return None
    if topic.archived_at is None:
        topic.archived_at = utc_now()
        topic.updated_at = utc_now()
        record_archived(session, topic)
        session.flush()
    return topic


def restore_topic(session: Session, topic_id: int) -> SavedTopic | None:
    topic = session.get(SavedTopic, topic_id)
    if topic is None:
        return None
    was_archived = topic.archived_at is not None
    topic.archived_at = None
    topic.updated_at = utc_now()
    if was_archived:
        record_restored(session, topic)
    session.flush()
    result = _load_attention_snapshot(session)
    if result is not None and not observation_exists(
        session,
        saved_topic_id=topic.id,
        attention_run_id=result.summary.run_id,
    ):
        family = _family_map(result).get(topic.family_key)
        payload = build_observation_payload(family=family, result=result)
        _add_observation(
            session,
            topic=topic,
            run_id=result.summary.run_id,
            captured_at=ensure_utc(result.summary.computed_at),
            payload=payload,
        )
        session.flush()
    return topic


def get_topic(session: Session, topic_id: int) -> SavedTopic | None:
    return session.get(SavedTopic, topic_id)


def get_topic_by_family_key(session: Session, family_key: str) -> SavedTopic | None:
    return session.scalar(select(SavedTopic).where(SavedTopic.family_key == family_key).limit(1))


def list_topics(
    session: Session,
    *,
    archived: Literal["active", "archived", "all"] = "active",
    query: str | None = None,
) -> list[SavedTopic]:
    stmt = select(SavedTopic).order_by(SavedTopic.updated_at.desc(), SavedTopic.id.desc())
    if archived == "active":
        stmt = stmt.where(SavedTopic.archived_at.is_(None))
    elif archived == "archived":
        stmt = stmt.where(SavedTopic.archived_at.is_not(None))
    if query:
        q = f"%{query.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(SavedTopic.family_key).like(q),
                func.lower(SavedTopic.notes).like(q),
                func.lower(SavedTopic.tags_json).like(q),
                func.lower(SavedTopic.frozen_snapshot_json).like(q),
            ),
        )
    return list(session.scalars(stmt).all())


def latest_observations_by_topic_ids(
    session: Session,
    topic_ids: list[int],
) -> dict[int, SavedTopicObservation]:
    if not topic_ids:
        return {}
    subq = (
        select(
            SavedTopicObservation.saved_topic_id,
            func.max(SavedTopicObservation.captured_at).label("max_captured"),
        )
        .where(SavedTopicObservation.saved_topic_id.in_(topic_ids))
        .group_by(SavedTopicObservation.saved_topic_id)
        .subquery()
    )
    rows = session.scalars(
        select(SavedTopicObservation)
        .join(
            subq,
            (SavedTopicObservation.saved_topic_id == subq.c.saved_topic_id)
            & (SavedTopicObservation.captured_at == subq.c.max_captured),
        )
        .order_by(SavedTopicObservation.id.desc()),
    ).all()
    out: dict[int, SavedTopicObservation] = {}
    for row in rows:
        out.setdefault(row.saved_topic_id, row)
    return out


def list_topic_timeline(
    session: Session,
    topic_id: int,
    *,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    from app.services.saved_topic_decisions import event_to_dict, list_events

    observations, obs_total = list_observation_history(session, topic_id, limit=500, offset=0)
    events, ev_total = list_events(session, topic_id, limit=500, offset=0)
    merged: list[dict[str, Any]] = []
    for row in observations:
        merged.append(
            {
                "kind": "observation",
                "occurred_at": ensure_utc(row.captured_at),
                "observation_id": row.id,
                "attention_run_id": row.attention_run_id,
                "payload": json.loads(row.payload_json or "{}"),
            },
        )
    for row in events:
        event_dict = event_to_dict(row)
        merged.append(
            {
                "kind": "event",
                "occurred_at": ensure_utc(row.occurred_at),
                "id": event_dict["id"],
                "event_type": event_dict["event_type"],
                "payload": event_dict["payload"],
            },
        )
    merged.sort(
        key=lambda item: (
            item["occurred_at"],
            item.get("observation_id") or item.get("id") or 0,
        ),
        reverse=True,
    )
    total = obs_total + ev_total
    page = merged[offset : offset + limit]
    return page, total


def list_observation_history(
    session: Session,
    topic_id: int,
    *,
    limit: int,
    offset: int,
) -> tuple[list[SavedTopicObservation], int]:
    total = session.scalar(
        select(func.count())
        .select_from(SavedTopicObservation)
        .where(SavedTopicObservation.saved_topic_id == topic_id),
    )
    total = int(total or 0)
    rows = session.scalars(
        select(SavedTopicObservation)
        .where(SavedTopicObservation.saved_topic_id == topic_id)
        .order_by(SavedTopicObservation.captured_at.desc(), SavedTopicObservation.id.desc())
        .offset(offset)
        .limit(limit),
    ).all()
    return list(rows), total


def frozen_label(topic: SavedTopic) -> str:
    try:
        payload = json.loads(topic.frozen_snapshot_json)
        family = payload.get("family") or {}
        return str(family.get("label") or topic.family_key)
    except json.JSONDecodeError:
        return topic.family_key


def count_deltas(
    frozen: dict[str, Any],
    live_payload: dict[str, Any],
) -> dict[str, int] | None:
    if not live_payload.get("present_in_snapshot"):
        return None
    frozen_family = frozen.get("family") or {}
    live_counts = live_payload.get("counts") or {}
    keys = (
        "video_count",
        "channel_count",
        "keyword_count",
        "breakout_eligible_count",
        "videos_last_24h",
        "videos_previous_24h",
        "videos_previous_48_24h",
    )
    deltas: dict[str, int] = {}
    for key in keys:
        if key not in live_counts:
            continue
        before = frozen_family.get(key)
        after = live_counts.get(key)
        if before is None or after is None:
            continue
        deltas[key] = int(after) - int(before)
    return deltas or None
