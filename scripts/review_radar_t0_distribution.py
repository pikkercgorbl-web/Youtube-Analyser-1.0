"""Offline T0 distribution review CLI (Stage 1.9B)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.radar_t0_distribution_review import (
    review_t0_cohort_from_manifest,
    write_distribution_review,
)

ARTIFACTS_DIR = ROOT / "artifacts"
DEFAULT_MANIFEST = ARTIFACTS_DIR / "cohort_T0_20260911_173903_manifest.json"
DEFAULT_REVIEW_ID = "20260911"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Offline distribution review of an existing T0 cohort manifest (no network/DB).",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help=f"Path to cohort_T0 manifest (default: {DEFAULT_MANIFEST})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ARTIFACTS_DIR,
        help="Directory for review JSON/MD outputs.",
    )
    parser.add_argument(
        "--review-id",
        default=DEFAULT_REVIEW_ID,
        help="Suffix for radar_t0_distribution_review_<id>.{json,md}",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.manifest.is_file():
        raise SystemExit(f"Manifest not found: {args.manifest}")

    review = review_t0_cohort_from_manifest(args.manifest)
    json_path, md_path = write_distribution_review(
        review,
        output_dir=args.output_dir,
        review_id=args.review_id,
    )

    print(
        f"[RADAR_T0_DISTRIBUTION_REVIEW] {json.dumps({'json': str(json_path), 'md': str(md_path), 'regular_records': review['overview']['regular_records']}, ensure_ascii=False)}",
        flush=True,
    )
    print(f"JSON report: {json_path}", flush=True)
    print(f"MD report: {md_path}", flush=True)
    print(f"NO_NETWORK_REQUESTS: {review['verification']['NO_NETWORK_REQUESTS']}", flush=True)
    print(f"NO_DB_WRITES: {review['verification']['NO_DB_WRITES']}", flush=True)


if __name__ == "__main__":
    main()
