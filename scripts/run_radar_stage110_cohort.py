"""Independent Stage 1.10C T0 cohort: discovery, sampling, channel baseline."""

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
from app.services.radar_stage110_cohort import (
    STAGE110_KEYWORDS,
    apply_baseline_to_selected,
    build_eligible_pool,
    build_quality_report,
    build_stage110_manifest,
    compute_overlap,
    merge_candidates_by_video_id,
    sample_stage110_design_a,
    serialize_stage110_broad_row,
    serialize_stage110_sample_row,
    write_jsonl,
)
from app.services.radar_validation_format import VALIDATION_CONTENT_FILTERS
from app.services.radar_validation_scan import run_validation_analysis_scan
from app.services.target_keywords_service import WORKER_STATUS_IDLE, TargetKeywordsService

ARTIFACTS_DIR = ROOT / "artifacts"
DEFAULT_OLD_MANIFEST = ARTIFACTS_DIR / "cohort_T0_20260911_173903_manifest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage 1.10C independent T0 + baseline sample.")
    parser.add_argument("--output-dir", type=Path, default=ARTIFACTS_DIR)
    parser.add_argument("--old-manifest", type=Path, default=DEFAULT_OLD_MANIFEST)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    if not settings.youtube_api_keys:
        raise SystemExit("YouTube API keys required for enrichment and channel baseline.")

    cohort_timestamp = datetime.now(timezone.utc)
    stamp = cohort_timestamp.strftime("%Y%m%d_%H%M%S")
    broad_path = args.output_dir / f"cohort_T0_stage110_{stamp}_broad.jsonl"
    sample_path = args.output_dir / f"cohort_T0_stage110_{stamp}_sample.jsonl"
    manifest_path = args.output_dir / f"cohort_T0_stage110_{stamp}_manifest.json"

    db = SessionLocal()
    try:
        if TargetKeywordsService().is_worker_stopped(db):
            TargetKeywordsService().set_worker_status(db, WORKER_STATUS_IDLE)
    finally:
        db.close()

    youtube_client = get_youtube_client()
    worker = ExplosiveChannelsRadarWorker()
    all_candidates: list = []
    discovery_started = datetime.now(timezone.utc)

    print(
        f"Validation filters: shorts={VALIDATION_CONTENT_FILTERS.exclude_shorts}, "
        f"streams={VALIDATION_CONTENT_FILTERS.exclude_streams}",
        flush=True,
    )

    radar_module.is_radar_running = True
    try:
        for index, keyword in enumerate(STAGE110_KEYWORDS, start=1):
            print(f"\n=== [{index}/{len(STAGE110_KEYWORDS)}] Stage 1.10C discovery: {keyword!r} ===", flush=True)
            scan_result, _meta = await run_validation_analysis_scan(
                worker,
                keyword,
                youtube_client=youtube_client,
            )
            all_candidates.extend(scan_result.candidates)
            print(f"accumulated candidates: {len(all_candidates)}", flush=True)
    finally:
        radar_module.is_radar_running = False

    discovery_duration = (datetime.now(timezone.utc) - discovery_started).total_seconds()

    broad_deduped = merge_candidates_by_video_id(all_candidates)
    write_jsonl(broad_path, [serialize_stage110_broad_row(candidate) for candidate in broad_deduped])

    eligible, pool_records = build_eligible_pool(all_candidates)
    selected_ids, sampling_audit, records_by_id = sample_stage110_design_a(pool_records)
    selected_candidates = [candidate for candidate in eligible if candidate.video_id in set(selected_ids)]
    selected_candidates.sort(key=lambda candidate: selected_ids.index(candidate.video_id))

    baseline_started = datetime.now(timezone.utc)
    baseline_stats = await apply_baseline_to_selected(selected_candidates, youtube_client)
    baseline_duration = (datetime.now(timezone.utc) - baseline_started).total_seconds()

    sample_rows = [
        serialize_stage110_sample_row(
            candidate,
            vph_stratum=records_by_id[candidate.video_id].vph_stratum
            if candidate.video_id in records_by_id
            else None,
            sampling_audit=sampling_audit,
        )
        for candidate in selected_candidates
    ]
    write_jsonl(sample_path, sample_rows)

    overlap = compute_overlap(eligible, old_manifest_path=args.old_manifest)
    quality = build_quality_report(
        all_candidates=all_candidates,
        eligible=eligible,
        selected=selected_candidates,
        sampling_audit=sampling_audit,
        baseline_stats=baseline_stats,
    )
    manifest = build_stage110_manifest(
        cohort_timestamp=cohort_timestamp,
        broad_path=broad_path,
        sample_path=sample_path,
        all_candidates=all_candidates,
        eligible=eligible,
        selected_ids=selected_ids,
        sampling_audit=sampling_audit,
        baseline_stats=baseline_stats,
        overlap=overlap,
        discovery_duration_seconds=discovery_duration,
        baseline_duration_seconds=baseline_duration,
        quality=quality,
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "manifest": str(manifest_path),
        "broad": str(broad_path),
        "sample": str(sample_path),
        "quality": quality,
        "overlap": overlap,
        "verification": manifest["verification"],
    }
    print(f"\n[STAGE110_COHORT] {json.dumps(summary, ensure_ascii=False)}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
