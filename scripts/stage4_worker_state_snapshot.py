#!/usr/bin/env python3
"""Read-only worker / cycle state for Stage 4 observation (restore-check only)."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import load_dotenv

EXPECTED_HOST = "127.0.0.1"
EXPECTED_PORT = 5433
EXPECTED_DB = "youtube_radar_restore_check"
ARTIFACT = ROOT / "artifacts" / "stage4_worker_state_snapshot.json"


def _assert_db_url() -> None:
    url = os.environ.get("DATABASE_URL", "")
    p = urlparse(url)
    if p.hostname not in (EXPECTED_HOST, "localhost") or p.port != EXPECTED_PORT:
        raise SystemExit(f"Refusing: DATABASE_URL host/port not {EXPECTED_HOST}:{EXPECTED_PORT}")
    if (p.path or "").lstrip("/") != EXPECTED_DB:
        raise SystemExit(f"Refusing: database not {EXPECTED_DB}")


def main() -> int:
    load_dotenv(ROOT / ".env")
    _assert_db_url()
    from app.models.db import SessionLocal, engine
    from app.models.orm import DiscoveryWorkerState, MonitoringWorkerState
    from app.services.radar_api_budget import enrichment_daily_budget_summary

    engine.echo = False
    session = SessionLocal()
    now = datetime.now(timezone.utc)
    try:
        disc = session.get(DiscoveryWorkerState, 1)
        mon = session.get(MonitoringWorkerState, 1)
        outcome = None
        try:
            from app.models.orm import OutcomeCaptureWorkerState

            outcome = session.get(OutcomeCaptureWorkerState, 1)
        except Exception:
            pass

        def _row(obj) -> dict | None:
            if obj is None:
                return None
            return {
                k: (v.isoformat() if hasattr(v, "isoformat") else v)
                for k, v in obj.__dict__.items()
                if not k.startswith("_")
            }

        report = {
            "captured_at_utc": now.isoformat(),
            "discovery_worker_state": _row(disc),
            "monitoring_worker_state": _row(mon),
            "outcome_worker_state": _row(outcome),
            "enrichment_budget_summary": enrichment_daily_budget_summary(session, now=now),
        }
        ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(json.dumps(report, indent=2, default=str))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
