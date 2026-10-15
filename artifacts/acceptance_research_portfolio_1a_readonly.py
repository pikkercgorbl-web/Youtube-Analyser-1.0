"""Read-only acceptance: live PG portfolio totals (Fix 1A)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.services.research_portfolio_report import build_research_portfolio_report
from app.services.saved_topic_validation import build_validation_report

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
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        legacy = build_validation_report(session, period_start=None, period_end=None)
        portfolio = build_research_portfolio_report(
            session,
            period_start=None,
            period_end=None,
            legacy_topics_saved_in_period=int(legacy["topics_saved_in_period"]),
        )
    out = {
        "legacy_topics_saved_in_period": legacy["topics_saved_in_period"],
        "portfolio_saved_in_period": portfolio["saved_in_period"],
        "combined_total": portfolio["saved_in_period"]["combined_total"],
        "portfolio_hints": portfolio["portfolio_hints"],
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
