"""Print latest finished monitoring cycle as single JSON line (no SQL echo)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from migrate import load_dotenv

load_dotenv(ROOT / ".env")
import os

os.environ["DEBUG"] = "false"
os.environ["RADAR_SQL_ECHO"] = "false"

from sqlalchemy import select

from app.models.db import SessionLocal, engine
from app.models.orm import MonitoringCaptureOutcome, MonitoringCycleRun

engine.echo = False

VIDEO = "YXodhWM0RiI"


def main() -> None:
    session = SessionLocal()
    try:
        run = session.scalar(
            select(MonitoringCycleRun)
            .where(MonitoringCycleRun.finished_at.is_not(None))
            .order_by(MonitoringCycleRun.finished_at.desc())
            .limit(1),
        )
        if run is None:
            print(json.dumps({"error": "no_cycle"}))
            return
        yx = session.scalars(
            select(MonitoringCaptureOutcome)
            .where(MonitoringCaptureOutcome.monitoring_run_id == run.run_id)
            .where(MonitoringCaptureOutcome.video_id == VIDEO),
        ).all()
        print(
            json.dumps(
                {
                    "run_id": run.run_id,
                    "started_at": run.started_at.isoformat(),
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                    "cycle_status": run.cycle_status,
                    "selected": run.selected_request_count,
                    "inserted": run.inserted_snapshot_count,
                    "missing": run.missing_count,
                    "fetch_failed": run.fetch_failed_count,
                    "yxodh_outcomes_in_run": [
                        {
                            "checkpoint": r.checkpoint_age_hours,
                            "outcome": r.outcome,
                            "attempted_at": r.attempted_at.isoformat(),
                        }
                        for r in yx
                    ],
                },
                ensure_ascii=False,
            ),
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
