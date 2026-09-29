"""Read-only T0 cohort data quality audit CLI (Stage 1.8.4)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.radar_t0_data_quality import (
    audit_t0_dataset,
    load_t0_jsonl,
    write_audit_reports,
)

ARTIFACTS_DIR = ROOT / "artifacts"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run read-only data quality audit on an existing cohort_T0 JSONL file.",
    )
    parser.add_argument(
        "jsonl_path",
        type=Path,
        help="Path to cohort_T0 JSONL (e.g. artifacts/cohort_T0_20260911_172900_gaming.jsonl)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ARTIFACTS_DIR,
        help="Directory for audit JSON/MD reports (default: artifacts/)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    jsonl_path = args.jsonl_path
    if not jsonl_path.is_file():
        raise SystemExit(f"JSONL file not found: {jsonl_path}")

    records = load_t0_jsonl(jsonl_path)
    if not records:
        raise SystemExit(f"No records found in {jsonl_path}")

    audit = audit_t0_dataset(records, source_path=str(jsonl_path.resolve()))
    json_report_path, md_report_path = write_audit_reports(
        audit,
        output_dir=args.output_dir,
        keyword=str(audit.get("keyword") or "dataset"),
    )

    print(f"[RADAR_T0_QUALITY_AUDIT] {json.dumps({'verdict': audit['final_verdict'], 'json': str(json_report_path), 'md': str(md_report_path)}, ensure_ascii=False)}", flush=True)
    print(f"Final verdict: {audit['final_verdict']}", flush=True)
    print(f"JSON report: {json_report_path}", flush=True)
    print(f"MD report: {md_report_path}", flush=True)


if __name__ == "__main__":
    main()
