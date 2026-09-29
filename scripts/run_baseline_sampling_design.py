"""Offline baseline sampling design report (Stage 1.10B)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.radar_baseline_sampling_design import (
    run_sampling_design_analysis,
    write_sampling_design_reports,
)

ARTIFACTS_DIR = ROOT / "artifacts"
DEFAULT_MANIFEST = ARTIFACTS_DIR / "cohort_T0_20260911_173903_manifest.json"
DEFAULT_JOINED = ARTIFACTS_DIR / "radar_outcome_joined_T0_T67_20260914_124311.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Baseline enrichment sampling design (offline).")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--joined", type=Path, default=DEFAULT_JOINED)
    parser.add_argument("--output-dir", type=Path, default=ARTIFACTS_DIR)
    parser.add_argument("--review-id", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.manifest.is_file():
        raise SystemExit(f"Manifest not found: {args.manifest}")

    review_id = args.review_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    joined = args.joined if args.joined.is_file() else None
    report = run_sampling_design_analysis(
        manifest_path=args.manifest,
        joined_path=joined,
    )
    json_path, md_path = write_sampling_design_reports(
        report,
        output_dir=args.output_dir,
        review_id=review_id,
    )
    print(
        f"[RADAR_BASELINE_SAMPLING_DESIGN] {json.dumps({'json': str(json_path), 'md': str(md_path)}, ensure_ascii=False)}",
        flush=True,
    )


if __name__ == "__main__":
    main()
