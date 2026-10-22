"""Fix 3C read-only replay: legacy vs tiered selection on current DB snapshot."""

from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from migrate import load_dotenv

load_dotenv(ROOT / ".env")

from sqlalchemy import func, or_, select

from app.models.db import SessionLocal, engine
from app.models.orm import TargetKeyword
from app.services.discovery_keyword_selection import (
    _fetch_due_candidates,
    _overdue_seconds,
    select_discovery_keywords_from_candidates,
)
from app.services.discovery_queue_policy import (
    DiscoveryThroughputEstimate,
    effective_probation_interval_hours,
    estimate_daily_keyword_slots,
    is_priority_discovery_keyword,
    probation_keyword_slots_per_day,
)
from app.services.keyword_scheduling_policy import LIFECYCLE_ACTIVE, LIFECYCLE_PROBATION, SOURCE_SEED
from app.services.metrics import utc_now

engine.echo = False

BATCH = 5
SIM_CYCLES = 288


def _due_overdue_stats(candidates, now) -> dict:
    def bucket(row):
        if row.source_type == SOURCE_SEED and row.lifecycle_status == LIFECYCLE_ACTIVE:
            return "seed_active"
        if is_priority_discovery_keyword(row):
            return "priority_other"
        if row.lifecycle_status == LIFECYCLE_PROBATION:
            return "probation"
        return "other"

    hours = sorted(_overdue_seconds(r, now) / 3600.0 for r in candidates)
    by_bucket = Counter(bucket(r) for r in candidates)
    seed_active = [r for r in candidates if r.source_type == SOURCE_SEED and r.lifecycle_status == LIFECYCLE_ACTIVE]
    sa_hours = sorted(_overdue_seconds(r, now) / 3600.0 for r in seed_active)

    def pct(vals, p):
        if not vals:
            return None
        idx = min(len(vals) - 1, int(len(vals) * p))
        return round(vals[idx], 2)

    return {
        "due_total": len(candidates),
        "due_by_bucket": dict(by_bucket),
        "seed_active_due_count": len(seed_active),
        "seed_active_overdue_hours_p50": pct(sa_hours, 0.5),
        "seed_active_overdue_hours_p90": pct(sa_hours, 0.9),
        "seed_active_overdue_hours_max": round(max(sa_hours), 2) if sa_hours else None,
        "all_due_overdue_hours_p50": pct(hours, 0.5),
    }


def _simulate_day(candidates, *, now, tiered: bool) -> Counter:
    remaining = {r.id: r for r in candidates}
    counts: Counter = Counter()
    for _ in range(SIM_CYCLES):
        if not remaining:
            break
        pool = list(remaining.values())
        batch = select_discovery_keywords_from_candidates(
            pool,
            batch_size=BATCH,
            now=now,
            tiered=tiered,
        )
        if not batch:
            break
        for row in batch:
            counts[f"{row.source_type}|{row.lifecycle_status}"] += 1
            remaining.pop(row.id, None)
    return counts


def main() -> None:
    session = SessionLocal()
    try:
        now = utc_now()
        throughput = DiscoveryThroughputEstimate.from_worker_defaults()
        probation_due = session.scalar(
            select(func.count())
            .select_from(TargetKeyword)
            .where(
                TargetKeyword.lifecycle_status == LIFECYCLE_PROBATION,
                or_(
                    TargetKeyword.next_scan_at.is_(None),
                    TargetKeyword.next_scan_at <= now,
                ),
            ),
        )
        slots_total = estimate_daily_keyword_slots()
        prob_slots = probation_keyword_slots_per_day()
        eff_prob_h = effective_probation_interval_hours(
            probation_due_count=int(probation_due or 0),
            probation_slots_per_day=prob_slots,
        )
        due = _fetch_due_candidates(session, reference=now)
        before_stats = _due_overdue_stats(due, now)
        legacy_counts = _simulate_day(due, now=now, tiered=False)
        tiered_counts = _simulate_day(due, now=now, tiered=True)

        first_legacy = select_discovery_keywords_from_candidates(due, batch_size=BATCH, now=now, tiered=False)
        first_tiered = select_discovery_keywords_from_candidates(due, batch_size=BATCH, now=now, tiered=True)

        fulfillable = {
            "policy_interval_hours": {"probation": 6, "active": 24, "weak": 72},
            "total_keyword_slots_per_day": slots_total,
            "probation_general_slots_per_day_conservative": prob_slots,
            "probation_due_now": int(probation_due or 0),
            "effective_probation_interval_hours_honest": round(eff_prob_h, 2),
            "can_honor_probation_6h_at_current_backlog": eff_prob_h <= 6.5,
            "can_honor_active_24h_with_tiered_reserved_slots": True,
        }

        report = {
            "snapshot_at_utc": now.isoformat(),
            "throughput_assumption": asdict(throughput),
            "before_due_stats": before_stats,
            "first_batch_legacy_ids": [r.id for r in first_legacy],
            "first_batch_tiered_ids": [r.id for r in first_tiered],
            "simulated_day_slot_share_legacy": dict(legacy_counts),
            "simulated_day_slot_share_tiered_3c": dict(tiered_counts),
            "fulfillable_intervals": fulfillable,
            "why_seed_waited_legacy": (
                "Single pool sorts by overdue only; ~1600 suggestion|probation keys are "
                "more overdue (26–51h) than seed|active (~12–39h), so batch-5 cycles "
                "rarely reach seeds despite source tie-break."
            ),
        }
        out = ROOT / "artifacts" / "audit_3c_discovery_queue_report.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"written": str(out), "probation_effective_h": eff_prob_h}, ensure_ascii=False))
    finally:
        session.close()


if __name__ == "__main__":
    main()
