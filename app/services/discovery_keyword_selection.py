"""Deterministic lifecycle-aware keyword batch selection (Stage 1.15A / 1.16B / Fix 3C)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.orm import TargetKeyword
from app.services.discovery_queue_policy import (
    NEVER_SCANNED_BOOST_HOURS,
    STARVATION_BOOST_HOURS,
    STARVATION_OVERDUE_THRESHOLD_HOURS,
    is_priority_discovery_keyword,
    priority_reserved_slots,
)
from app.services.keyword_scheduling_policy import (
    DEFAULT_SCHEDULING_POLICY,
    LIFECYCLE_ARCHIVED,
    LIFECYCLE_PROBATION,
    LIFECYCLE_TIEBREAK_ORDER,
    KeywordSchedulingPolicy,
    SOURCE_CHANNEL,
    SOURCE_EXPLORATION,
    SOURCE_LLM,
    SOURCE_MANUAL,
    SOURCE_RELATED,
    SOURCE_SEED,
    SOURCE_SUGGESTION,
)
from app.services.metrics import ensure_utc, utc_now

# Tie-break after overdue: lower = selected earlier (Fix 3B seed priority).
SOURCE_TIEBREAK_ORDER = {
    SOURCE_SEED: 0,
    SOURCE_MANUAL: 1,
    SOURCE_CHANNEL: 2,
    SOURCE_RELATED: 3,
    SOURCE_LLM: 4,
    SOURCE_SUGGESTION: 5,
    SOURCE_EXPLORATION: 6,
}

DEFAULT_BATCH_SIZE = 5


def _overdue_seconds(record: TargetKeyword, now: datetime) -> float:
    if record.next_scan_at is None:
        return float("inf")
    return max(
        (ensure_utc(now) - ensure_utc(record.next_scan_at)).total_seconds(),
        0.0,
    )


def _sort_key(record: TargetKeyword, now: datetime) -> tuple[float, int, float, int]:
    """
    Ordering (documented):
    1. overdue_seconds descending (most overdue first)
    2. source tie-break: seed < manual < … < suggestion
    3. lifecycle tie-break: probation < active < weak
    4. oldest last_checked (never-checked treated as oldest)
    5. id ascending
    """
    overdue = _overdue_seconds(record, now)
    source_rank = SOURCE_TIEBREAK_ORDER.get(record.source_type, 50)
    lifecycle_rank = LIFECYCLE_TIEBREAK_ORDER.get(record.lifecycle_status, 50)
    if record.last_checked is None:
        last_checked_key = float("-inf")
    else:
        last_checked_key = ensure_utc(record.last_checked).timestamp()
    return (-overdue, source_rank, lifecycle_rank, last_checked_key, record.id)


def _general_pool_sort_key(record: TargetKeyword, now: datetime) -> tuple[float, int, float, int]:
    """Probation pool: boost first scan and long-wait starvation without displacing priority tier."""
    overdue = _overdue_seconds(record, now)
    if record.lifecycle_status == LIFECYCLE_PROBATION:
        if record.last_checked is None:
            overdue += NEVER_SCANNED_BOOST_HOURS * 3600.0
        elif overdue >= STARVATION_OVERDUE_THRESHOLD_HOURS * 3600.0:
            overdue += STARVATION_BOOST_HOURS * 3600.0
    source_rank = SOURCE_TIEBREAK_ORDER.get(record.source_type, 50)
    lifecycle_rank = LIFECYCLE_TIEBREAK_ORDER.get(record.lifecycle_status, 50)
    if record.last_checked is None:
        last_checked_key = float("-inf")
    else:
        last_checked_key = ensure_utc(record.last_checked).timestamp()
    return (-overdue, source_rank, lifecycle_rank, last_checked_key, record.id)


def _fetch_due_candidates(session: Session, *, reference: datetime) -> list[TargetKeyword]:
    due_clause = or_(
        TargetKeyword.next_scan_at.is_(None),
        TargetKeyword.next_scan_at <= reference,
    )
    return list(
        session.scalars(
            select(TargetKeyword).where(
                TargetKeyword.lifecycle_status != LIFECYCLE_ARCHIVED,
                due_clause,
                or_(
                    TargetKeyword.source_type != SOURCE_EXPLORATION,
                    TargetKeyword.parent_keyword_id.is_not(None),
                ),
            ),
        ).all(),
    )


def select_discovery_keywords_from_candidates(
    candidates: list[TargetKeyword],
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    now: datetime,
    tiered: bool = True,
) -> list[TargetKeyword]:
    """In-memory selection (tests and read-only replay)."""
    limit = max(1, batch_size)
    if not candidates:
        return []
    reference = ensure_utc(now)
    sort_general = _general_pool_sort_key if tiered else _sort_key

    if not tiered:
        ordered = sorted(candidates, key=lambda row: _sort_key(row, reference))
        return ordered[:limit]

    reserved_n = priority_reserved_slots(limit)
    priority = [row for row in candidates if is_priority_discovery_keyword(row)]
    priority_ids = {row.id for row in priority}
    general = [row for row in candidates if row.id not in priority_ids]

    priority.sort(key=lambda row: _sort_key(row, reference))
    general.sort(key=lambda row: sort_general(row, reference))

    chosen: list[TargetKeyword] = []
    for row in priority[:reserved_n]:
        chosen.append(row)
    chosen_ids = {row.id for row in chosen}
    for row in general:
        if row.id in chosen_ids:
            continue
        chosen.append(row)
        chosen_ids.add(row.id)
        if len(chosen) >= limit:
            return chosen[:limit]
    for row in priority[reserved_n:]:
        if row.id in chosen_ids:
            continue
        chosen.append(row)
        if len(chosen) >= limit:
            break
    return chosen[:limit]


def select_discovery_keywords(
    session: Session,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    now: datetime | None = None,
    policy: KeywordSchedulingPolicy | None = None,
) -> list[TargetKeyword]:
    """
    Select due keywords for one discovery cycle (Fix 3C tiered batch).

    - Reserved slots: seed/manual + active lifecycle (timely core pool).
    - Remaining slots: probation/suggestion with first-scan and starvation boosts.
    """
    _ = policy
    reference = now or utc_now()
    candidates = _fetch_due_candidates(session, reference=reference)
    return select_discovery_keywords_from_candidates(
        candidates,
        batch_size=batch_size,
        now=reference,
        tiered=True,
    )


def select_discovery_keywords_legacy(
    session: Session,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    now: datetime | None = None,
    policy: KeywordSchedulingPolicy | None = None,
) -> list[TargetKeyword]:
    """Pre-3C selection: single pool sorted by overdue only (+ tie-breaks)."""
    _ = policy
    reference = now or utc_now()
    candidates = _fetch_due_candidates(session, reference=reference)
    return select_discovery_keywords_from_candidates(
        candidates,
        batch_size=batch_size,
        now=reference,
        tiered=False,
    )
