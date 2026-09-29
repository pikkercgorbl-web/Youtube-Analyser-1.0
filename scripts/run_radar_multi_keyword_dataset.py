"""Multi-keyword RadarCandidate dataset collection (Stage 1.7)."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.services.explosive_channels_radar_worker as radar_module
from app.models.db import SessionLocal
from app.models.orm import ExplosiveChannel
from app.services.explosive_channels_radar_worker import ExplosiveChannelsRadarWorker
from app.services.radar_multi_keyword_dataset import (
    DEFAULT_KEYWORDS,
    ExperimentSettings,
    aggregate_collection_summary,
    collect_keywords_sequential,
    write_collection_summary,
)
from app.services.target_keywords_service import (
    WORKER_STATUS_IDLE,
    TargetKeywordsService,
)
from sqlalchemy import func, select

SOURCE = "run_radar_multi_keyword_dataset.py"


def parse_keywords(raw: str | None) -> list[str]:
    if not raw:
        return list(DEFAULT_KEYWORDS)
    return [keyword.strip() for keyword in raw.split(",") if keyword.strip()]


def count_explosive_channels() -> int:
    db = SessionLocal()
    try:
        return db.scalar(select(func.count()).select_from(ExplosiveChannel)) or 0
    finally:
        db.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Collect per-keyword RadarCandidate JSONL datasets via analysis/dry-run scan "
            "(no explosive_channels registration)."
        ),
    )
    parser.add_argument(
        "--keywords",
        help="Comma-separated keywords (default: 10 Stage 1.7 keywords).",
    )
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "artifacts"),
        help="Directory for JSONL/meta/summary outputs (default: artifacts/).",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    keywords = parse_keywords(args.keywords)
    output_dir = Path(args.output_dir)
    run_started = datetime.now(timezone.utc)

    channels_before = count_explosive_channels()
    worker = ExplosiveChannelsRadarWorker()

    db = SessionLocal()
    try:
        if TargetKeywordsService().is_worker_stopped(db):
            TargetKeywordsService().set_worker_status(db, WORKER_STATUS_IDLE)
        from app.services.explosive_channels_service import ExplosiveChannelsService

        service = ExplosiveChannelsService()
        thresholds = service.get_thresholds(db)
        upload_period = service.get_upload_period(db)
    finally:
        db.close()

    settings = ExperimentSettings(
        min_views=thresholds.min_views,
        min_viral_coeff=thresholds.min_viral_coeff,
        upload_period=upload_period,
    )

    radar_module.is_radar_running = True
    try:

        async def scan_keyword(keyword: str):
            return await worker.run_analysis_scan(keyword)

        def on_start(keyword: str, index: int, total: int) -> None:
            print(f"\n=== [{index}/{total}] Analysis scan: {keyword!r} ===", flush=True)

        def on_done(result) -> None:
            if result.status == "success":
                print(
                    f"Collected {result.counts.get('total', 0)} candidates "
                    f"(passed={result.counts.get('passed', 0)}, "
                    f"rejected={result.counts.get('rejected', 0)}, "
                    f"parse_errors={result.counts.get('parse_errors', 0)}) "
                    f"pages={result.pages_scanned} duration={result.duration_seconds:.1f}s",
                    flush=True,
                )
                print(f"jsonl: {result.jsonl_path}", flush=True)
                print(f"meta: {result.meta_path}", flush=True)
            else:
                print(
                    f"FAILED {result.keyword!r}: {result.error_type} — {result.error_message} "
                    f"(duration={result.duration_seconds:.1f}s)",
                    flush=True,
                )

        results = await collect_keywords_sequential(
            keywords,
            scan_keyword=scan_keyword,
            output_dir=output_dir,
            settings=settings,
            source=SOURCE,
            on_keyword_start=on_start,
            on_keyword_done=on_done,
        )
    finally:
        radar_module.is_radar_running = False

    channels_after = count_explosive_channels()
    summary = aggregate_collection_summary(
        results,
        settings=settings,
        explosive_channels_before=channels_before,
        explosive_channels_after=channels_after,
        generated_at=run_started,
    )
    summary_json, summary_md = write_collection_summary(summary, output_dir, timestamp=run_started)

    print("\n=== MULTI-KEYWORD DATASET COLLECTION ===", flush=True)
    print(f"keywords_requested: {len(keywords)}", flush=True)
    print(f"keywords_successful: {summary['keywords_successful']}", flush=True)
    print(f"keywords_failed: {summary['keywords_failed']}", flush=True)
    print(f"settings_match_expected: {summary['settings_match_expected']}", flush=True)
    print(f"summary_json: {summary_json}", flush=True)
    print(f"summary_md: {summary_md}", flush=True)
    print(
        f"explosive_channels before/after: {channels_before} / {channels_after} "
        f"(production_db_registration_occurred: {summary['production_db_registration_occurred']})",
        flush=True,
    )

    if summary["keywords_failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
