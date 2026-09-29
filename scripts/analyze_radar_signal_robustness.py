"""Offline signal robustness CLI (Stage 1.9E)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.radar_signal_robustness import run_signal_robustness_analysis, write_robustness_reports

ARTIFACTS_DIR = ROOT / "artifacts"
DEFAULT_JOINED = ARTIFACTS_DIR / "radar_outcome_joined_T0_T67_20260914_124311.jsonl"
DEFAULT_REVIEW_ID = "20260914_124311"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline signal robustness diagnostics T0→T67.")
    parser.add_argument("--joined", type=Path, default=DEFAULT_JOINED)
    parser.add_argument("--output-dir", type=Path, default=ARTIFACTS_DIR)
    parser.add_argument("--review-id", default=DEFAULT_REVIEW_ID)
    parser.add_argument("--elapsed-hours", type=float, default=67.0689)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.joined.is_file():
        raise SystemExit(f"Joined dataset not found: {args.joined}")

    report = run_signal_robustness_analysis(args.joined, elapsed_hours=args.elapsed_hours)
    json_path, md_path = write_robustness_reports(
        report,
        output_dir=args.output_dir,
        review_id=args.review_id,
    )
    print(
        f"[RADAR_SIGNAL_ROBUSTNESS] {json.dumps({'json': str(json_path), 'md': str(md_path)}, ensure_ascii=False)}",
        flush=True,
    )


if __name__ == "__main__":
    main()
