#!/usr/bin/env python3
"""Lock completed UTC daily intelligence reports (Stage 1.23A)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import load_dotenv


def main() -> int:
    load_dotenv(ROOT / ".env")
    from app.db.migrations import run_startup_migrations
    from app.models.db import SessionLocal, engine
    from app.services.daily_intelligence_capture import finalize_eligible_reports
    from app.services.metrics import utc_now

    run_startup_migrations(engine)
    session = SessionLocal()
    try:
        locked = finalize_eligible_reports(session, now=utc_now())
        session.commit()
        print(f"Finalized {len(locked)} UTC day(s): {[d.isoformat() for d in locked]}")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
