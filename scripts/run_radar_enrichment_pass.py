#!/usr/bin/env python3
"""One-shot Radar enrichment pass (Stage 2.5)."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.migrations import run_startup_migrations
from app.models.db import SessionLocal, engine
from app.services.radar_api_budget import enrichment_daily_budget_summary
from app.services.radar_enrichment_orchestrator import run_radar_enrichment_pass
from app.services.radar_enrichment_selection import RadarEnrichmentPassContext


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description="Run Radar subscriber + format enrichment pass.")
    parser.add_argument("--dry-run", action="store_true", help="Plan only; no API or DB writes.")
    parser.add_argument("--pass-sequence", type=int, default=1)
    args = parser.parse_args(argv)

    run_startup_migrations(engine)
    engine.echo = False
    session = SessionLocal()
    try:
        if args.dry_run:
            report = run_radar_enrichment_pass(
                session,
                _DryRunClient(),
                context=RadarEnrichmentPassContext(pass_sequence=args.pass_sequence),
                dry_run=True,
            )
            session.rollback()
        else:
            from app.api.deps import get_youtube_client

            report = run_radar_enrichment_pass(
                session,
                get_youtube_client(),
                context=RadarEnrichmentPassContext(pass_sequence=args.pass_sequence),
                dry_run=False,
            )
            session.commit()
        payload: dict = {"pass_report": asdict(report)}
        if args.dry_run:
            payload["budget_status"] = enrichment_daily_budget_summary(session)
        print(json.dumps(payload if args.dry_run else asdict(report), indent=2, default=str))
        return 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class _DryRunClient:
    def get_channels(self, channel_ids: list[str]):
        return {}

    def get_videos(self, video_ids: list[str]):
        return []


if __name__ == "__main__":
    raise SystemExit(main())
