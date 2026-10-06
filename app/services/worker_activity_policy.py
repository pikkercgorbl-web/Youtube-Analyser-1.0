"""Worker operational liveness (activity), separate from lock ownership (Stage 1.20C.2)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.services.metrics import ensure_utc

ActivityState = Literal["active_recently", "stale_activity", "unknown", "error"]

# Allow several missed cycles before calling activity stale (not lock stale).
STALE_ACTIVITY_MISSED_INTERVALS = 4
MIN_STALE_ACTIVITY_SECONDS = 600


def stale_activity_threshold_seconds(expected_interval_seconds: int) -> int:
    interval = max(1, int(expected_interval_seconds))
    return max(MIN_STALE_ACTIVITY_SECONDS, interval * STALE_ACTIVITY_MISSED_INTERVALS)


def _activity_age_seconds(now: datetime, last_activity_at: datetime | None) -> float | None:
    if last_activity_at is None:
        return None
    return (ensure_utc(now) - ensure_utc(last_activity_at)).total_seconds()


def classify_worker_activity(
    *,
    now: datetime,
    worker_expected_running: bool,
    last_activity_at: datetime | None,
    expected_interval_seconds: int,
    latest_cycle_failed: bool,
) -> tuple[ActivityState, datetime | None]:
    """
    Operational liveness from cycle finish / heartbeat timestamps.
    lock_acquired_at must not be passed here.
    """
    if latest_cycle_failed:
        return "error", last_activity_at

    if not worker_expected_running:
        return "unknown", last_activity_at

    age = _activity_age_seconds(now, last_activity_at)
    threshold = stale_activity_threshold_seconds(expected_interval_seconds)

    if age is None:
        return "unknown", last_activity_at

    if age <= threshold:
        return "active_recently", last_activity_at

    return "stale_activity", last_activity_at
