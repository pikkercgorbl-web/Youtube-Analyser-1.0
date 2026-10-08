"""Run continuous automatic discovery worker (Stage 1.15B)."""



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

from app.services.discovery_worker_runtime import (

    DEFAULT_DISCOVERY_ERROR_BACKOFF_SECONDS,

    DEFAULT_DISCOVERY_WORKER_INTERVAL_SECONDS,

    DiscoveryWorkerConfig,

    run_discovery_worker,

)





def main() -> int:

    parser = argparse.ArgumentParser(description="Run discovery worker loop.")

    parser.add_argument(

        "--interval-seconds",

        type=int,

        default=DEFAULT_DISCOVERY_WORKER_INTERVAL_SECONDS,

        help="Sleep between completed cycles (default: 300).",

    )

    parser.add_argument(

        "--error-backoff-seconds",

        type=int,

        default=DEFAULT_DISCOVERY_ERROR_BACKOFF_SECONDS,

        help="Sleep after fatal cycle error (default: 300).",

    )

    parser.add_argument(

        "--batch-size",

        type=int,

        default=5,

        help="Keyword batch size per cycle (default: 5).",

    )

    args = parser.parse_args()



    config = DiscoveryWorkerConfig(

        interval_seconds=args.interval_seconds,

        error_backoff_seconds=args.error_backoff_seconds,

        keyword_batch_size=max(1, args.batch_size),

    )

    run_discovery_worker(

        SessionLocal,

        get_youtube_client(),

        config=config,

    )

    return 0





if __name__ == "__main__":

    raise SystemExit(main())

