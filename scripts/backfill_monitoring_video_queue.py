"""One-shot queue materialization from latest cycle run_id (post-deploy backfill)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models.db import SessionLocal
from app.services.monitoring_api_service import build_active_monitoring_enriched
from app.services.monitoring_cycle_run_storage import get_latest_monitoring_cycle_run
from app.services.monitoring_queue_persist import replace_monitoring_video_queue


def main() -> int:
    session = SessionLocal()
    try:
        latest = get_latest_monitoring_cycle_run(session)
        if latest is None:
            print("No monitoring cycle run found; aborting.")
            return 1
        enriched, _, _ = build_active_monitoring_enriched(session)
        count = replace_monitoring_video_queue(session, latest.run_id, enriched)
        session.commit()
        print(f"Backfilled monitoring_video_queue run_id={latest.run_id} rows={count}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
