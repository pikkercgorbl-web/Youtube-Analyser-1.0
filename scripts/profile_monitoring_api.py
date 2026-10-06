"""Profile monitoring overview + paginated list (read-path diagnostics)."""

from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import event

from app.models.db import SessionLocal
from app.services.monitoring_api_service import get_monitoring_overview, list_monitoring_videos


def _profile_call(session, *, live_planner: bool) -> dict:
    records: list[dict] = []
    by_kind: defaultdict[str, int] = defaultdict(int)

    def before(_conn, _cursor, statement, *_a, **_k) -> None:
        sql = str(statement).lower()
        if "monitoring_video_queue" in sql:
            kind = "monitoring_video_queue"
        elif "video_snapshots" in sql:
            kind = "video_snapshots"
        elif "videos" in sql:
            kind = "videos"
        else:
            kind = "other"
        by_kind[kind] += 1
        records.append({"kind": kind, "t0": time.perf_counter(), "prefix": str(statement)[:120]})

    def after(_conn, _cursor, _statement, *_a, **_k) -> None:
        if records:
            records[-1]["sec"] = round(time.perf_counter() - records[-1]["t0"], 4)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", before)
    event.listen(engine, "after_cursor_execute", after)
    try:
        t0 = time.perf_counter()
        result = list_monitoring_videos(session, limit=50, offset=0, live_planner=live_planner)
        list_sec = round(time.perf_counter() - t0, 4)
    finally:
        event.remove(engine, "before_cursor_execute", before)
        event.remove(engine, "after_cursor_execute", after)

    snapshot_queries = [r for r in records if r["kind"] == "video_snapshots"]
    queue_queries = [r for r in records if r["kind"] == "monitoring_video_queue"]
    return {
        "live_planner": live_planner,
        "list_page_sec": list_sec,
        "sql_count": len(records),
        "by_kind": dict(by_kind),
        "queue_query_count": len(queue_queries),
        "snapshot_query_count": len(snapshot_queries),
        "page_size": 50,
        "rows_returned": len(result.rows),
        "total_matching_count": result.total,
        "video_ids_enriched": len(result.rows),
        "queue_run_id": result.queue_run_id,
        "queue_source": result.queue_source,
        "slowest": sorted(records, key=lambda r: r.get("sec", 0), reverse=True)[:5],
    }


def main() -> int:
    session = SessionLocal()
    try:
        t0 = time.perf_counter()
        get_monitoring_overview(session, live_planner=False)
        overview_sec = round(time.perf_counter() - t0, 4)

        cycle_list = _profile_call(session, live_planner=False)
        live_list = None
        if os.environ.get("MONITORING_PROFILE_LIVE_PLANNER") == "1":
            live_list = _profile_call(session, live_planner=True)
    finally:
        session.close()

    print(
        json.dumps(
            {
                "overview_sec": overview_sec,
                "list_cycle_snapshot": cycle_list,
                "list_live_planner": live_list,
            },
            indent=2,
            default=str,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
