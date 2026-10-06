"""Keyword lifecycle transitions and creation (Stage 1.16B)."""

from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.orm import KeywordLifecycleEvent, KeywordScanRun, TargetKeyword
from app.services.keyword_scheduling_policy import (
    DEFAULT_SCHEDULING_POLICY,
    KeywordSchedulingPolicy,
    LIFECYCLE_ARCHIVED,
    LIFECYCLE_ACTIVE,
    LIFECYCLE_PROBATION,
    LIFECYCLE_STATUSES,
    PROBATION_READY_SCAN_COUNT,
    SOURCE_SEED,
)
from app.services.metrics import ensure_utc, utc_now

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_keyword_text(keyword: str) -> str:
    return _WHITESPACE_RE.sub(" ", keyword.strip())


def find_keyword_by_normalized(session: Session, keyword: str) -> TargetKeyword | None:
    normalized = normalize_keyword_text(keyword).casefold()
    for row in session.scalars(select(TargetKeyword)).all():
        if normalize_keyword_text(row.keyword).casefold() == normalized:
            return row
    return None


def create_keyword(
    session: Session,
    keyword: str,
    *,
    source_type: str = SOURCE_SEED,
    parent_keyword_id: int | None = None,
    lifecycle_status: str = LIFECYCLE_PROBATION,
    policy: KeywordSchedulingPolicy | None = None,
    now: datetime | None = None,
    status_reason: str | None = None,
) -> TargetKeyword:
    """
    Insert a keyword. Future expansion sources default to probation; seeds may use active via caller.
    """
    _ = policy
    normalized = normalize_keyword_text(keyword)
    if not normalized:
        raise ValueError("Keyword cannot be empty")

    existing = find_keyword_by_normalized(session, normalized)
    if existing is not None:
        return existing

    reference = now or utc_now()
    sched = policy or DEFAULT_SCHEDULING_POLICY
    interval = sched.interval_seconds_for(lifecycle_status)
    record = TargetKeyword(
        keyword=normalized,
        lifecycle_status=lifecycle_status,
        source_type=source_type,
        parent_keyword_id=parent_keyword_id,
        scan_interval_seconds=interval,
        next_scan_at=sched.next_scan_after_lifecycle_change(lifecycle_status, reference),
        status_changed_at=reference,
        status_reason=status_reason or "created",
    )
    session.add(record)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        dup = find_keyword_by_normalized(session, normalized)
        if dup is not None:
            return dup
        raise ValueError(f"Keyword already exists: {normalized!r}") from exc

    session.add(
        KeywordLifecycleEvent(
            keyword_id=record.id,
            from_status=None,
            to_status=lifecycle_status,
            changed_at=reference,
            reason=status_reason or "created",
            actor_source=source_type,
        ),
    )
    session.flush()
    return record


def set_keyword_lifecycle(
    session: Session,
    keyword_id: int,
    new_status: str,
    reason: str,
    *,
    now: datetime | None = None,
    actor_source: str = "manual",
    policy: KeywordSchedulingPolicy | None = None,
) -> TargetKeyword:
    if new_status not in LIFECYCLE_STATUSES:
        raise ValueError(f"Invalid lifecycle status: {new_status!r}")

    record = session.get(TargetKeyword, keyword_id)
    if record is None:
        raise ValueError(f"Keyword not found: {keyword_id}")

    sched = policy or DEFAULT_SCHEDULING_POLICY
    reference = now or utc_now()
    old_status = record.lifecycle_status
    if old_status == new_status:
        return record

    record.lifecycle_status = new_status
    record.status_changed_at = reference
    record.status_reason = reason.strip() or None
    record.scan_interval_seconds = sched.interval_seconds_for(new_status)
    record.next_scan_at = sched.next_scan_after_lifecycle_change(new_status, reference)

    session.add(
        KeywordLifecycleEvent(
            keyword_id=record.id,
            from_status=old_status,
            to_status=new_status,
            changed_at=reference,
            reason=record.status_reason,
            actor_source=actor_source,
        ),
    )
    session.flush()
    return record


def apply_post_scan_schedule(
    session: Session,
    keyword_id: int,
    *,
    finished_at: datetime,
    scan_succeeded: bool,
    policy: KeywordSchedulingPolicy | None = None,
) -> None:
    """Update last_checked (success only) and next_scan_at after a discovery keyword scan."""
    record = session.get(TargetKeyword, keyword_id)
    if record is None or record.lifecycle_status == LIFECYCLE_ARCHIVED:
        return

    sched = policy or DEFAULT_SCHEDULING_POLICY
    finished = ensure_utc(finished_at)
    if scan_succeeded:
        record.last_checked = finished
        record.next_scan_at = sched.next_scan_after_success(record.lifecycle_status, finished)
        record.scan_interval_seconds = sched.interval_seconds_for(record.lifecycle_status)
    else:
        record.next_scan_at = sched.next_scan_after_failure(finished)
    session.flush()


def count_successful_scans(session: Session, keyword_id: int) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(KeywordScanRun)
            .where(
                KeywordScanRun.keyword_id == keyword_id,
                KeywordScanRun.status == "ok",
            ),
        )
        or 0
    )


def count_successful_scans_batch(session: Session, keyword_ids: list[int]) -> dict[int, int]:
    if not keyword_ids:
        return {}
    rows = session.execute(
        select(KeywordScanRun.keyword_id, func.count())
        .where(
            KeywordScanRun.keyword_id.in_(keyword_ids),
            KeywordScanRun.status == "ok",
        )
        .group_by(KeywordScanRun.keyword_id),
    ).all()
    out = {int(kid): 0 for kid in keyword_ids}
    for kid, cnt in rows:
        out[int(kid)] = int(cnt or 0)
    return out


def probation_ready_for_review(session: Session, keyword_id: int) -> bool:
    record = session.get(TargetKeyword, keyword_id)
    if record is None or record.lifecycle_status != LIFECYCLE_PROBATION:
        return False
    return count_successful_scans(session, keyword_id) >= PROBATION_READY_SCAN_COUNT
