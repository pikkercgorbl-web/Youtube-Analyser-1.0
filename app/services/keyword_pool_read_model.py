"""Keyword pool queue read model for UI (Fix 3B)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.orm import KeywordScanRun, TargetKeyword
from app.services.keyword_scheduling_policy import DEFAULT_SCHEDULING_POLICY, LIFECYCLE_ARCHIVED
from app.services.metrics import ensure_utc, utc_now
from app.services.operations_overview_queries import count_keywords_due_batch


@dataclass(frozen=True, slots=True)
class KeywordPoolSummary:
    snapshot_at: datetime
    due_now: int
    due_next_1h: int
    due_next_24h: int
    not_archived_count: int
    unique_keywords_scanned_last_24h: int
    keyword_scan_runs_last_24h: int
    probation_interval_hours: float
    active_interval_hours: float
    weak_interval_hours: float
    failed_scan_retry_hours: float


def build_keyword_pool_summary(session: Session, *, now: datetime | None = None) -> KeywordPoolSummary:
    reference = ensure_utc(now or utc_now())
    due_now, due_1h, due_24h = count_keywords_due_batch(session, now=reference)
    not_archived = session.scalar(
        select(func.count())
        .select_from(TargetKeyword)
        .where(TargetKeyword.lifecycle_status != LIFECYCLE_ARCHIVED),
    )
    since = reference - timedelta(hours=24)
    runs_24h = session.scalar(
        select(func.count()).select_from(KeywordScanRun).where(KeywordScanRun.started_at >= since),
    )
    distinct_24h = session.scalar(
        select(func.count(func.distinct(KeywordScanRun.keyword_id))).where(
            KeywordScanRun.started_at >= since,
        ),
    )
    policy = DEFAULT_SCHEDULING_POLICY
    return KeywordPoolSummary(
        snapshot_at=reference,
        due_now=int(due_now),
        due_next_1h=int(due_1h),
        due_next_24h=int(due_24h),
        not_archived_count=int(not_archived or 0),
        unique_keywords_scanned_last_24h=int(distinct_24h or 0),
        keyword_scan_runs_last_24h=int(runs_24h or 0),
        probation_interval_hours=policy.probation_interval_hours,
        active_interval_hours=policy.active_interval_hours,
        weak_interval_hours=policy.weak_interval_hours,
        failed_scan_retry_hours=policy.failed_scan_retry_hours,
    )
