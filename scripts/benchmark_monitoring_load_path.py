"""Measure monitoring load-path SQL volume (read-only)."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("RADAR_SQL_ECHO", "false")
os.environ.setdefault("DEBUG", "false")

from sqlalchemy import event

from app.models.db import SessionLocal, engine
from app.services.metrics import utc_now
from app.services.monitoring_video_source import load_monitored_video_states


def main() -> int:
    query_count = 0
    max_in = 0

    def _before(conn, cursor, statement, parameters, context, executemany) -> None:
        nonlocal query_count, max_in
        query_count += 1
        if parameters and isinstance(parameters, dict):
            n = sum(1 for k in parameters if "video_id" in k or k.startswith("id_"))
            max_in = max(max_in, n)
        sql = statement if isinstance(statement, str) else str(statement)
        placeholders = len(re.findall(r"%\(\w+_\d+\)s", sql))
        max_in = max(max_in, placeholders)

    event.listen(engine, "before_cursor_execute", _before, retval=False)
    session = SessionLocal()
    try:
        t0 = time.perf_counter()
        states = load_monitored_video_states(session, now=utc_now())
        elapsed = time.perf_counter() - t0
    finally:
        event.remove(engine, "before_cursor_execute", _before)
        session.close()

    report = {
        "elapsed_seconds": round(elapsed, 3),
        "eligible_state_count": len(states),
        "sql_query_count": query_count,
        "max_in_clause_params": max_in,
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
