"""Lifecycle scan intervals and scheduling policy (Stage 1.16B)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.services.metrics import ensure_utc

LIFECYCLE_PROBATION = "probation"
LIFECYCLE_ACTIVE = "active"
LIFECYCLE_WEAK = "weak"
LIFECYCLE_ARCHIVED = "archived"

LIFECYCLE_STATUSES = (
    LIFECYCLE_PROBATION,
    LIFECYCLE_ACTIVE,
    LIFECYCLE_WEAK,
    LIFECYCLE_ARCHIVED,
)

SOURCE_SEED = "seed"
SOURCE_MANUAL = "manual"
SOURCE_SUGGESTION = "suggestion"
SOURCE_RELATED = "related"
SOURCE_CHANNEL = "channel"
SOURCE_LLM = "llm"
SOURCE_EXPLORATION = "exploration"


def is_exploration_query_anchor(record: object) -> bool:
    """Anchor keywords hold exploration query text; they must not enter seed discovery scans."""
    source = getattr(record, "source_type", None)
    parent_id = getattr(record, "parent_keyword_id", None)
    return source == SOURCE_EXPLORATION and parent_id is None

PROBATION_READY_SCAN_COUNT = 3

# Tie-break only: lower sorts earlier when overdue is similar.
LIFECYCLE_TIEBREAK_ORDER = {
    LIFECYCLE_PROBATION: 0,
    LIFECYCLE_ACTIVE: 1,
    LIFECYCLE_WEAK: 2,
    LIFECYCLE_ARCHIVED: 99,
}


@dataclass(frozen=True, slots=True)
class KeywordSchedulingPolicy:
    probation_interval_hours: float = 6.0
    active_interval_hours: float = 24.0
    weak_interval_hours: float = 72.0
    failed_scan_retry_hours: float = 2.0

    def interval_seconds_for(self, lifecycle_status: str) -> int | None:
        if lifecycle_status == LIFECYCLE_ARCHIVED:
            return None
        if lifecycle_status == LIFECYCLE_PROBATION:
            return int(self.probation_interval_hours * 3600)
        if lifecycle_status == LIFECYCLE_WEAK:
            return int(self.weak_interval_hours * 3600)
        return int(self.active_interval_hours * 3600)

    def next_scan_after_success(
        self,
        lifecycle_status: str,
        finished_at: datetime,
    ) -> datetime | None:
        seconds = self.interval_seconds_for(lifecycle_status)
        if seconds is None:
            return None
        return ensure_utc(finished_at) + timedelta(seconds=seconds)

    def next_scan_after_failure(self, finished_at: datetime) -> datetime:
        return ensure_utc(finished_at) + timedelta(hours=self.failed_scan_retry_hours)

    def next_scan_after_lifecycle_change(
        self,
        lifecycle_status: str,
        now: datetime,
    ) -> datetime | None:
        if lifecycle_status == LIFECYCLE_ARCHIVED:
            return None
        if lifecycle_status in (LIFECYCLE_ACTIVE, LIFECYCLE_PROBATION):
            return ensure_utc(now)
        seconds = self.interval_seconds_for(lifecycle_status)
        assert seconds is not None
        return ensure_utc(now) + timedelta(seconds=seconds)


DEFAULT_SCHEDULING_POLICY = KeywordSchedulingPolicy()
