"""Read-only keyword schedule state (Stage 1.16B)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.orm import TargetKeyword
from app.services.keyword_lifecycle_service import probation_ready_for_review
from app.services.keyword_scheduling_policy import LIFECYCLE_ARCHIVED
from app.services.metrics import ensure_utc, utc_now


@dataclass(frozen=True, slots=True)
class KeywordScheduleState:
    keyword_id: int
    keyword: str
    lifecycle_status: str
    source_type: str
    last_checked: datetime | None
    next_scan_at: datetime | None
    scan_interval_seconds: int | None
    is_due: bool
    overdue_seconds: float
    probation_ready_for_review: bool
    scheduling_hint: str | None


def _overdue_seconds(next_scan_at: datetime | None, now: datetime) -> float:
    if next_scan_at is None:
        return 0.0
    delta = (ensure_utc(now) - ensure_utc(next_scan_at)).total_seconds()
    return round(max(delta, 0.0), 3)


def is_keyword_due(record: TargetKeyword, *, now: datetime | None = None) -> bool:
    reference = now or utc_now()
    if record.lifecycle_status == LIFECYCLE_ARCHIVED:
        return False
    if record.next_scan_at is None:
        return True
    return ensure_utc(record.next_scan_at) <= ensure_utc(reference)


def get_keyword_schedule_state(
    session: Session,
    keyword_id: int,
    *,
    now: datetime | None = None,
) -> KeywordScheduleState | None:
    record = session.get(TargetKeyword, keyword_id)
    if record is None:
        return None
    reference = now or utc_now()
    due = is_keyword_due(record, now=reference)
    overdue = _overdue_seconds(record.next_scan_at, reference) if due else 0.0
    ready = probation_ready_for_review(session, keyword_id)
    hint = None
    if ready and record.lifecycle_status == "probation":
        hint = "probation_ready_for_review"

    return KeywordScheduleState(
        keyword_id=record.id,
        keyword=record.keyword,
        lifecycle_status=record.lifecycle_status,
        source_type=record.source_type,
        last_checked=record.last_checked,
        next_scan_at=record.next_scan_at,
        scan_interval_seconds=record.scan_interval_seconds,
        is_due=due,
        overdue_seconds=overdue,
        probation_ready_for_review=ready,
        scheduling_hint=hint,
    )
