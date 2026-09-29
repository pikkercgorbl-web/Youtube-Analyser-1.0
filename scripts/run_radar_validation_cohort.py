"""Fresh 10-keyword validation T0 cohort collection (Stage 1.9A)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.services.explosive_channels_radar_worker as radar_module
from app.api.deps import get_youtube_client
from app.core.config import settings
from app.models.db import SessionLocal
from app.models.orm import ExplosiveChannel
from app.services.explosive_channels_radar_worker import ExplosiveChannelsRadarWorker
from app.services.radar_validation_cohort import (
    VALIDATION_COHORT_KEYWORDS,
    build_cohort_manifest_with_aggregates,
    build_global_summary_payload,
    collect_validation_cohort,
    write_cohort_manifest,
)
from app.services.radar_validation_format import VALIDATION_CONTENT_FILTERS
from app.services.target_keywords_service import (
    WORKER_STATUS_IDLE,
    TargetKeywordsService,
)
from sqlalchemy import func, select

ARTIFACTS_DIR = ROOT / "artifacts"


def count_explosive_channels() -> int:
    db = SessionLocal()
    try:
        return db.scalar(select(func.count()).select_from(ExplosiveChannel)) or 0
    finally:
        db.close()


def parse_keywords(raw: str | None) -> list[str]:
    if not raw:
        return list(VALIDATION_COHORT_KEYWORDS)
    return [keyword.strip() for keyword in raw.split(",") if keyword.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Collect fresh validation T0 cohort datasets for multiple keywords "
            "(no explosive_channels registration)."
        ),
    )
    parser.add_argument(
        "--keywords",
        help="Comma-separated keywords (default: 10 Stage 1.9A keywords).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ARTIFACTS_DIR,
        help="Output directory for JSONL/meta/manifest (default: artifacts/).",
    )
    return parser.parse_args()


def print_per_keyword_table(summary: dict) -> None:
    header = (
        "keyword\tstatus\traw\tregular\tpassed\trejected\t"
        "format_excluded\tenrichment_ok\tenrichment_partial\tenrichment_failed\t"
        "VPH_available\tV/S_available"
    )
    print(header, flush=True)
    for row in summary["per_keyword_table"]:
        print(
            f"{row['keyword']}\t{row['status']}\t{row['raw']}\t{row['regular']}\t"
            f"{row['passed']}\t{row['rejected']}\t{row['format_excluded']}\t"
            f"{row['enrichment_ok']}\t{row['enrichment_partial']}\t{row['enrichment_failed']}\t"
            f"{row['VPH_available']}\t{row['V/S_available']}",
            flush=True,
        )


async def main() -> None:
    args = parse_args()
    keywords = parse_keywords(args.keywords)
    output_dir = args.output_dir
    cohort_timestamp = datetime.now(timezone.utc)
    run_started = cohort_timestamp

    channels_before = count_explosive_channels()
    worker = ExplosiveChannelsRadarWorker()

    db = SessionLocal()
    try:
        if TargetKeywordsService().is_worker_stopped(db):
            TargetKeywordsService().set_worker_status(db, WORKER_STATUS_IDLE)
    finally:
        db.close()

    print(
        "Validation format filters: "
        f"exclude_shorts={VALIDATION_CONTENT_FILTERS.exclude_shorts}, "
        f"exclude_streams={VALIDATION_CONTENT_FILTERS.exclude_streams}, "
        f"exclude_videos={VALIDATION_CONTENT_FILTERS.exclude_videos}",
        flush=True,
    )

    youtube_client = get_youtube_client() if settings.youtube_api_keys else None
    if youtube_client is None:
        print("YouTube API keys not configured — post-discovery enrichment will be skipped.", flush=True)

    radar_module.is_radar_running = True
    try:

        def on_start(keyword: str, index: int, total: int) -> None:
            print(f"\n=== [{index}/{total}] Validation T0 scan: {keyword!r} ===", flush=True)

        def on_done(result) -> None:
            if result.status == "FAILED":
                print(
                    f"FAILED {result.keyword!r}: {result.error_type} — {result.error_message} "
                    f"(duration={result.duration_seconds:.1f}s)",
                    flush=True,
                )
                return
            print(
                f"{result.status} {result.keyword!r}: raw={result.raw_candidates} "
                f"regular={result.regular_candidates} passed={result.passed} "
                f"rejected={result.rejected} excluded={result.excluded_after_enrichment} "
                f"duration={result.duration_seconds:.1f}s",
                flush=True,
            )
            print(f"jsonl: {result.jsonl_path}", flush=True)
            print(f"meta: {result.meta_path}", flush=True)

        results = await collect_validation_cohort(
            keywords,
            worker=worker,
            youtube_client=youtube_client,
            output_dir=output_dir,
            cohort_timestamp=cohort_timestamp,
            on_keyword_start=on_start,
            on_keyword_done=on_done,
        )
    finally:
        radar_module.is_radar_running = False

    channels_after = count_explosive_channels()
    total_duration = (datetime.now(timezone.utc) - run_started).total_seconds()

    manifest = build_cohort_manifest_with_aggregates(
        keywords=keywords,
        results=results,
        cohort_timestamp=cohort_timestamp,
        total_duration_seconds=total_duration,
        explosive_channels_before=channels_before,
        explosive_channels_after=channels_after,
    )
    manifest_path = write_cohort_manifest(
        manifest,
        output_dir=output_dir,
        cohort_timestamp=cohort_timestamp,
    )
    summary = build_global_summary_payload(manifest, manifest_path)

    print(f"\n[RADAR_T0_COHORT_SUMMARY] {json.dumps(summary, ensure_ascii=False)}", flush=True)
    print("\n=== PER-KEYWORD TABLE ===", flush=True)
    print_per_keyword_table(summary)

    print("\n=== VALIDATION T0 COHORT ===", flush=True)
    print(f"keywords_requested: {len(keywords)}", flush=True)
    print(f"keywords_successful: {manifest['keywords_successful']}", flush=True)
    print(f"keywords_partial: {manifest['keywords_partial']}", flush=True)
    print(f"keywords_failed: {manifest['keywords_failed']}", flush=True)
    print(f"manifest: {manifest_path}", flush=True)
    print(
        f"explosive_channels before/after: {channels_before} / {channels_after}",
        flush=True,
    )

    if manifest["keywords_failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
