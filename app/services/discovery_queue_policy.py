"""Discovery queue capacity and priority policy (Fix 3C)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.models.orm import TargetKeyword

# Keep in sync with DiscoveryWorkerConfig defaults (avoid import cycle via discovery_cycle).
_DEFAULT_KEYWORD_BATCH_SIZE = 5
_DEFAULT_WORKER_INTERVAL_SECONDS = 300

from app.services.keyword_scheduling_policy import (
    LIFECYCLE_ACTIVE,
    LIFECYCLE_PROBATION,
    SOURCE_MANUAL,
    SOURCE_SEED,
)

_MIN_CYCLES_FOR_MEASURED_CAPACITY = 15
_MEASURED_LOOKBACK_HOURS = 72
# Typical observed when exploration consumes 1 slot (batch 5 → selector 4).
_FALLBACK_SELECTOR_BATCH_SIZE = 4
_FALLBACK_CYCLES_PER_DAY = 186.0

NEVER_SCANNED_BOOST_HOURS = 20.0
STARVATION_BOOST_HOURS = 6.0
STARVATION_OVERDUE_THRESHOLD_HOURS = 48.0


@dataclass(frozen=True, slots=True)
class DiscoveryThroughputEstimate:
    keyword_batch_size: int
    worker_interval_seconds: int
    cycles_per_day: float
    keyword_slots_per_day: float

    @classmethod
    def from_worker_defaults(cls) -> DiscoveryThroughputEstimate:
        batch = max(1, _DEFAULT_KEYWORD_BATCH_SIZE)
        interval = max(1, _DEFAULT_WORKER_INTERVAL_SECONDS)
        cycles = 86_400.0 / float(interval)
        return cls(
            keyword_batch_size=batch,
            worker_interval_seconds=interval,
            cycles_per_day=cycles,
            keyword_slots_per_day=cycles * batch,
        )


def resolve_selector_keyword_batch_size(
    *,
    worker_keyword_batch_size: int = _DEFAULT_KEYWORD_BATCH_SIZE,
    exploration_enabled: bool | None = None,
    exploration_fraction: float | None = None,
) -> int:
    """
    Keyword slots passed to select_discovery_keywords after exploration split.

    Mirrors discovery_cycle: split_discovery_batch_slots(worker_batch) → seed_slots.
    """
    from app.services.topic_exploration_batch_split import split_discovery_batch_slots

    if exploration_enabled is None or exploration_fraction is None:
        from app.services.topic_exploration_runtime_config import topic_exploration_runtime_settings

        cfg = topic_exploration_runtime_settings
        exploration_enabled = cfg.topic_exploration_in_discovery
        exploration_fraction = cfg.topic_exploration_batch_fraction

    seed_slots, _expl = split_discovery_batch_slots(
        worker_keyword_batch_size,
        exploration_enabled=bool(exploration_enabled),
        exploration_fraction=float(exploration_fraction),
    )
    return max(1, seed_slots)


def estimate_daily_keyword_slots(
    *,
    batch_size: int | None = None,
    interval_seconds: int | None = None,
) -> float:
    est = DiscoveryThroughputEstimate.from_worker_defaults()
    batch = max(1, batch_size or est.keyword_batch_size)
    interval = max(1, interval_seconds or _DEFAULT_WORKER_INTERVAL_SECONDS)
    return (86_400.0 / float(interval)) * batch


def is_priority_discovery_keyword(record: TargetKeyword) -> bool:
    """Seed/manual and active lifecycle keys get reserved scan slots."""
    if record.source_type in (SOURCE_SEED, SOURCE_MANUAL):
        return True
    return record.lifecycle_status == LIFECYCLE_ACTIVE


def priority_reserved_slots(batch_size: int) -> int:
    """
    Reserve slots within existing batch (no worker change).
    batch=5 → 2 priority, 3 general; batch=4 → 2 priority, 2 general.
    """
    total = max(1, int(batch_size))
    if total == 1:
        return 1
    reserved = max(1, total // 2)
    return min(reserved, total - 1)


def probation_keyword_slots_per_day(
    *,
    batch_size: int | None = None,
    interval_seconds: int | None = None,
    reserved_slots: int | None = None,
    cycles_per_day: float | None = None,
) -> float:
    """
    Structural upper bound on general (probation) slots if priority fills reserved every cycle.

    Prefer resolve_probation_slots_per_day_for_scheduling() for honest intervals.
    """
    batch = max(1, int(batch_size or _FALLBACK_SELECTOR_BATCH_SIZE))
    reserved = priority_reserved_slots(batch) if reserved_slots is None else int(reserved_slots)
    general_per_cycle = max(0, batch - reserved)
    if cycles_per_day is not None:
        cycles = float(cycles_per_day)
    else:
        interval = max(1, int(interval_seconds or _DEFAULT_WORKER_INTERVAL_SECONDS))
        cycles = 86_400.0 / float(interval)
    return cycles * float(general_per_cycle)


def _count_scan_run_rows(
    session,
    *,
    since: datetime,
    until: datetime,
    priority_only: bool = False,
    probation_only: bool = False,
) -> int:
    from sqlalchemy import func, select

    from app.models.orm import KeywordScanRun
    from app.services.metrics import ensure_utc

    start = ensure_utc(since)
    end = ensure_utc(until)
    q = (
        select(func.count())
        .select_from(KeywordScanRun)
        .join(TargetKeyword, TargetKeyword.id == KeywordScanRun.keyword_id)
        .where(KeywordScanRun.started_at >= start, KeywordScanRun.started_at < end)
    )
    if priority_only:
        q = q.where(
            (TargetKeyword.source_type.in_((SOURCE_SEED, SOURCE_MANUAL)))
            | (TargetKeyword.lifecycle_status == LIFECYCLE_ACTIVE),
        )
    if probation_only:
        q = q.where(TargetKeyword.lifecycle_status == LIFECYCLE_PROBATION)
    return int(session.scalar(q) or 0)


@dataclass(frozen=True, slots=True)
class ProbationCapacityEstimate:
    probation_scan_slots_per_day: float
    source: str
    selector_keyword_batch_size: int
    reserved_slots_per_batch: int
    measured_cycles_per_day: float | None
    measured_keyword_scan_runs_per_day: float | None
    structural_general_slots_per_day: float | None


def resolve_probation_slots_per_day_for_scheduling(
    session,
    *,
    now: datetime,
    lookback_hours: int = _MEASURED_LOOKBACK_HOURS,
    min_cycles: int = _MIN_CYCLES_FOR_MEASURED_CAPACITY,
) -> ProbationCapacityEstimate:
    """
    Honest probation throughput for next_scan_at scheduling.

    Primary: measured probation scan-run rows/day (includes spillover from unused priority).
    Fallback: structural general slots using selector batch=4 and typical cycle rate.
    """
    from app.services.metrics import ensure_utc

    reference = ensure_utc(now)
    since = reference - timedelta(hours=lookback_hours)
    cap = observed_discovery_capacity(session, since=since, until=reference)
    selector_batch = resolve_selector_keyword_batch_size()
    reserved = priority_reserved_slots(selector_batch)

    hours = float(lookback_hours)
    cycles_day = cap["completed_discovery_cycles"] * (24.0 / hours) if hours else 0.0
    scans_day = cap["keyword_scan_run_rows"] * (24.0 / hours) if hours else 0.0
    probation_rows_day = _count_scan_run_rows(
        session,
        since=since,
        until=reference,
        probation_only=True,
    ) * (24.0 / hours)

    structural_general = probation_keyword_slots_per_day(
        batch_size=selector_batch,
        cycles_per_day=cycles_day if cycles_day > 0 else None,
    )

    if cap["completed_discovery_cycles"] >= min_cycles and probation_rows_day > 0:
        # Pessimistic: use min(measured probation, structural) so we do not over-promise frequency.
        slots = min(probation_rows_day, structural_general) if structural_general > 0 else probation_rows_day
        return ProbationCapacityEstimate(
            probation_scan_slots_per_day=max(1.0, slots),
            source="measured_probation_scan_runs",
            selector_keyword_batch_size=selector_batch,
            reserved_slots_per_batch=reserved,
            measured_cycles_per_day=round(cycles_day, 2),
            measured_keyword_scan_runs_per_day=round(scans_day, 2),
            structural_general_slots_per_day=round(structural_general, 2),
        )

    fallback_slots = probation_keyword_slots_per_day(
        batch_size=_FALLBACK_SELECTOR_BATCH_SIZE,
        cycles_per_day=_FALLBACK_CYCLES_PER_DAY,
    )
    return ProbationCapacityEstimate(
        probation_scan_slots_per_day=max(1.0, fallback_slots),
        source="fallback_insufficient_cycle_history",
        selector_keyword_batch_size=selector_batch,
        reserved_slots_per_batch=priority_reserved_slots(_FALLBACK_SELECTOR_BATCH_SIZE),
        measured_cycles_per_day=round(cycles_day, 2) if cycles_day else None,
        measured_keyword_scan_runs_per_day=round(scans_day, 2) if scans_day else None,
        structural_general_slots_per_day=round(fallback_slots, 2),
    )


def effective_probation_interval_hours(
    *,
    probation_due_count: int,
    probation_slots_per_day: float,
    policy_min_hours: float = 6.0,
) -> float:
    """
    Estimated rotation interval at current backlog (not a guaranteed SLA).

    When backlog is large, result exceeds policy_min_hours.
    """
    due = max(0, int(probation_due_count))
    slots = max(1.0, float(probation_slots_per_day))
    if due == 0:
        return policy_min_hours
    sustainable = 24.0 * due / slots
    if sustainable <= policy_min_hours:
        return policy_min_hours
    return sustainable


def effective_probation_interval_seconds(
    *,
    probation_due_count: int,
    probation_slots_per_day: float | None = None,
    policy_min_hours: float = 6.0,
) -> int:
    slots = probation_slots_per_day if probation_slots_per_day is not None else 1.0
    hours = effective_probation_interval_hours(
        probation_due_count=probation_due_count,
        probation_slots_per_day=slots,
        policy_min_hours=policy_min_hours,
    )
    return int(hours * 3600)


def effective_probation_interval_seconds_for_session(
    session,
    *,
    now: datetime,
    probation_due_count: int | None = None,
) -> tuple[int, ProbationCapacityEstimate]:
    due = (
        probation_due_count
        if probation_due_count is not None
        else count_probation_due(session, now=now)
    )
    cap = resolve_probation_slots_per_day_for_scheduling(session, now=now)
    seconds = effective_probation_interval_seconds(
        probation_due_count=due,
        probation_slots_per_day=cap.probation_scan_slots_per_day,
    )
    return seconds, cap


def observed_discovery_capacity(
    session,
    *,
    since,
    until,
) -> dict:
    """
    Read-only metrics from keyword_scan_runs (distinct from unique keywords).
    """
    from sqlalchemy import select

    from app.models.orm import KeywordScanRun
    from app.services.metrics import ensure_utc

    start = ensure_utc(since)
    end = ensure_utc(until)
    runs = list(
        session.scalars(
            select(KeywordScanRun).where(
                KeywordScanRun.started_at >= start,
                KeywordScanRun.started_at < end,
            ),
        ).all(),
    )
    by_cycle: dict[str, list] = {}
    for row in runs:
        by_cycle.setdefault(row.discovery_run_id, []).append(row)
    completed_cycles = len(by_cycle)
    successful = [r for r in runs if (r.status or "").lower() in ("ok", "completed", "success")]
    unique_kw = len({r.keyword_id for r in runs})
    slot_rows = len(runs)
    return {
        "completed_discovery_cycles": completed_cycles,
        "keyword_scan_run_rows": slot_rows,
        "successful_scan_runs": len(successful),
        "unique_keywords_scanned": unique_kw,
        "avg_scans_per_cycle": round(slot_rows / completed_cycles, 3) if completed_cycles else 0.0,
    }


def count_probation_due(session, *, now) -> int:
    from sqlalchemy import func, or_, select

    from app.models.orm import TargetKeyword
    from app.services.metrics import ensure_utc

    reference = ensure_utc(now)
    due_clause = or_(
        TargetKeyword.next_scan_at.is_(None),
        TargetKeyword.next_scan_at <= reference,
    )
    return int(
        session.scalar(
            select(func.count())
            .select_from(TargetKeyword)
            .where(
                TargetKeyword.lifecycle_status == LIFECYCLE_PROBATION,
                due_clause,
            ),
        )
        or 0,
    )
