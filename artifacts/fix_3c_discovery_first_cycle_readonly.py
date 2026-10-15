"""After Discovery restart: read latest cycle scan details (read-only)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from migrate import load_dotenv

load_dotenv(ROOT / ".env")

from sqlalchemy import select

from app.models.db import SessionLocal, engine
from app.models.orm import KeywordScanRun, TargetKeyword
from app.services.discovery_queue_policy import is_priority_discovery_keyword

engine.echo = False


def main() -> None:
    session = SessionLocal()
    try:
        latest_run_id = session.scalar(
            select(KeywordScanRun.discovery_run_id)
            .order_by(KeywordScanRun.started_at.desc())
            .limit(1),
        )
        if not latest_run_id:
            print(json.dumps({"error": "no_scan_runs"}))
            return
        runs = list(
            session.scalars(
                select(KeywordScanRun)
                .where(KeywordScanRun.discovery_run_id == latest_run_id)
                .order_by(KeywordScanRun.started_at),
            ).all(),
        )
        items = []
        seed_active = 0
        probation = 0
        for run in runs:
            tk = session.get(TargetKeyword, run.keyword_id)
            if tk is None:
                continue
            if is_priority_discovery_keyword(tk):
                seed_active += 1
            if tk.lifecycle_status == "probation":
                probation += 1
            items.append(
                {
                    "keyword_id": tk.id,
                    "keyword": tk.keyword[:60],
                    "source_type": tk.source_type,
                    "lifecycle_status": tk.lifecycle_status,
                    "scan_status": run.status,
                    "error_summary": (run.error_summary or "")[:120] or None,
                    "runtime_seconds": run.runtime_seconds,
                    "next_scan_at": tk.next_scan_at.isoformat() if tk.next_scan_at else None,
                    "scan_interval_seconds": tk.scan_interval_seconds,
                },
            )
        started = min(r.started_at for r in runs)
        finished = max(r.finished_at for r in runs)
        duration = (finished - started).total_seconds()
        print(
            json.dumps(
                {
                    "discovery_run_id": latest_run_id,
                    "started_at": started.isoformat(),
                    "finished_at": finished.isoformat(),
                    "cycle_duration_seconds": round(duration, 3),
                    "keyword_scan_count": len(runs),
                    "seed_or_active_priority_count": seed_active,
                    "probation_count": probation,
                    "scans": items,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
