"""Deterministic lifecycle-aware keyword batch selection (Stage 1.15A / 1.16B)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.orm import TargetKeyword
from app.services.keyword_scheduling_policy import (
    DEFAULT_SCHEDULING_POLICY,
    LIFECYCLE_ARCHIVED,
    LIFECYCLE_TIEBREAK_ORDER,
    KeywordSchedulingPolicy,
)
from app.services.metrics import ensure_utc, utc_now

DEFAULT_BATCH_SIZE = 5


def _sort_key(record: TargetKeyword, now: datetime) -> tuple[float, int, float, int]:
    """
    Ordering (documented):
    1. overdue_seconds descending (most overdue first)
    2. lifecycle tie-break: probation < active < weak
    3. oldest last_checked (never-checked treated as oldest)
    4. id ascending
    """
    if record.next_scan_at is None:
        overdue = float("inf")
    else:
        overdue = max(
            (ensure_utc(now) - ensure_utc(record.next_scan_at)).total_seconds(),
            0.0,
        )
    lifecycle_rank = LIFECYCLE_TIEBREAK_ORDER.get(record.lifecycle_status, 50)
    if record.last_checked is None:
        last_checked_key = float("-inf")
    else:
        last_checked_key = ensure_utc(record.last_checked).timestamp()
    return (-overdue, lifecycle_rank, last_checked_key, record.id)


def select_discovery_keywords(
    session: Session,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    now: datetime | None = None,
    policy: KeywordSchedulingPolicy | None = None,
) -> list[TargetKeyword]:
    """
    Select due keyword seeds for one discovery cycle.

    Eligible: lifecycle != archived and next_scan_at <= now (or next_scan_at is null).
    Fairness: overdue age dominates; lifecycle only breaks near-ties.
    """
    _ = policy
    reference = now or utc_now()
    due_clause = or_(
        TargetKeyword.next_scan_at.is_(None),
        TargetKeyword.next_scan_at <= reference,
    )
    candidates = list(
        session.scalars(
            select(TargetKeyword).where(
                TargetKeyword.lifecycle_status != LIFECYCLE_ARCHIVED,
                due_clause,
            ),
        ).all(),
    )
    candidates.sort(key=lambda row: _sort_key(row, reference))
    limit = max(1, batch_size)
    return candidates[:limit]
