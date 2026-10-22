"""Measure get_latest_snapshots call count + runtime for 50-winner coverage (read-only PG)."""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.services import daily_intelligence_outcome_followup as followup_mod
from app.services.daily_intelligence_outcome_followup import get_report_outcome_coverage
from app.services.video_snapshot_storage import get_latest_snapshots_for_videos


def _url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL="):
                url = line.split("=", 1)[1].strip().strip('"').strip("'")
    if "youtube_radar_restore_check" not in (url or ""):
        raise SystemExit("wrong db")
    return url


def main() -> None:
    Session = sessionmaker(
        bind=create_engine(_url(), connect_args={"options": "-c default_transaction_read_only=on"}),
    )
    s = Session()
    s.execute(text("SET TRANSACTION READ ONLY"))
    rd = date(2026, 10, 10)
    ref = None
    from app.services.metrics import utc_now

    ref = utc_now()

    latest_calls = 0
    original = get_latest_snapshots_for_videos

    def spy(session_arg, video_ids, **kwargs):
        nonlocal latest_calls
        latest_calls += 1
        return original(session_arg, video_ids, **kwargs)

    t0 = time.perf_counter()
    with patch.object(followup_mod, "get_latest_snapshots_for_videos", side_effect=spy):
        cov = get_report_outcome_coverage(s, rd, reference_now=ref)
    ms = (time.perf_counter() - t0) * 1000
    s.close()
    print(
        json.dumps(
            {
                "report_date": rd.isoformat(),
                "winner_count": cov["winner_count"] if cov else None,
                "get_latest_snapshots_for_videos_calls": latest_calls,
                "coverage_ms": round(ms, 2),
            },
            indent=2,
        ),
    )


if __name__ == "__main__":
    main()
