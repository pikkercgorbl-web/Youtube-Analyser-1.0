"""Fix 3B read-only: delay distribution, intake vs scans, missing video_ids."""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.models.db import SessionLocal  # noqa: E402
from app.services.metrics import utc_now  # noqa: E402


def _percentile(sorted_vals: list[float], p: float) -> float | None:
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def main() -> None:
    ref = utc_now()
    report: dict = {"snapshot_at_utc": ref.isoformat()}

    with SessionLocal() as session:
        # Overdue seconds for due keywords by source/lifecycle
        rows = session.execute(
            text(
                """
                SELECT source_type, lifecycle_status,
                       EXTRACT(EPOCH FROM (:ref - next_scan_at)) AS overdue_sec
                FROM target_keywords
                WHERE lifecycle_status != 'archived'
                  AND next_scan_at IS NOT NULL
                  AND next_scan_at <= :ref
                """
            ),
            {"ref": ref},
        ).all()
        buckets: dict[str, list[float]] = {}
        for source, lifecycle, overdue in rows:
            key = f"{source}|{lifecycle}"
            buckets.setdefault(key, []).append(float(overdue))
        delay_stats = {}
        for key, vals in buckets.items():
            vals.sort()
            delay_stats[key] = {
                "count": len(vals),
                "p50_hours": round(_percentile(vals, 0.5) / 3600, 2) if vals else None,
                "p90_hours": round(_percentile(vals, 0.9) / 3600, 2) if vals else None,
                "max_hours": round(max(vals) / 3600, 2) if vals else None,
            }
        report["due_overdue_hours_by_source_lifecycle"] = delay_stats

        for hours in (24, 72):
            since = ref - timedelta(hours=hours)
            created = session.execute(
                text(
                    """
                    SELECT source_type, lifecycle_status, COUNT(*) AS n
                    FROM target_keywords
                    WHERE created_at >= :since AND lifecycle_status != 'archived'
                    GROUP BY source_type, lifecycle_status
                    """
                ),
                {"since": since},
            ).all()
            report[f"keywords_created_last_{hours}h"] = {
                f"{r[0]}|{r[1]}": int(r[2]) for r in created
            }
            scanned = session.execute(
                text(
                    """
                    SELECT tk.source_type, tk.lifecycle_status, COUNT(DISTINCT ksr.keyword_id) AS n
                    FROM keyword_scan_runs ksr
                    JOIN target_keywords tk ON tk.id = ksr.keyword_id
                    WHERE ksr.started_at >= :since
                    GROUP BY tk.source_type, tk.lifecycle_status
                    """
                ),
                {"since": since},
            ).all()
            report[f"keywords_scanned_last_{hours}h_by_source_lifecycle"] = {
                f"{r[0]}|{r[1]}": int(r[2]) for r in scanned
            }

        # Examples: seed due with high overdue
        examples = session.execute(
            text(
                """
                SELECT id, keyword, source_type, lifecycle_status,
                       EXTRACT(EPOCH FROM (:ref - next_scan_at))/3600 AS overdue_h
                FROM target_keywords
                WHERE lifecycle_status != 'archived'
                  AND next_scan_at <= :ref
                  AND source_type = 'seed'
                ORDER BY overdue_h DESC
                LIMIT 5
                """
            ),
            {"ref": ref},
        ).all()
        report["example_overdue_seed_keywords"] = [
            {
                "keyword_id": int(r[0]),
                "keyword": r[1],
                "source_type": r[2],
                "lifecycle_status": r[3],
                "overdue_hours": round(float(r[4]), 2),
            }
            for r in examples
        ]

        missing_last_10 = session.execute(
            text(
                """
                SELECT monitoring_run_id, video_id, checkpoint_age_hours, outcome, attempted_at
                FROM monitoring_capture_outcomes
                WHERE outcome = 'missing'
                ORDER BY attempted_at DESC
                LIMIT 10
                """
            ),
        ).all()
        report["last_10_missing_capture_outcomes"] = [
            {
                "monitoring_run_id": r[0],
                "video_id": r[1],
                "checkpoint_age_hours": int(r[2]),
                "outcome": r[3],
                "attempted_at": r[4].isoformat() if r[4] else None,
            }
            for r in missing_last_10
        ]
        if missing_last_10:
            vid_counts = session.execute(
                text(
                    """
                    SELECT video_id, COUNT(*) AS n
                    FROM monitoring_capture_outcomes
                    WHERE outcome = 'missing' AND attempted_at >= :since
                    GROUP BY video_id
                    ORDER BY n DESC
                    LIMIT 5
                    """
                ),
                {"since": ref - timedelta(hours=72)},
            ).all()
            report["top_missing_video_ids_72h"] = [
                {"video_id": r[0], "missing_count": int(r[1])} for r in vid_counts
            ]
        else:
            report["top_missing_video_ids_72h"] = []
            report["missing_outcomes_note"] = (
                "Таблица monitoring_capture_outcomes пуста для missing — "
                "video_id задним числом из cycle runs определить нельзя."
            )

    out = ROOT / "artifacts" / "audit_3b_discovery_monitoring_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"written": str(out), "missing_rows": len(report.get("last_10_missing_capture_outcomes", []))}))


if __name__ == "__main__":
    main()
