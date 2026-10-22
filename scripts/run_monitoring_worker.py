"""Run continuous automatic monitoring worker (Stage 1.13C)."""

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
from app.services.monitoring_cycle import (
    DEFAULT_MONITORING_ERROR_BACKOFF_SECONDS,
    DEFAULT_MONITORING_WORKER_INTERVAL_SECONDS,
)
from app.services.monitoring_worker_runtime import (
    MonitoringWorkerConfig,
    run_monitoring_worker_loop,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run monitoring worker loop.")
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=DEFAULT_MONITORING_WORKER_INTERVAL_SECONDS,
        help="Sleep between completed cycles (default: 900).",
    )
    parser.add_argument(
        "--error-backoff-seconds",
        type=int,
        default=DEFAULT_MONITORING_ERROR_BACKOFF_SECONDS,
        help="Sleep after fatal cycle error (default: 300).",
    )
    args = parser.parse_args()

    config = MonitoringWorkerConfig(
        interval_seconds=args.interval_seconds,
        error_backoff_seconds=args.error_backoff_seconds,
    )
    run_monitoring_worker_loop(
        SessionLocal,
        get_youtube_client(),
        config=config,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
