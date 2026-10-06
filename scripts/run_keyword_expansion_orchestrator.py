"""Safe keyword expansion orchestrator CLI (Stage 1.20C)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models.db import SessionLocal
from app.services.keyword_expansion_orchestrator import (
    KeywordExpansionOrchestratorConfig,
    run_keyword_expansion_orchestrated_batch,
    run_keyword_expansion_orchestrated,
)
import asyncio


def main() -> int:
    parser = argparse.ArgumentParser(description="Run safe keyword expansion orchestration.")
    parser.add_argument("--seed-id", type=int, help="Single seed keyword id")
    parser.add_argument("--seed-ids", type=str, help="Comma-separated seed keyword ids")
    parser.add_argument("--max-seeds", type=int, default=10)
    parser.add_argument("--max-new", type=int, default=50, help="Global max accepted keywords per run")
    parser.add_argument("--include-weak", action="store_true", help="Allow weak lifecycle seeds")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = KeywordExpansionOrchestratorConfig(
        max_seeds_per_batch=max(1, args.max_seeds),
        max_new_keywords_per_expansion_run=max(1, args.max_new),
        expand_weak=args.include_weak,
    )

    session = SessionLocal()
    try:
        if args.seed_ids:
            ids = [int(part.strip()) for part in args.seed_ids.split(",") if part.strip()]
            summary = asyncio.run(
                run_keyword_expansion_orchestrated_batch(session, ids, config=config, dry_run=args.dry_run),
            )
        elif args.seed_id is not None:
            summary = asyncio.run(
                run_keyword_expansion_orchestrated(session, args.seed_id, config=config, dry_run=args.dry_run),
            )
        else:
            print("Provide --seed-id or --seed-ids", file=sys.stderr)
            return 2

        if not args.dry_run:
            session.commit()
        else:
            session.rollback()

        print(
            json.dumps(
                {
                    "run_id": summary.discovery_run_id,
                    "cycle_status": summary.cycle_status,
                    "seed_keyword_count": summary.seed_keyword_count,
                    "raw_candidate_count": summary.raw_candidate_count,
                    "created_keyword_count": summary.created_keyword_count,
                    "existing_keyword_count": summary.existing_keyword_count,
                    "deferred_count": summary.deferred_count,
                    "rejected_count": summary.rejected_count,
                    "runtime_seconds": summary.runtime_seconds,
                    "errors": list(summary.errors),
                },
                indent=2,
            ),
        )
        return 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
