"""Pilot: validation T0 scan + channel baseline capture (Stage 1.10A)."""

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
from app.services.explosive_channels_radar_worker import ExplosiveChannelsRadarWorker
from app.services.target_keywords_service import WORKER_STATUS_IDLE, TargetKeywordsService
from app.services.radar_channel_baseline import (
    ChannelBaselineConfig,
    build_pilot_quality_report,
    collect_channel_baselines_for_candidates,
)
from app.services.radar_validation_scan import run_validation_analysis_scan
from app.services.radar_validation_t0_dataset import (
    T0_SCHEMA_VERSION_WITH_BASELINE,
    serialize_t0_candidate_with_baseline,
)

ARTIFACTS_DIR = ROOT / "artifacts"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Channel baseline T0 pilot (single keyword).")
    parser.add_argument("--keyword", default="gaming")
    parser.add_argument("--output-dir", type=Path, default=ARTIFACTS_DIR)
    parser.add_argument(
        "--max-channel-requests",
        type=int,
        default=None,
        help="Optional cap on unique channel baseline fetches.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    if not settings.youtube_api_keys:
        raise SystemExit("YouTube API keys required for enrichment + baseline metadata.")

    youtube_client = get_youtube_client()
    worker = ExplosiveChannelsRadarWorker()
    run_started = datetime.now(timezone.utc)

    db = SessionLocal()
    try:
        if TargetKeywordsService().is_worker_stopped(db):
            TargetKeywordsService().set_worker_status(db, WORKER_STATUS_IDLE)
    finally:
        db.close()

    radar_module.is_radar_running = True
    try:
        scan_result, enrichment_meta = await run_validation_analysis_scan(
            worker,
            args.keyword,
            youtube_client=youtube_client,
        )
    finally:
        radar_module.is_radar_running = False

    config = ChannelBaselineConfig(
        max_channel_requests=args.max_channel_requests,
    )
    baseline_stats = await collect_channel_baselines_for_candidates(
        scan_result.candidates,
        youtube_client,
        config=config,
    )

    stamp = run_started.strftime("%Y%m%d_%H%M%S")
    safe_kw = args.keyword.strip().lower().replace(" ", "_")
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    jsonl_path = output_dir / f"cohort_T0_{stamp}_{safe_kw}_channel_baseline_pilot.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for candidate in scan_result.candidates:
            handle.write(json.dumps(serialize_t0_candidate_with_baseline(candidate), ensure_ascii=False))
            handle.write("\n")

    report = build_pilot_quality_report(
        keyword=args.keyword,
        candidates=scan_result.candidates,
        stats=baseline_stats,
    )
    report["schema_version"] = T0_SCHEMA_VERSION_WITH_BASELINE
    report["enrichment_missing_video_count"] = enrichment_meta.get("missing_video_count", 0)
    report["jsonl_path"] = str(jsonl_path)
    report["request_cost_note"] = (
        f"~{baseline_stats.channel_baseline_requests} InnerTube channel browse + "
        f"batched videos.list per channel (cached per channel_id within run)."
    )

    report_path = output_dir / f"radar_channel_baseline_pilot_{stamp}_{safe_kw}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[RADAR_CHANNEL_BASELINE_PILOT] {json.dumps(report, ensure_ascii=False)}", flush=True)
    print(f"jsonl: {jsonl_path}", flush=True)
    print(f"report: {report_path}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
