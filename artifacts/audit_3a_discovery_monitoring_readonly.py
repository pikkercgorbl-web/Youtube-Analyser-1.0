"""
Fix 3A read-only audit: Discovery due queue + Monitoring partial cycles.
No writes. Outputs JSON to artifacts/audit_3a_discovery_monitoring_report.json
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select, text  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.models.db import SessionLocal  # noqa: E402
from app.models.orm import (  # noqa: E402
    DiscoveryWorkerState,
    KeywordScanRun,
    MonitoringCycleRun,
    MonitoringWorkerState,
    TargetKeyword,
)
from app.services.keyword_scheduling_policy import LIFECYCLE_ARCHIVED  # noqa: E402
from app.services.metrics import ensure_utc, utc_now  # noqa: E402
from app.services.operations_overview_queries import count_keywords_due_batch  # noqa: E402


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return ensure_utc(dt).isoformat()


def main() -> None:
    snapshot_at = utc_now()
    settings = Settings()
    report: dict = {
        "snapshot_at_utc": _iso(snapshot_at),
        "database_url_redacted": settings.database_url.split("@")[-1]
        if "@" in settings.database_url
        else settings.database_url,
    }

    with SessionLocal() as session:
        due_now, due_1h, due_24h = count_keywords_due_batch(session, now=snapshot_at)
        report["discovery_due_counts_backend"] = {
            "due_now": due_now,
            "due_next_1h_exclusive": due_1h,
            "due_next_24h_cumulative": due_24h,
            "source": "app.services.operations_overview_queries.count_keywords_due_batch",
        }

        not_archived = TargetKeyword.lifecycle_status != LIFECYCLE_ARCHIVED
        ref = ensure_utc(snapshot_at)

        due_clause = (TargetKeyword.next_scan_at.is_(None)) | (
            TargetKeyword.next_scan_at <= ref
        )

        total_not_archived = session.scalar(
            select(func.count()).select_from(TargetKeyword).where(not_archived),
        )
        due_total = session.scalar(
            select(func.count()).select_from(TargetKeyword).where(not_archived, due_clause),
        )
        null_next = session.scalar(
            select(func.count())
            .select_from(TargetKeyword)
            .where(not_archived, TargetKeyword.next_scan_at.is_(None)),
        )

        report["discovery_due_crosscheck"] = {
            "not_archived_keywords": int(total_not_archived or 0),
            "due_now_rows": int(due_total or 0),
            "due_with_null_next_scan_at": int(null_next or 0),
        }

        # Overdue age buckets (only rows with next_scan_at set and due)
        overdue_buckets = session.execute(
            text(
                """
                SELECT bucket, COUNT(*) AS n
                FROM (
                  SELECT CASE
                    WHEN next_scan_at IS NULL THEN 'null_next_scan_at'
                    WHEN next_scan_at > :ref THEN 'not_due'
                    WHEN :ref - next_scan_at <= interval '1 hour' THEN 'overdue_0_1h'
                    WHEN :ref - next_scan_at <= interval '24 hours' THEN 'overdue_1_24h'
                    WHEN :ref - next_scan_at <= interval '7 days' THEN 'overdue_1_7d'
                    ELSE 'overdue_7d_plus'
                  END AS bucket
                  FROM target_keywords
                  WHERE lifecycle_status != 'archived'
                ) t
                WHERE bucket != 'not_due'
                GROUP BY bucket
                ORDER BY bucket
                """
            ),
            {"ref": ref},
        ).all()
        report["discovery_due_overdue_buckets"] = {row[0]: int(row[1]) for row in overdue_buckets}

        by_lifecycle = session.execute(
            select(TargetKeyword.lifecycle_status, func.count())
            .where(not_archived)
            .group_by(TargetKeyword.lifecycle_status)
        ).all()
        report["discovery_by_lifecycle_not_archived"] = {
            str(row[0]): int(row[1]) for row in by_lifecycle
        }

        by_source = session.execute(
            select(TargetKeyword.source_type, func.count())
            .where(not_archived)
            .group_by(TargetKeyword.source_type)
            .order_by(func.count().desc())
        ).all()
        report["discovery_by_source_type_not_archived"] = {
            str(row[0]): int(row[1]) for row in by_source
        }

        due_by_source = session.execute(
            select(TargetKeyword.source_type, func.count())
            .where(not_archived, due_clause)
            .group_by(TargetKeyword.source_type)
            .order_by(func.count().desc())
        ).all()
        report["discovery_due_by_source_type"] = {
            str(row[0]): int(row[1]) for row in due_by_source
        }

        due_by_lifecycle = session.execute(
            select(TargetKeyword.lifecycle_status, func.count())
            .where(not_archived, due_clause)
            .group_by(TargetKeyword.lifecycle_status)
        ).all()
        report["discovery_due_by_lifecycle"] = {
            str(row[0]): int(row[1]) for row in due_by_lifecycle
        }

        # Historical window: keyword_scan_runs (not a due-queue time series)
        for hours in (24, 72):
            since = ref - timedelta(hours=hours)
            runs = session.scalars(
                select(KeywordScanRun).where(KeywordScanRun.started_at >= since),
            ).all()
            distinct_keywords = len({r.keyword_id for r in runs})
            distinct_cycles = len({r.discovery_run_id for r in runs})
            status_counts: dict[str, int] = defaultdict(int)
            for r in runs:
                status_counts[r.status] += 1
            report[f"discovery_scan_activity_last_{hours}h"] = {
                "keyword_scan_run_rows": len(runs),
                "distinct_keyword_ids_scanned": distinct_keywords,
                "distinct_discovery_run_ids": distinct_cycles,
                "scan_run_status_counts": dict(status_counts),
                "note": "Historical scan activity; not equal to 'became due' count (no due-event log).",
            }

        # Per-cycle aggregates last 72h
        since_72 = ref - timedelta(hours=72)
        cycle_rows = session.execute(
            text(
                """
                SELECT discovery_run_id,
                       MIN(started_at) AS started,
                       MAX(finished_at) AS finished,
                       COUNT(*) AS keyword_scans,
                       COUNT(DISTINCT keyword_id) AS distinct_keywords,
                       SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_scans,
                       SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS ok_scans
                FROM keyword_scan_runs
                WHERE started_at >= :since
                GROUP BY discovery_run_id
                ORDER BY MIN(started_at) DESC
                LIMIT 30
                """
            ),
            {"since": since_72},
        ).all()
        report["discovery_cycles_last_72h_sample"] = [
            {
                "discovery_run_id": row[0],
                "started_at": _iso(row[1]),
                "finished_at": _iso(row[2]),
                "keyword_scan_rows": int(row[3]),
                "distinct_keywords": int(row[4]),
                "failed_scans": int(row[5]),
                "ok_scans": int(row[6]),
            }
            for row in cycle_rows
        ]

        # Repeat failures
        repeat_fail = session.execute(
            text(
                """
                SELECT keyword_id, COUNT(*) AS fail_count
                FROM keyword_scan_runs
                WHERE status = 'failed' AND started_at >= :since
                GROUP BY keyword_id
                HAVING COUNT(*) >= 3
                ORDER BY fail_count DESC
                LIMIT 20
                """
            ),
            {"since": since_72},
        ).all()
        report["discovery_repeat_failed_keywords_72h"] = [
            {"keyword_id": int(row[0]), "failed_scan_count": int(row[1])} for row in repeat_fail
        ]

        dw = session.get(DiscoveryWorkerState, 1)
        report["discovery_worker_state"] = {
            "status": dw.status if dw else None,
            "lock_holder": dw.lock_holder if dw else None,
            "lock_acquired_at": _iso(dw.lock_acquired_at if dw else None),
            "last_cycle_started_at": _iso(dw.last_cycle_started_at if dw else None),
            "last_cycle_finished_at": _iso(dw.last_cycle_finished_at if dw else None),
            "last_cycle_status": dw.last_cycle_status if dw else None,
            "last_run_id": dw.last_run_id if dw else None,
            "last_error": (dw.last_error[:500] if dw and dw.last_error else None),
        }

        # Monitoring cycles
        cycles = session.scalars(
            select(MonitoringCycleRun)
            .order_by(MonitoringCycleRun.started_at.desc())
            .limit(10),
        ).all()

        def partial_reason(c: MonitoringCycleRun) -> str:
            if c.cycle_status != "partial":
                return ""
            parts = []
            if c.fetch_failed_count:
                parts.append(f"fetch_failed={c.fetch_failed_count}")
            if c.missing_count:
                parts.append(f"missing={c.missing_count}")
            if c.validation_failed_count:
                parts.append(f"validation_failed={c.validation_failed_count}")
            if c.persistence_failed_count:
                parts.append(f"persistence_failed={c.persistence_failed_count}")
            if not parts:
                parts.append("partial_with_zero_stored_failure_counts (check failed_batch_count in logs)")
            return "; ".join(parts)

        report["monitoring_last_10_cycles"] = [
            {
                "run_id": c.run_id,
                "started_at": _iso(c.started_at),
                "finished_at": _iso(c.finished_at),
                "cycle_status": c.cycle_status,
                "loaded_video_count": c.loaded_video_count,
                "eligible_video_count": c.eligible_video_count,
                "due_count": c.due_count,
                "overdue_count": c.overdue_count,
                "selected_request_count": c.selected_request_count,
                "deferred_request_count": c.deferred_request_count,
                "inserted_snapshot_count": c.inserted_snapshot_count,
                "duplicate_snapshot_count": c.duplicate_snapshot_count,
                "missing_count": c.missing_count,
                "fetch_failed_count": c.fetch_failed_count,
                "validation_failed_count": c.validation_failed_count,
                "persistence_failed_count": c.persistence_failed_count,
                "partial_reason_from_stored_counts": partial_reason(c),
                "error_summary": (c.error_summary[:300] if c.error_summary else None),
            }
            for c in cycles
        ]

        partial_total = sum(1 for c in cycles if c.cycle_status == "partial")
        ok_total = sum(1 for c in cycles if c.cycle_status == "ok")
        report["monitoring_last_10_status_mix"] = {
            "partial": partial_total,
            "ok": ok_total,
            "other": 10 - partial_total - ok_total,
        }

        since_72m = ref - timedelta(hours=72)
        mon_hist = session.execute(
            select(
                MonitoringCycleRun.cycle_status,
                func.count(),
            )
            .where(MonitoringCycleRun.started_at >= since_72m)
            .group_by(MonitoringCycleRun.cycle_status)
        ).all()
        report["monitoring_cycle_status_last_72h"] = {
            str(row[0]): int(row[1]) for row in mon_hist
        }

        agg_partial = session.execute(
            text(
                """
                SELECT
                  SUM(CASE WHEN cycle_status = 'partial' THEN 1 ELSE 0 END) AS partial_cycles,
                  SUM(CASE WHEN cycle_status = 'partial' AND missing_count > 0 THEN 1 ELSE 0 END) AS partial_with_missing,
                  SUM(CASE WHEN cycle_status = 'partial' AND fetch_failed_count > 0 THEN 1 ELSE 0 END) AS partial_with_fetch,
                  SUM(CASE WHEN cycle_status = 'partial' AND validation_failed_count > 0 THEN 1 ELSE 0 END) AS partial_with_validation,
                  SUM(CASE WHEN cycle_status = 'partial' AND persistence_failed_count > 0 THEN 1 ELSE 0 END) AS partial_with_persist,
                  SUM(CASE WHEN cycle_status = 'partial'
                    AND missing_count = 0 AND fetch_failed_count = 0
                    AND validation_failed_count = 0 AND persistence_failed_count = 0
                    THEN 1 ELSE 0 END) AS partial_all_zero
                FROM monitoring_cycle_runs
                WHERE started_at >= :since
                """
            ),
            {"since": since_72m},
        ).one()
        report["monitoring_partial_decomposition_72h"] = {
            "partial_cycles": int(agg_partial[0] or 0),
            "partial_with_missing": int(agg_partial[1] or 0),
            "partial_with_fetch_failed": int(agg_partial[2] or 0),
            "partial_with_validation_failed": int(agg_partial[3] or 0),
            "partial_with_persistence_failed": int(agg_partial[4] or 0),
            "partial_all_failure_counts_zero": int(agg_partial[5] or 0),
        }

        mw = session.get(MonitoringWorkerState, 1)
        report["monitoring_worker_state"] = {
            "status": mw.status if mw else None,
            "lock_holder": mw.lock_holder if mw else None,
            "lock_acquired_at": _iso(mw.lock_acquired_at if mw else None),
            "updated_at": _iso(mw.updated_at if mw else None),
        }

    out_path = ROOT / "artifacts" / "audit_3a_discovery_monitoring_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"written": str(out_path), "due_now": report["discovery_due_counts_backend"]["due_now"]}, indent=2))


if __name__ == "__main__":
    main()
