"""Fix 3C capacity verification: spillover, measured cycles, sequential batch replay."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from migrate import load_dotenv

load_dotenv(ROOT / ".env")

from datetime import timedelta

from app.models.db import SessionLocal, engine
from app.services.discovery_keyword_selection import (
    _fetch_due_candidates,
    select_discovery_keywords_from_candidates,
)
from app.services.discovery_queue_policy import (
    effective_probation_interval_hours,
    estimate_daily_keyword_slots,
    is_priority_discovery_keyword,
    observed_discovery_capacity,
    priority_reserved_slots,
    probation_keyword_slots_per_day,
)
from app.services.metrics import utc_now

engine.echo = False

BATCH = 5
RESERVED = priority_reserved_slots(BATCH)
SEED_IDS = [127, 128, 129, 130, 131]


def _sequential_replay(candidates, *, now, batches: int = 12):
    remaining = {r.id: r for r in candidates}
    traces = []
    never_checked_selected = 0
    old_probation_selected = 0
    seed_selected = []
    for batch_idx in range(batches):
        if not remaining:
            break
        pool = list(remaining.values())
        picked = select_discovery_keywords_from_candidates(
            pool,
            batch_size=BATCH,
            now=now,
            tiered=True,
        )
        if not picked:
            break
        detail = []
        for row in picked:
            detail.append(
                {
                    "id": row.id,
                    "keyword": row.keyword[:40],
                    "source": row.source_type,
                    "lifecycle": row.lifecycle_status,
                    "priority": is_priority_discovery_keyword(row),
                    "last_checked": row.last_checked.isoformat() if row.last_checked else None,
                },
            )
            if row.id in SEED_IDS:
                seed_selected.append({"batch": batch_idx, "id": row.id})
            if row.lifecycle_status == "probation" and row.last_checked is None:
                never_checked_selected += 1
            if row.lifecycle_status == "probation" and row.last_checked is not None:
                old_probation_selected += 1
            remaining.pop(row.id, None)
        traces.append({"batch_index": batch_idx, "picked": detail})
    return {
        "batches_traced": traces,
        "seed_127_131_selected": seed_selected,
        "never_checked_probation_picks": never_checked_selected,
        "old_probation_picks": old_probation_selected,
        "remaining_due_after": len(remaining),
    }


def main() -> None:
    session = SessionLocal()
    try:
        now = utc_now()
        theoretical_total_slots = estimate_daily_keyword_slots()
        theoretical_prob_slots = probation_keyword_slots_per_day()
        probation_due = __import__(
            "app.services.discovery_queue_policy",
            fromlist=["count_probation_due"],
        ).count_probation_due(session, now=now)
        interval_old_formula = 24.0 * probation_due / theoretical_total_slots
        interval_new_formula = effective_probation_interval_hours(
            probation_due_count=probation_due,
            probation_slots_per_day=theoretical_prob_slots,
        )

        windows = {}
        for hours in (24, 72):
            since = now - timedelta(hours=hours)
            cap = observed_discovery_capacity(session, since=since, until=now)
            hours_f = float(hours)
            cap["scan_runs_per_day_extrapolated"] = round(
                cap["keyword_scan_run_rows"] * (24.0 / hours_f),
                1,
            )
            cap["unique_keywords_per_day_extrapolated"] = round(
                cap["unique_keywords_scanned"] * (24.0 / hours_f),
                1,
            )
            cap["cycles_per_day_extrapolated"] = round(
                cap["completed_discovery_cycles"] * (24.0 / hours_f),
                1,
            )
            if cap["keyword_scan_run_rows"] > 0:
                cap["measured_probation_interval_if_all_probation_due"] = round(
                    24.0
                    * probation_due
                    / max(1.0, cap["scan_runs_per_day_extrapolated"]),
                    2,
                )
            windows[f"last_{hours}h"] = cap

        due = _fetch_due_candidates(session, reference=now)
        replay = _sequential_replay(due, now=now, batches=12)

        spillover_code = (
            "Tiered selector fills priority[:reserved_n] then general until batch full; "
            "if priority due < reserved_n, unused reserved capacity is filled from general "
            "(see test_unused_priority_slots_spill_to_general)."
        )

        report = {
            "snapshot_at_utc": now.isoformat(),
            "code_spillover": spillover_code,
            "theoretical_batch_5_interval_300s": {
                "total_keyword_slots_per_day": theoretical_total_slots,
                "reserved_slots_per_batch": RESERVED,
                "general_probation_slots_per_day_conservative": theoretical_prob_slots,
                "formula_old_24xdue_1440_hours": round(interval_old_formula, 2),
                "formula_new_24xdue_general_slots_hours": round(interval_new_formula, 2),
                "note_old_formula_ignores_reserved_and_is_optimistic": True,
            },
            "probation_due_now": probation_due,
            "measured_windows": windows,
            "sequential_batch_replay_12x5": replay,
            "conclusions": {
                "promise_probation_6h_at_current_backlog": False,
                "honest_scheduling_interval_hours": round(interval_new_formula, 2),
                "exploration_slots_not_in_theoretical_prob_budget": True,
            },
        }
        out = ROOT / "artifacts" / "audit_3c_capacity_verification_report.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"written": str(out), "interval_h": interval_new_formula}, ensure_ascii=False))
    finally:
        session.close()


if __name__ == "__main__":
    main()
