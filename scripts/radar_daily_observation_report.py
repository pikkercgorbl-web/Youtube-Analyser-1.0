#!/usr/bin/env python3
"""Read-only UTC-day Radar observation report (immutable originals + catch-up)."""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import load_dotenv

DEFAULT_OUT = ROOT / "artifacts" / "daily_observation"


def _parse_day(raw: str) -> date:
    return date.fromisoformat(raw)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate read-only Radar daily observation reports.")
    parser.add_argument(
        "--day",
        type=str,
        default=None,
        help="Single UTC day YYYY-MM-DD (must be complete unless --recalculate).",
    )
    parser.add_argument(
        "--catch-up",
        action="store_true",
        help="Process missing original reports for completed UTC days (see --max-days).",
    )
    parser.add_argument(
        "--fix-yesterday",
        action="store_true",
        help="Shorthand: ensure original for yesterday UTC (+ catch-up missing within --max-days).",
    )
    parser.add_argument(
        "--max-days",
        type=int,
        default=14,
        help="Catch-up lookback for completed UTC days (default 14, max 90).",
    )
    parser.add_argument(
        "--recalculate",
        action="store_true",
        help="Write a timestamped revision under revisions/ (does not replace original).",
    )
    parser.add_argument(
        "--index-only",
        action="store_true",
        help="Rebuild index_last_14_complete_utc_days.json from saved originals only.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Observation artifact root (default: {DEFAULT_OUT}).",
    )
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    import os

    os.environ.setdefault("DEBUG", "false")
    os.environ.setdefault("RADAR_SQL_ECHO", "false")

    from app.models.db import SessionLocal, engine
    from app.services.radar_daily_observation_report import (
        RadarDailyReportError,
        build_radar_daily_observation_report,
        utc_day_window,
    )
    from app.services.radar_daily_observation_storage import (
        complete_utc_days_for_catchup,
        migrate_legacy_flat_artifacts,
        missing_original_days,
        persist_daily_observation_artifacts,
        write_observation_index,
    )

    engine.echo = False
    output_dir: Path = args.output_dir
    migrate_legacy_flat_artifacts(output_dir)

    if args.index_only:
        index_path = write_observation_index(output_dir, complete_day_count=min(args.max_days, 14))
        print(f"Wrote {index_path}")
        return 0

    now = _utc_now()
    today = now.date()

    days_to_process: list[date] = []
    if args.day:
        days_to_process = [_parse_day(args.day)]
    elif args.catch_up:
        candidates = complete_utc_days_for_catchup(reference_now=now, max_days=args.max_days)
        days_to_process = missing_original_days(output_dir, candidates)
    elif args.fix_yesterday:
        days_to_process = [today - timedelta(days=1)]
    else:
        parser.error("Specify --day, --catch-up, --fix-yesterday, or --index-only")

    if not days_to_process:
        index_path = write_observation_index(output_dir, complete_day_count=14)
        print("No days to process (all originals present in range).")
        print(f"Wrote {index_path}")
        return 0

    exit_code = 0
    session = SessionLocal()
    try:
        for utc_day in days_to_process:
            window = utc_day_window(utc_day, reference_now=now)
            if not window.day_complete and not args.recalculate:
                print(f"Skip {utc_day}: UTC day not complete (use --recalculate after close).", file=sys.stderr)
                continue
            if args.recalculate and utc_day not in days_to_process[:1] and len(days_to_process) > 1:
                print("Note: --recalculate applies per run; use with single --day.", file=sys.stderr)

            try:
                report = build_radar_daily_observation_report(session, utc_day=utc_day, generated_at=now)
            except RadarDailyReportError as exc:
                print(f"ERROR {utc_day}: {exc}", file=sys.stderr)
                exit_code = 2
                continue

            outcome, json_path, md_path = persist_daily_observation_artifacts(
                report,
                output_dir=output_dir,
                as_revision=bool(args.recalculate),
            )
            print(f"{utc_day}: {outcome} -> {json_path}")
            if md_path:
                print(f"  {md_path}")
    finally:
        session.close()

    index_path = write_observation_index(output_dir, complete_day_count=14)
    print(f"Wrote {index_path}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
