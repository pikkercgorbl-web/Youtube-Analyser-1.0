"""Explicit analyst feedback for Saved Research (Stage 1.22D.2)."""

from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.orm import SavedFamily, SavedResearchFeedback, SavedVideo
from app.services.metrics import utc_now
from app.services.saved_research import SavedResearchArchivedError

EntityKind = Literal["video", "family"]
FeedbackVerdict = Literal[
    "USEFUL",
    "NOT_RELEVANT",
    "NOISE_OR_DUPLICATE",
    "TOO_BROAD",
    "NEEDS_RESEARCH",
]

FEEDBACK_VERDICTS: frozenset[str] = frozenset(
    {
        "USEFUL",
        "NOT_RELEVANT",
        "NOISE_OR_DUPLICATE",
        "TOO_BROAD",
        "NEEDS_RESEARCH",
    },
)
MAX_FEEDBACK_REASON_CHARS = 1000


def _load_entity(session: Session, *, entity_kind: EntityKind, entity_id: int):
    if entity_kind == "video":
        return session.get(SavedVideo, entity_id)
    return session.get(SavedFamily, entity_id)


def _ensure_feedback_allowed(row) -> None:
    if row is None:
        return
    if getattr(row, "archived_at", None) is not None:
        raise SavedResearchArchivedError(
            "Cannot add analyst feedback while the item is archived; restore it first.",
        )


def append_analyst_feedback(
    session: Session,
    *,
    entity_kind: EntityKind,
    entity_id: int,
    verdict: str,
    reason: str | None = None,
) -> SavedResearchFeedback | None:
    row = _load_entity(session, entity_kind=entity_kind, entity_id=entity_id)
    if row is None:
        return None
    _ensure_feedback_allowed(row)
    rating = (verdict or "").strip().upper()
    if rating not in FEEDBACK_VERDICTS:
        raise ValueError(
            "verdict must be one of: USEFUL, NOT_RELEVANT, NOISE_OR_DUPLICATE, TOO_BROAD, NEEDS_RESEARCH",
        )
    reason_text = (reason or "").strip()
    if len(reason_text) > MAX_FEEDBACK_REASON_CHARS:
        raise ValueError(f"reason must be at most {MAX_FEEDBACK_REASON_CHARS} characters")
    now = utc_now()
    feedback = SavedResearchFeedback(
        entity_kind=entity_kind,
        entity_id=entity_id,
        verdict=rating,
        reason=reason_text or None,
        created_at=now,
    )
    session.add(feedback)
    row.updated_at = now
    session.flush()
    return feedback


def latest_feedback_for_entity(
    session: Session,
    *,
    entity_kind: EntityKind,
    entity_id: int,
) -> SavedResearchFeedback | None:
    return session.scalar(
        select(SavedResearchFeedback)
        .where(
            SavedResearchFeedback.entity_kind == entity_kind,
            SavedResearchFeedback.entity_id == entity_id,
        )
        .order_by(SavedResearchFeedback.created_at.desc(), SavedResearchFeedback.id.desc())
        .limit(1),
    )


def latest_feedback_by_entities(
    session: Session,
    *,
    entity_kind: EntityKind,
    entity_ids: list[int],
) -> dict[int, SavedResearchFeedback]:
    if not entity_ids:
        return {}
    subq = (
        select(
            SavedResearchFeedback.entity_id,
            func.max(SavedResearchFeedback.created_at).label("max_created"),
        )
        .where(
            SavedResearchFeedback.entity_kind == entity_kind,
            SavedResearchFeedback.entity_id.in_(entity_ids),
        )
        .group_by(SavedResearchFeedback.entity_id)
        .subquery()
    )
    rows = session.scalars(
        select(SavedResearchFeedback)
        .join(
            subq,
            (SavedResearchFeedback.entity_id == subq.c.entity_id)
            & (SavedResearchFeedback.created_at == subq.c.max_created)
            & (SavedResearchFeedback.entity_kind == entity_kind),
        )
        .order_by(SavedResearchFeedback.id.desc()),
    ).all()
    out: dict[int, SavedResearchFeedback] = {}
    for row in rows:
        out.setdefault(row.entity_id, row)
    return out


def list_analyst_feedback(
    session: Session,
    *,
    entity_kind: EntityKind,
    entity_id: int,
    limit: int,
    offset: int,
) -> tuple[SavedResearchFeedback | None, list[SavedResearchFeedback], int]:
    filters = (
        SavedResearchFeedback.entity_kind == entity_kind,
        SavedResearchFeedback.entity_id == entity_id,
    )
    total = int(
        session.scalar(select(func.count()).select_from(SavedResearchFeedback).where(*filters)) or 0,
    )
    latest = latest_feedback_for_entity(session, entity_kind=entity_kind, entity_id=entity_id)
    rows = list(
        session.scalars(
            select(SavedResearchFeedback)
            .where(*filters)
            .order_by(SavedResearchFeedback.created_at.desc(), SavedResearchFeedback.id.desc())
            .offset(offset)
            .limit(limit),
        ).all(),
    )
    return latest, rows, total


def feedback_to_dict(row: SavedResearchFeedback) -> dict[str, Any]:
    return {
        "id": row.id,
        "entity_kind": row.entity_kind,
        "entity_id": row.entity_id,
        "verdict": row.verdict,
        "reason": row.reason,
        "created_at": row.created_at.isoformat(),
    }
