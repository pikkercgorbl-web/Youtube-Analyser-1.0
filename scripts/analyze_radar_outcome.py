"""Offline T0 → T67 outcome analysis CLI (Stage 1.9D)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.radar_outcome_analysis import run_outcome_analysis, write_outcome_reports

ARTIFACTS_DIR = ROOT / "artifacts"
DEFAULT_SNAPSHOT = ARTIFACTS_DIR / "cohort_T72_20260914_124311_snapshot.jsonl"
DEFAULT_META = ARTIFACTS_DIR / "cohort_T72_20260914_124311_meta.json"
DEFAULT_MANIFEST = ARTIFACTS_DIR / "cohort_T0_20260911_173903_manifest.json"
DEFAULT_REVIEW_ID = "20260914_124311"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline outcome analysis for T0 → T67 snapshot.")
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=ARTIFACTS_DIR)
    parser.add_argument("--review-id", default=DEFAULT_REVIEW_ID)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for path in (args.snapshot, args.meta):
        if not path.is_file():
            raise SystemExit(f"Missing input file: {path}")

    report = run_outcome_analysis(
        snapshot_path=args.snapshot,
        snapshot_meta_path=args.meta,
        t0_manifest_path=args.manifest if args.manifest.is_file() else None,
    )
    json_path, md_path, joined_path = write_outcome_reports(
        report,
        output_dir=args.output_dir,
        review_id=args.review_id,
    )

    print(
        f"[RADAR_OUTCOME_ANALYSIS] {json.dumps({'joined': report['verification']['joined_rows'], 'json': str(json_path), 'md': str(md_path), 'joined_jsonl': str(joined_path) if joined_path else None}, ensure_ascii=False)}",
        flush=True,
    )


if __name__ == "__main__":
    main()
