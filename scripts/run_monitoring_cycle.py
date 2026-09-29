"""Run one automatic monitoring cycle (Stage 1.13C)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.deps import get_youtube_client
from app.models.db import SessionLocal
from app.services.monitoring_cycle import run_monitoring_cycle


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one monitoring revisit cycle.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan and budget only; no YouTube fetch or snapshot persistence.",
    )
    args = parser.parse_args()

    session = SessionLocal()
    try:
        client = None if args.dry_run else get_youtube_client()
        summary = run_monitoring_cycle(
            session,
            youtube_client=client,
            dry_run=args.dry_run,
        )
        if not args.dry_run:
            session.commit()
        else:
            session.rollback()
        print(json.dumps(summary.__dict__, default=str, indent=2))
        return 0 if summary.cycle_status in ("ok", "dry_run", "partial") else 1
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
