"""One-shot delayed outcome capture cycle (Stage 1.20E.2)."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.deps import get_youtube_client
from app.models.db import SessionLocal
from app.services.delayed_outcome_capture_config import OutcomeCaptureBudgetPolicy
from app.services.delayed_outcome_capture_cycle import run_delayed_outcome_capture_cycle


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one delayed outcome capture cycle.")
    parser.add_argument("--dry-run", action="store_true", help="Plan only; no fetch/persist")
    parser.add_argument("--max-videos", type=int, default=100)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        summary = run_delayed_outcome_capture_cycle(
            session,
            youtube_client=None if args.dry_run else get_youtube_client(),
            dry_run=args.dry_run,
            budget=OutcomeCaptureBudgetPolicy(max_videos_per_cycle=max(1, args.max_videos)),
        )
        payload = asdict(summary)
        if args.json:
            print(json.dumps(payload, indent=2, default=str))
        else:
            print(json.dumps(payload, indent=2, default=str))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
