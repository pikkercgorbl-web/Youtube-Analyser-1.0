"""Read-only snapshot for Fix 3B.1 live monitoring cycle verification."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from migrate import load_dotenv

load_dotenv(ROOT / ".env")

from sqlalchemy import select, text

from app.models.db import SessionLocal
from app.models.orm import MonitoringCaptureOutcome, MonitoringCycleRun, MonitoringWorkerState
from app.services.metrics import ensure_utc, utc_now
from app.services.monitoring_missing_retry import (
    load_latest_missing_attempt_at,
    missing_capture_retry_interval_seconds,
)
from app.services.snapshot_collection_policy import SnapshotCollectionPolicy

VIDEO_ID = "YXodhWM0RiI"
CHECKPOINT = 24


def main() -> None:
    import os

    url = os.environ.get("DATABASE_URL") or ""
    if "supabase" in url.lower():
        raise SystemExit("Refusing: DATABASE_URL looks like Supabase")
    if "youtube_radar_restore_check" not in url and "5433" not in url:
        raise SystemExit(f"Refusing unexpected DATABASE_URL target: {url[:80]}...")
    session = SessionLocal()
    try:
        dbinfo = session.execute(
            text("SELECT current_database(), inet_server_addr()::text, inet_server_port()"),
        ).one()
        url_host_hint = url.split("@")[-1].split("/")[0] if "@" in url else "local"
        worker = session.get(MonitoringWorkerState, 1)
        last_cycle = session.scalar(
            select(MonitoringCycleRun)
            .where(MonitoringCycleRun.finished_at.is_not(None))
            .order_by(MonitoringCycleRun.finished_at.desc())
            .limit(1),
        )
        running_cycle = session.scalar(
            select(MonitoringCycleRun)
            .where(MonitoringCycleRun.finished_at.is_(None))
            .order_by(MonitoringCycleRun.started_at.desc())
            .limit(1),
        )
        latest_missing = load_latest_missing_attempt_at(session, {(VIDEO_ID, CHECKPOINT)})
        last_missing_at = latest_missing.get((VIDEO_ID, CHECKPOINT))
        policy = SnapshotCollectionPolicy()
        # Approximate current age for retry calc: use now vs last attempt context
        retry_interval_s = missing_capture_retry_interval_seconds(
            checkpoint_age_hours=CHECKPOINT,
            current_age_hours=25.0,
            policy=policy,
        )
        retry_at = None
        if last_missing_at is not None:
            retry_at = last_missing_at.timestamp() + retry_interval_s

        recent_outcomes = session.scalars(
            select(MonitoringCaptureOutcome)
            .where(MonitoringCaptureOutcome.video_id == VIDEO_ID)
            .order_by(MonitoringCaptureOutcome.attempted_at.desc())
            .limit(5),
        ).all()

        payload = {
            "checked_at_utc": utc_now().isoformat(),
            "database": {
                "name": dbinfo[0],
                "host": dbinfo[1],
                "port": dbinfo[2],
                "url_host_hint": url_host_hint,
            },
            "worker_state": {
                "status": worker.status if worker else None,
                "lock_holder": worker.lock_holder if worker else None,
                "lock_acquired_at": worker.lock_acquired_at.isoformat() if worker and worker.lock_acquired_at else None,
            },
            "last_finished_cycle": None
            if last_cycle is None
            else {
                "run_id": last_cycle.run_id,
                "started_at": last_cycle.started_at.isoformat(),
                "finished_at": last_cycle.finished_at.isoformat() if last_cycle.finished_at else None,
                "cycle_status": last_cycle.cycle_status,
                "selected": last_cycle.selected_request_count,
                "inserted": last_cycle.inserted_snapshot_count,
                "missing": last_cycle.missing_count,
                "fetch_failed": last_cycle.fetch_failed_count,
            },
            "unfinished_cycle": None
            if running_cycle is None
            else {
                "run_id": running_cycle.run_id,
                "started_at": running_cycle.started_at.isoformat(),
            },
            "yxodh": {
                "last_missing_at_utc": last_missing_at.isoformat() if last_missing_at else None,
                "retry_interval_seconds": retry_interval_s,
                "retry_at_utc": datetime.fromtimestamp(retry_at, tz=timezone.utc).isoformat()
                if retry_at
                else None,
                "cooldown_active_now": bool(
                    last_missing_at
                    and (ensure_utc(utc_now()) - last_missing_at).total_seconds() < retry_interval_s
                ),
                "recent_outcomes": [
                    {
                        "run_id": r.monitoring_run_id,
                        "checkpoint": r.checkpoint_age_hours,
                        "outcome": r.outcome,
                        "attempted_at": r.attempted_at.isoformat(),
                    }
                    for r in recent_outcomes
                ],
            },
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    finally:
        session.close()


if __name__ == "__main__":
    main()
