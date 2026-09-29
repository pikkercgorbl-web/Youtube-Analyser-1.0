"""SQL inventory for GET /api/operations/overview default mode (Stage 1.19B2)."""

from __future__ import annotations

import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import event

from app.models.db import SessionLocal
from app.services.operations_overview_service import build_operations_overview


def _classify(sql: str) -> str:
    normalized = " ".join(sql.split()).lower()
    if "discovery_worker_state" in normalized:
        return "discovery_worker_state"
    if "monitoring_worker_state" in normalized:
        return "monitoring_worker_state"
    if "target_keywords" in normalized and "next_scan_at" in normalized:
        return "keyword_due_counts"
    if "keyword_scan_runs" in normalized:
        if "group by" in normalized:
            return "discovery_cycle_rank"
        return "discovery_scan_rows"
    if "monitoring_cycle_runs" in normalized:
        return "monitoring_cycles"
    if "video_snapshots" in normalized:
        if "group by" in normalized or "date_trunc" in normalized or "date(captured_at)" in normalized:
            return "snapshot_daily_buckets"
        return "snapshot_summary"
    if "keyword_discovery_hits" in normalized:
        return "maturity_72h"
    return "other"


def main() -> int:
    session = SessionLocal()
    records: list[dict] = []
    by_purpose: defaultdict[str, int] = defaultdict(int)

    def before_cursor_execute(_conn, _cursor, statement, *_a, **_k) -> None:
        purpose = _classify(str(statement))
        by_purpose[purpose] += 1
        records.append(
            {
                "purpose": purpose,
                "started_at": time.perf_counter(),
                "statement_prefix": str(statement)[:120],
            },
        )

    def after_cursor_execute(_conn, _cursor, _statement, *_a, **_k) -> None:
        if records:
            records[-1]["duration_sec"] = round(time.perf_counter() - records[-1]["started_at"], 4)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    event.listen(engine, "after_cursor_execute", after_cursor_execute)
    try:
        start = time.perf_counter()
        build_operations_overview(session)
        total = time.perf_counter() - start
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
        event.remove(engine, "after_cursor_execute", after_cursor_execute)
        session.close()

    report = {
        "total_runtime_sec": round(total, 4),
        "sql_query_count": len(records),
        "by_purpose_count": dict(by_purpose),
        "queries": records,
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
