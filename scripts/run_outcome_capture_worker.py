"""Run continuous delayed outcome capture worker (Stage 1.20E.2)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.utils.worker_stdio import configure_worker_stdio_utf8

configure_worker_stdio_utf8()

from app.api.deps import get_youtube_client
from app.models.db import SessionLocal
from app.services.delayed_outcome_capture_config import DEFAULT_OUTCOME_CAPTURE_INTERVAL_SECONDS
from app.services.outcome_capture_worker_runtime import (
    OutcomeCaptureWorkerConfig,
    run_outcome_capture_worker_loop,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run delayed outcome capture worker loop.")
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=DEFAULT_OUTCOME_CAPTURE_INTERVAL_SECONDS,
        help="Sleep between completed cycles (default: 3600).",
    )
    args = parser.parse_args()

    run_outcome_capture_worker_loop(
        SessionLocal,
        get_youtube_client(),
        config=OutcomeCaptureWorkerConfig(interval_seconds=args.interval_seconds),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
