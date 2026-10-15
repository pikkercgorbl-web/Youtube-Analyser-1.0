"""One-shot delayed outcome capture cycle (Stage 1.20E.2)."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one delayed outcome capture cycle.")
    parser.add_argument("--dry-run", action="store_true", help="Plan only; no fetch/persist")
    parser.add_argument("--max-videos", type=int, default=100)
    parser.add_argument("--json", action="store_true", help="Emit a single JSON document on stdout")
    return parser.parse_args()


def _prepare_json_cli_environment() -> None:
    """Process-local: keep stdout clean for machine-readable output (PowerShell 5.1 / UTF-8)."""
    os.environ["RADAR_SQL_ECHO"] = "false"
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from app.utils.worker_stdio import configure_worker_stdio_utf8

    configure_worker_stdio_utf8()

    for logger_name in (
        "sqlalchemy.engine",
        "sqlalchemy.engine.Engine",
        "sqlalchemy.pool",
        "sqlalchemy.orm",
    ):
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.WARNING)
        for handler in list(logger.handlers):
            if isinstance(handler, logging.StreamHandler) and handler.stream is sys.stdout:
                handler.stream = sys.stderr


def _emit_json(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, default=str))
    sys.stdout.write("\n")
    sys.stdout.flush()


def _emit_human(payload: dict) -> None:
    print(json.dumps(payload, indent=2, default=str))


def main() -> int:
    args = _parse_args()
    if args.json:
        _prepare_json_cli_environment()

    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    try:
        from app.api.deps import get_youtube_client
        from app.models.db import SessionLocal
        from app.services.delayed_outcome_capture_config import (
            OutcomeCaptureBudgetPolicy,
            outcome_capture_budget_from_env,
        )
        from app.services.delayed_outcome_capture_cycle import run_delayed_outcome_capture_cycle

        session = SessionLocal()
        try:
            env_budget = outcome_capture_budget_from_env()
            budget = OutcomeCaptureBudgetPolicy(
                max_videos_per_cycle=max(1, args.max_videos),
                batch_size=env_budget.batch_size,
                di_winner_priority_enabled=env_budget.di_winner_priority_enabled,
                priority_max_slots=env_budget.priority_max_slots,
                background_min_slots=env_budget.background_min_slots,
            )
            summary = run_delayed_outcome_capture_cycle(
                session,
                youtube_client=None if args.dry_run else get_youtube_client(),
                dry_run=args.dry_run,
                budget=budget,
            )
            payload = asdict(summary)
            if args.json:
                _emit_json(payload)
            else:
                _emit_human(payload)
            return 0
        finally:
            session.close()
    except Exception as exc:
        print(f"outcome capture cycle failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
