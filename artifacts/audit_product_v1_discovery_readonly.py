"""Product audit v1 — read-only PG diagnostics (youtube_radar_restore_check)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text

EXPECTED = "youtube_radar_restore_check"


def _url() -> str:
    u = os.environ.get("DATABASE_URL", "").strip()
    if not u:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL="):
                u = line.split("=", 1)[1].strip().strip('"').strip("'")
    if EXPECTED not in (u or ""):
        raise SystemExit("Refusing: not restore_check DB")
    return u


def main() -> None:
    engine = create_engine(_url(), connect_args={"options": "-c default_transaction_read_only=on"})
    with engine.connect() as c:
        c.execute(text("SET TRANSACTION READ ONLY"))

        def scalar(sql: str):
            return c.execute(text(sql)).scalar()

        def rows(sql: str):
            return [dict(r._mapping) for r in c.execute(text(sql)).fetchall()]

        report = {
            "target_keywords_by_lifecycle": rows(
                "SELECT lifecycle_status, COUNT(*)::int AS n FROM target_keywords GROUP BY 1 ORDER BY 1",
            ),
            "non_archived_total": scalar(
                "SELECT COUNT(*) FROM target_keywords WHERE lifecycle_status != 'archived'",
            ),
            "due_now_count": scalar(
                """
                SELECT COUNT(*) FROM target_keywords
                WHERE lifecycle_status != 'archived'
                  AND (next_scan_at IS NULL OR next_scan_at <= NOW())
                """,
            ),
            "null_next_scan_non_archived": scalar(
                """
                SELECT COUNT(*) FROM target_keywords
                WHERE lifecycle_status != 'archived' AND next_scan_at IS NULL
                """,
            ),
            "saved_counts": {
                "saved_videos": scalar("SELECT COUNT(*) FROM saved_videos"),
                "saved_families": scalar("SELECT COUNT(*) FROM saved_families"),
                "saved_topics": scalar("SELECT COUNT(*) FROM saved_topics"),
            },
        }
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
