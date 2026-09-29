"""Benchmark operations overview read model (Stage 1.19B / 1.19B1 / 1.19B2)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import event, func, select

from app.models.db import SessionLocal
from app.models.orm import KeywordDiscoveryHit, KeywordScanRun, MonitoringCycleRun, TargetKeyword
from app.services.operations_maturity_sql import compute_maturity_aggregate_sql
from app.services.operations_overview_service import build_operations_overview


def _run_with_query_count(session, **kwargs) -> tuple[dict, int, float]:
    engine = session.get_bind()
    count = 0

    def before_cursor_execute(*_a, **_k) -> None:
        nonlocal count
        count += 1

    event.listen(engine, "before_cursor_execute", before_cursor_execute, retval=False)
    try:
        start = time.perf_counter()
        overview = build_operations_overview(session, **kwargs)
        elapsed = time.perf_counter() - start
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)

    matured = overview.keyword_outcomes.matured_72h_count
    payload = {
        "runtime_seconds": round(elapsed, 4),
        "sql_query_count": count,
        "target_keywords": session.scalar(select(func.count()).select_from(TargetKeyword)) or 0,
        "keyword_scan_runs": session.scalar(select(func.count()).select_from(KeywordScanRun)) or 0,
        "monitoring_cycle_runs": session.scalar(select(func.count()).select_from(MonitoringCycleRun)) or 0,
        "discovery_hits_raw": session.scalar(select(func.count()).select_from(KeywordDiscoveryHit)) or 0,
        "matured_baselines": matured,
        "valid_72h": overview.keyword_outcomes.valid_72h_outcome_count,
        "missing_72h": overview.keyword_outcomes.missing_72h_outcome_count,
        "snapshots_last_24h": overview.snapshots.snapshots_last_24h,
    }
    return payload, count, elapsed


def _maturity_only(session, mode: str) -> tuple[dict, float]:
    engine = session.get_bind()
    count = 0

    def before_cursor_execute(*_a, **_k) -> None:
        nonlocal count
        count += 1

    event.listen(engine, "before_cursor_execute", before_cursor_execute, retval=False)
    try:
        start = time.perf_counter()
        row = compute_maturity_aggregate_sql(session, attribution_mode=mode)
        elapsed = time.perf_counter() - start
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
    return {
        "maturity_runtime_seconds": round(elapsed, 4),
        "maturity_sql_queries": count,
        "attributed": row.attributed_observation_count,
        "matured": row.matured_72h_count,
        "valid": row.valid_72h_outcome_count,
        "missing": row.missing_72h_outcome_count,
    }, elapsed


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _run_iterations(session, iterations: int = 3, **kwargs) -> dict:
    runtimes: list[float] = []
    counts: list[int] = []
    last_payload: dict = {}
    for _ in range(iterations):
        payload, count, elapsed = _run_with_query_count(session, **kwargs)
        runtimes.append(elapsed)
        counts.append(count)
        last_payload = payload
    return {
        **last_payload,
        "iterations": iterations,
        "runtime_median_sec": round(_median(runtimes), 4),
        "runtime_min_sec": round(min(runtimes), 4),
        "runtime_max_sec": round(max(runtimes), 4),
        "sql_query_count_median": int(_median([float(c) for c in counts])),
    }


def main() -> int:
    session = SessionLocal()
    try:
        report = {
            "note": "1.19B2 consolidated; baseline ~32 SQL / ~5-11s (1.19B1)",
            "maturity_all_hits": _maturity_only(session, "all_hits")[0],
            "A_default": _run_iterations(session, iterations=3),
            "B_with_history": _run_iterations(
                session,
                iterations=3,
                discovery_history_limit=10,
                monitoring_history_limit=10,
            ),
            "C_live_planner": _run_iterations(
                session,
                iterations=3,
                include_live_monitoring_planner=True,
                discovery_history_limit=10,
                monitoring_history_limit=10,
            ),
        }
        print(json.dumps(report, indent=2))
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
