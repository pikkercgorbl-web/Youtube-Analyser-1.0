"""Profile keyword performance list read path (Stage 1.20E.4)."""

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

from sqlalchemy import event, func, select

from app.models.db import SessionLocal
from app.models.orm import KeywordDiscoveryHit, VideoSnapshot
from app.services.keyword_performance_service import list_keyword_performance


def _profile(session, *, live_evaluation: bool, include_breakout: bool, include_delayed: bool) -> dict:
    records: list[dict] = []
    by_kind: defaultdict[str, int] = defaultdict(int)

    def before(_conn, _cursor, statement, *_a, **_k) -> None:
        sql = str(statement).lower()
        if "keyword_discovery_hits" in sql:
            kind = "discovery_hits"
        elif "video_snapshots" in sql:
            kind = "video_snapshots"
        elif "keyword_performance" in sql:
            kind = "keyword_performance_snapshot"
        elif "target_keywords" in sql:
            kind = "target_keywords"
        elif "videos" in sql:
            kind = "videos"
        else:
            kind = "other"
        by_kind[kind] += 1
        records.append({"kind": kind, "t0": time.perf_counter()})

    def after(*_a, **_k) -> None:
        if records and "sec" not in records[-1]:
            records[-1]["sec"] = round(time.perf_counter() - records[-1]["t0"], 4)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", before)
    event.listen(engine, "after_cursor_execute", after)
    try:
        t0 = time.perf_counter()
        result = list_keyword_performance(
            session,
            limit=100,
            offset=0,
            include_breakout=include_breakout,
            include_delayed=include_delayed,
            live_evaluation=live_evaluation,
        )
        duration = round(time.perf_counter() - t0, 4)
    finally:
        event.remove(engine, "before_cursor_execute", before)
        event.remove(engine, "after_cursor_execute", after)

    hit_total = session.scalar(select(func.count()).select_from(KeywordDiscoveryHit)) or 0
    snap_total = session.scalar(select(func.count()).select_from(VideoSnapshot)) or 0
    return {
        "live_evaluation": live_evaluation,
        "include_breakout": include_breakout,
        "include_delayed": include_delayed,
        "duration_sec": duration,
        "sql_count": len(records),
        "by_kind": dict(by_kind),
        "rows_returned": len(result.items),
        "total": result.total,
        "data_source": result.data_source,
        "discovery_hits_table_rows": int(hit_total),
        "video_snapshots_table_rows": int(snap_total),
        "slowest": sorted(records, key=lambda r: r.get("sec", 0), reverse=True)[:5],
    }


def main() -> int:
    session = SessionLocal()
    try:
        snapshot_discovery = _profile(
            session,
            live_evaluation=False,
            include_breakout=False,
            include_delayed=False,
        )
        snapshot_outcomes = _profile(
            session,
            live_evaluation=False,
            include_breakout=False,
            include_delayed=True,
        )
        live = None
        if os.environ.get("KEYWORD_PERFORMANCE_PROFILE_LIVE") == "1":
            live = _profile(
                session,
                live_evaluation=True,
                include_breakout=True,
                include_delayed=True,
            )
    finally:
        session.close()

    print(
        json.dumps(
            {
                "list_snapshot_discovery_tab": snapshot_discovery,
                "list_snapshot_outcomes_tab": snapshot_outcomes,
                "list_live_full": live,
            },
            indent=2,
            default=str,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
