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
from app.services.delayed_outcome_capture_config import (
    DEFAULT_OUTCOME_CAPTURE_INTERVAL_SECONDS,
    DEFAULT_OUTCOME_CAPTURE_MAX_VIDEOS_PER_CYCLE,
)
from app.services.outcome_capture_worker_runtime import (
    OutcomeCaptureWorkerConfig,
    run_outcome_capture_worker_loop,
)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Run delayed outcome capture worker loop.")
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=DEFAULT_OUTCOME_CAPTURE_INTERVAL_SECONDS,
        help="Sleep after each completed cycle (default: 3600).",
    )
    parser.add_argument(
        "--max-videos",
        type=_positive_int,
        default=None,
        help=(
            f"Max unique videos fetched per cycle (default: "
            f"{DEFAULT_OUTCOME_CAPTURE_MAX_VIDEOS_PER_CYCLE})."
        ),
    )
    args = parser.parse_args()

    run_outcome_capture_worker_loop(
        SessionLocal,
        get_youtube_client(),
        config=OutcomeCaptureWorkerConfig(
            interval_seconds=args.interval_seconds,
            max_videos_per_cycle=args.max_videos,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
