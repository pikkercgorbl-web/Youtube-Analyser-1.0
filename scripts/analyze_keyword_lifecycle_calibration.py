"""Keyword lifecycle calibration observation CLI (Stage 1.20E). Read-only."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models.db import SessionLocal
from app.services.keyword_lifecycle_calibration_service import (
    build_calibration_report,
    report_to_summary_dict,
)


def _json_default(obj: object) -> str:
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(type(obj))


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row[k] for k in fieldnames})


def main() -> int:
    parser = argparse.ArgumentParser(description="Keyword lifecycle calibration report (read-only).")
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--status", type=str, default=None, help="Filter lifecycle_status")
    parser.add_argument("--include-breakout", action="store_true", default=True)
    parser.add_argument("--no-breakout", action="store_true")
    parser.add_argument("--include-delayed", action="store_true", default=True)
    parser.add_argument("--no-delayed", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print full summary JSON")
    parser.add_argument("--export-csv", type=str, default=None, help="Directory for keyword + scan CSV exports")
    parser.add_argument(
        "--72h-diagnostics",
        dest="horizon_diagnostics",
        action="store_true",
        help="Print focused 72h outcome coverage diagnostics (read-only)",
    )
    args = parser.parse_args()

    include_breakout = not args.no_breakout
    include_delayed = not args.no_delayed

    session = SessionLocal()
    try:
        report = build_calibration_report(
            session,
            lifecycle_status=args.status,
            include_breakout=include_breakout,
            include_delayed=include_delayed,
            limit=max(1, args.limit),
        )
        summary = report_to_summary_dict(report)
        if args.horizon_diagnostics:
            block = summary.get("outcome_72h_coverage") or {}
            diag = block.get("72h_diagnostics")
            if diag:
                print(json.dumps({"72h_diagnostics": diag}, indent=2, default=_json_default))
            else:
                print(json.dumps({"72h_diagnostics": block}, indent=2, default=_json_default))
        elif args.json:
            print(json.dumps(summary, indent=2, default=_json_default))
        else:
            print(json.dumps(summary, indent=2, default=_json_default))

        if args.export_csv:
            out_dir = Path(args.export_csv)
            out_dir.mkdir(parents=True, exist_ok=True)
            kw_rows = [asdict(r) for r in report.keyword_rows]
            scan_rows = [asdict(r) for r in report.scan_rows]
            for row in kw_rows + scan_rows:
                for key, val in list(row.items()):
                    if isinstance(val, datetime):
                        row[key] = val.isoformat()
            _write_csv(out_dir / "keyword_calibration.csv", kw_rows)
            _write_csv(out_dir / "scan_calibration.csv", scan_rows)
            print(f"Wrote CSV to {out_dir}", file=sys.stderr)
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
