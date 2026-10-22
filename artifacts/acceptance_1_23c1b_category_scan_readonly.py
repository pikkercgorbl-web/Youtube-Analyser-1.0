"""Scan all DI report dates for outcome coverage categories (read-only)."""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.services.daily_intelligence_outcome_followup import get_report_outcome_coverage


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
    dates = [
        row[0]
        for row in s.execute(
            text(
                "SELECT DISTINCT report_date::text FROM daily_intelligence_report_winner_findings ORDER BY 1",
            ),
        ).fetchall()
    ]
    by_date = {}
    first: dict[str, dict] = {}
    for rd in dates:
        cov = get_report_outcome_coverage(s, date.fromisoformat(rd))
        if not cov:
            continue
        by_date[rd] = cov.get("coverage_by_category") or {}
        for item in cov["items"]:
            cat = item["coverage_category"]
            if cat not in first:
                first[cat] = {
                    "report_date": rd,
                    "video_id": item["video_id"],
                    "outcome_window_phase": item.get("outcome_window_phase"),
                }
    print(json.dumps({"counts_by_date": by_date, "first_example_per_category": first}, indent=2))
    s.close()


if __name__ == "__main__":
    main()
