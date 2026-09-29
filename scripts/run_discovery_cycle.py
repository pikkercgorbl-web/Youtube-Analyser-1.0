"""Run one automatic discovery cycle (Stage 1.15A)."""

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
from app.services.discovery_cycle import DiscoveryCycleConfig, run_discovery_cycle


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one discovery keyword cycle.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover and summarize only; no Video persistence or keyword last_checked updates.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5,
        help="Keyword batch size (default: 5).",
    )
    args = parser.parse_args()

    session = SessionLocal()
    try:
        config = DiscoveryCycleConfig(keyword_batch_size=max(1, args.batch_size))
        outcome = run_discovery_cycle(
            session,
            youtube_client=get_youtube_client(),
            config=config,
            dry_run=args.dry_run,
        )
        summary = outcome.summary
        print(
            json.dumps(
                {
                    "run_id": summary.run_id,
                    "cycle_status": summary.cycle_status,
                    "selected_keyword_count": summary.selected_keyword_count,
                    "persisted_video_count": summary.persisted_video_count,
                    "unique_video_count": summary.unique_video_count,
                    "qualification_passed_count": summary.qualification_passed_count,
                    "qualification_rejected_count": summary.qualification_rejected_count,
                },
                default=str,
                indent=2,
            ),
        )
        return 0 if summary.cycle_status in ("ok", "dry_run", "partial") else 1
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
