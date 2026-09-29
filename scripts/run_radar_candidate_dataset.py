"""Export a clean RadarCandidate dataset via analysis/dry-run scan (Stage 1.5)."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.services.explosive_channels_radar_worker as radar_module
from app.models.db import SessionLocal
from app.models.orm import ExplosiveChannel
from app.services.explosive_channels_radar_worker import ExplosiveChannelsRadarWorker
from app.services.radar_candidate_dataset import (
    count_candidate_states,
    export_candidate_dataset,
)
from app.services.target_keywords_service import (
    WORKER_STATUS_IDLE,
    TargetKeywordsService,
)
from sqlalchemy import func, select


def load_keywords(args: argparse.Namespace) -> list[str]:
    if args.file:
        path = Path(args.file)
        return [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    if args.keywords:
        return [keyword.strip() for keyword in args.keywords if keyword.strip()]
    raise SystemExit("Provide keywords as arguments or via --file.")


def count_explosive_channels() -> int:
    db = SessionLocal()
    try:
        return db.scalar(select(func.count()).select_from(ExplosiveChannel)) or 0
    finally:
        db.close()


async def collect_dataset(keywords: list[str]) -> list:
    worker = ExplosiveChannelsRadarWorker()
    db = SessionLocal()
    all_candidates = []
    try:
        if TargetKeywordsService().is_worker_stopped(db):
            TargetKeywordsService().set_worker_status(db, WORKER_STATUS_IDLE)

        radar_module.is_radar_running = True
        try:
            for index, keyword in enumerate(keywords, start=1):
                print(f"\n=== [{index}/{len(keywords)}] Analysis scan: {keyword!r} ===", flush=True)
                scan_result = await worker.run_analysis_scan(keyword)
                candidates = scan_result.candidates
                all_candidates.extend(candidates)
                counts = count_candidate_states(candidates)
                print(
                    f"Collected {len(candidates)} candidates "
                    f"(passed={counts['passed']}, rejected={counts['rejected']}, "
                    f"parse_errors={counts['parse_errors']})",
                    flush=True,
                )
        finally:
            radar_module.is_radar_running = False
    finally:
        db.close()
    return all_candidates


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run analysis scan and export RadarCandidate JSONL dataset.",
    )
    parser.add_argument("keywords", nargs="*", help="Keyword(s) to scan.")
    parser.add_argument("--file", "-f", help="Keyword list file (one per line).")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    keywords = load_keywords(args)

    channels_before = count_explosive_channels()
    candidates = await collect_dataset(keywords)
    channels_after = count_explosive_channels()

    jsonl_path, meta_path = export_candidate_dataset(
        candidates,
        keywords=keywords,
        output_dir=ROOT / "artifacts",
        source="run_radar_candidate_dataset.py",
    )

    totals = count_candidate_states(candidates)
    print("\n=== DATASET EXPORT ===", flush=True)
    print(f"keywords: {keywords}", flush=True)
    print(f"total_candidates: {len(candidates)}", flush=True)
    print(f"passed: {totals['passed']}", flush=True)
    print(f"rejected: {totals['rejected']}", flush=True)
    print(f"parse_errors: {totals['parse_errors']}", flush=True)
    print(f"jsonl: {jsonl_path}", flush=True)
    print(f"meta: {meta_path}", flush=True)
    print(
        f"explosive_channels before/after: {channels_before} / {channels_after} "
        f"(DB writes: {'YES' if channels_after > channels_before else 'NO'})",
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
