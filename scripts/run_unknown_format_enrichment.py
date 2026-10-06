"""Refine UNKNOWN Video.content_format via batched videos.list (Stage 2)."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models.db import SessionLocal, engine
from app.services.unknown_format_enrichment import apply_unknown_format_enrichment
from app.services.unknown_format_enrichment_config import unknown_format_enrichment_settings


def _local_restore_database_url() -> str | None:
    import os
    from pathlib import Path
    from urllib.parse import quote

    from migrate import load_dotenv

    root = Path(__file__).resolve().parents[1]
    env_path = root / ".env.docker"
    if not env_path.is_file():
        return None
    load_dotenv(env_path)
    user = os.environ.get("RADAR_LOCAL_DB_USER", "").strip()
    password = os.environ.get("RADAR_LOCAL_DB_PASSWORD", "").strip()
    if not user or not password:
        return None
    pw = quote(password, safe="")
    return f"postgresql://{user}:{pw}@127.0.0.1:5433/youtube_radar_restore_check"


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Enrich UNKNOWN video formats via YouTube Data API.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan batches only; no API calls and no DB writes.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Override UNKNOWN_FORMAT_ENRICHMENT_DAILY_VIDEO_LIMIT for this run.",
    )
    args = parser.parse_args(argv)

    local_url = _local_restore_database_url()
    if local_url:
        import os

        os.environ["DATABASE_URL"] = local_url

    limit = args.limit
    if limit is None:
        limit = unknown_format_enrichment_settings.unknown_format_enrichment_daily_video_limit

    print(f"unknown_format_enrichment_daily_video_limit={limit} dry_run={args.dry_run}")
    if args.dry_run:
        engine.echo = False
        session = SessionLocal()
        try:
            result = apply_unknown_format_enrichment(
                session,
                youtube_client=object(),  # unused in dry_run
                limit=limit,
                dry_run=True,
            )
            print(f"selected={result.selected} api_batches={result.api_batches}")
            if result.video_ids_planned:
                print(f"first_ids={list(result.video_ids_planned[:5])}")
        finally:
            session.close()
        return 0

    print("Live API enrichment requires explicit client wiring; use --dry-run in offline environments.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
