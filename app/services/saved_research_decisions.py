"""Saved Research user decision events (Stage 1.22D.1)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.orm import SavedFamily, SavedResearchEvent, SavedVideo
from app.services.metrics import ensure_utc, utc_now

EntityKind = Literal["video", "family"]
EventType = Literal[
    "saved",
    "status_changed",
    "notes_changed",
    "tags_changed",
    "archived",
    "restored",
]


def _add_event(
    session: Session,
    *,
    entity_kind: EntityKind,
    entity_id: int,
    event_type: EventType,
    payload: dict[str, Any],
    occurred_at: datetime | None = None,
) -> SavedResearchEvent:
    row = SavedResearchEvent(
        entity_kind=entity_kind,
        entity_id=entity_id,
        occurred_at=occurred_at or utc_now(),
        event_type=event_type,
        payload_json=json.dumps(payload, ensure_ascii=False),
    )
    session.add(row)
    return row


def record_video_saved(session: Session, row: SavedVideo) -> SavedResearchEvent:
    return _add_event(
        session,
        entity_kind="video",
        entity_id=row.id,
        event_type="saved",
        payload={"status": row.status, "video_id": row.video_id},
        occurred_at=ensure_utc(row.saved_at),
    )


def record_family_saved(session: Session, row: SavedFamily) -> SavedResearchEvent:
    return _add_event(
        session,
        entity_kind="family",
        entity_id=row.id,
        event_type="saved",
        payload={"status": row.status, "family_key": row.family_key},
        occurred_at=ensure_utc(row.saved_at),
    )


def record_status_change(
    session: Session,
    *,
    entity_kind: EntityKind,
    entity_id: int,
    previous: str,
    new: str,
) -> SavedResearchEvent | None:
    if previous == new:
        return None
    return _add_event(
        session,
        entity_kind=entity_kind,
        entity_id=entity_id,
        event_type="status_changed",
        payload={"previous_status": previous, "new_status": new},
    )


def record_notes_changed(
    session: Session,
    *,
    entity_kind: EntityKind,
    entity_id: int,
    had_notes: bool,
    has_notes: bool,
) -> SavedResearchEvent | None:
    if had_notes == has_notes:
        return None
    return _add_event(
        session,
        entity_kind=entity_kind,
        entity_id=entity_id,
        event_type="notes_changed",
        payload={"had_notes": had_notes, "has_notes": has_notes},
    )


def record_tags_changed(
    session: Session,
    *,
    entity_kind: EntityKind,
    entity_id: int,
    previous_count: int,
    new_count: int,
) -> SavedResearchEvent | None:
    if previous_count == new_count:
        return None
    return _add_event(
        session,
        entity_kind=entity_kind,
        entity_id=entity_id,
        event_type="tags_changed",
        payload={"previous_tag_count": previous_count, "new_tag_count": new_count},
    )


def record_archived(
    session: Session,
    *,
    entity_kind: EntityKind,
    entity_id: int,
) -> SavedResearchEvent:
    return _add_event(
        session,
        entity_kind=entity_kind,
        entity_id=entity_id,
        event_type="archived",
        payload={},
    )


def record_restored(
    session: Session,
    *,
    entity_kind: EntityKind,
    entity_id: int,
) -> SavedResearchEvent:
    return _add_event(
        session,
        entity_kind=entity_kind,
        entity_id=entity_id,
        event_type="restored",
        payload={},
    )


def list_decision_events(
    session: Session,
    *,
    entity_kind: EntityKind,
    entity_id: int,
    limit: int,
    offset: int,
) -> tuple[list[SavedResearchEvent], int]:
    filters = (
        SavedResearchEvent.entity_kind == entity_kind,
        SavedResearchEvent.entity_id == entity_id,
    )
    total = int(
        session.scalar(select(func.count()).select_from(SavedResearchEvent).where(*filters)) or 0,
    )
    rows = session.scalars(
        select(SavedResearchEvent)
        .where(*filters)
        .order_by(SavedResearchEvent.occurred_at.desc(), SavedResearchEvent.id.desc())
        .offset(offset)
        .limit(limit),
    ).all()
    return list(rows), total


def event_to_dict(row: SavedResearchEvent) -> dict[str, Any]:
    try:
        payload = json.loads(row.payload_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    return {
        "id": row.id,
        "entity_kind": row.entity_kind,
        "entity_id": row.entity_id,
        "occurred_at": ensure_utc(row.occurred_at).isoformat(),
        "event_type": row.event_type,
        "payload": payload,
    }
