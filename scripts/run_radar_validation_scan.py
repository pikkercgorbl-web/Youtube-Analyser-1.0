"""Validation-only radar analysis scan with Shorts/LIVE excluded (Stage 1.8 Step 1)."""



from __future__ import annotations



import argparse

import asyncio

import json

import sys

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

from app.services.radar_validation_format import VALIDATION_CONTENT_FILTERS

from app.services.radar_validation_scan import run_validation_analysis_scan

from app.services.radar_validation_t0_dataset import persist_validation_t0_dataset

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





def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(

        description=(

            "Run validation analysis scan with exclude_shorts=True and "

            "exclude_streams=True (no explosive_channels registration)."

        ),

    )

    parser.add_argument("keyword", help="Keyword to scan.")

    return parser.parse_args()





async def main() -> None:

    args = parse_args()

    keyword = args.keyword.strip()

    if not keyword:

        raise SystemExit("Keyword must not be empty.")



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

        print("YouTube API keys not configured — skipping post-discovery enrichment.", flush=True)



    radar_module.is_radar_running = True

    try:

        scan_result, enrichment_meta = await run_validation_analysis_scan(

            worker,

            keyword,

            youtube_client=youtube_client,

        )

    finally:

        radar_module.is_radar_running = False



    channels_after = count_explosive_channels()



    dataset_path, enrichment_summary, dataset_summary = persist_validation_t0_dataset(

        scan_result.candidates,

        keyword=scan_result.keyword,

        output_dir=ARTIFACTS_DIR,

        missing_video_count=enrichment_meta.get("missing_video_count", 0),

    )



    print(

        f"[RADAR_T0_ENRICHMENT] {json.dumps(enrichment_summary, ensure_ascii=False)}",

        flush=True,

    )

    print(

        f"[RADAR_T0_DATASET] {json.dumps(dataset_summary, ensure_ascii=False)}",

        flush=True,

    )



    print("\n=== VALIDATION SCAN ===", flush=True)

    print(f"keyword: {scan_result.keyword}", flush=True)

    print(f"candidates: {dataset_summary['candidate_count']}", flush=True)

    print(f"passed: {dataset_summary['passed']}", flush=True)

    print(f"rejected: {dataset_summary['rejected']}", flush=True)

    print(f"parse_errors: {dataset_summary['parse_errors']}", flush=True)

    print(f"format_violations: {dataset_summary['format_violations']}", flush=True)

    print(f"cohort_T0: {dataset_path}", flush=True)

    print(

        f"explosive_channels before/after: {channels_before} / {channels_after}",

        flush=True,

    )





if __name__ == "__main__":

    asyncio.run(main())

