"""Analyze an exported RadarCandidate JSONL dataset (Stage 1.6)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.radar_candidate_analysis import (
    analyze_candidate_dataset,
    load_candidate_records,
    write_analysis_outputs,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze a Stage 1.5 RadarCandidate JSONL dataset.",
    )
    parser.add_argument(
        "jsonl_path",
        type=Path,
        help="Path to radar_candidates_*.jsonl",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "artifacts",
        help="Directory for analysis JSON/MD outputs.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    jsonl_path = args.jsonl_path.resolve()
    if not jsonl_path.exists():
        raise SystemExit(f"Dataset not found: {jsonl_path}")

    records = load_candidate_records(jsonl_path)
    analysis = analyze_candidate_dataset(records)
    json_path, md_path = write_analysis_outputs(analysis, output_dir=args.output_dir)

    summary = analysis["dataset"]
    print("=== Radar Candidate Analysis ===")
    print(f"source: {jsonl_path}")
    print(f"keywords: {', '.join(summary['keywords'])}")
    print(f"candidates: {summary['candidate_count']}")
    print(f"passed: {summary['passed']}")
    print(f"rejected: {summary['rejected']}")
    print(f"parse_errors: {summary['parse_errors']}")
    print(f"json: {json_path}")
    print(f"markdown: {md_path}")


if __name__ == "__main__":
    main()
