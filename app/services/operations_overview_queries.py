"""Batched SQL for operations overview (Stage 1.19B2)."""

from __future__ import annotations

from datetime import datetime, timedelta
from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session

from app.models.orm import DiscoveryWorkerState, KeywordScanRun, MonitoringCycleRun, TargetKeyword, VideoSnapshot
from app.services.discovery_worker_lock import DISCOVERY_WORKER_STATE_ROW_ID
from app.services.keyword_scheduling_policy import LIFECYCLE_ARCHIVED
from app.services.metrics import ensure_utc, utc_now


def fetch_discovery_worker_state(session: Session) -> DiscoveryWorkerState | None:
    return session.get(DiscoveryWorkerState, DISCOVERY_WORKER_STATE_ROW_ID)


def count_keywords_due_batch(session: Session, *, now: datetime | None = None) -> tuple[int, int, int]:
    reference = ensure_utc(now or utc_now())
    in_1h = reference + timedelta(hours=1)
    in_24h = reference + timedelta(hours=24)
    not_archived = TargetKeyword.lifecycle_status != LIFECYCLE_ARCHIVED
    due_now_expr = case(
        (
            (TargetKeyword.next_scan_at.is_(None)) | (TargetKeyword.next_scan_at <= reference),
            1,
        ),
        else_=0,
    )
    due_1h_expr = case(
        (
            (
                TargetKeyword.next_scan_at.is_not(None)
                & (TargetKeyword.next_scan_at > reference)
                & (TargetKeyword.next_scan_at <= in_1h)
            ),
            1,
        ),
        else_=0,
    )
    due_24h_expr = case(
        (
            (
                TargetKeyword.next_scan_at.is_not(None)
                & (TargetKeyword.next_scan_at > reference)
                & (TargetKeyword.next_scan_at <= in_24h)
            ),
            1,
        ),
        else_=0,
    )
    row = session.execute(
        select(
            func.coalesce(func.sum(due_now_expr), 0),
            func.coalesce(func.sum(due_1h_expr), 0),
            func.coalesce(func.sum(due_24h_expr), 0),
        ).where(not_archived),
    ).one()
    return int(row[0]), int(row[1]), int(row[2])


def _summarize_scan_runs(discovery_run_id: str, rows: list[KeywordScanRun]):
    from app.services.operations_overview_service import DiscoveryCycleSummaryOps, _sanitize_error

    if not rows:
        return DiscoveryCycleSummaryOps(
            discovery_run_id=discovery_run_id,
            started_at=None,
            finished_at=None,
            runtime_seconds=None,
            keywords_scanned=0,
            raw_candidates=0,
            unique_candidates=0,
            persisted_videos=0,
            qualification_passed=0,
            qualification_rejected=0,
            keyword_scan_failures=0,
            error_summaries=(),
        )
    started = min(r.started_at for r in rows)
    finished = max(r.finished_at for r in rows)
    runtime = max((r.runtime_seconds for r in rows), default=0.0)
    failures = sum(1 for r in rows if r.status != "ok")
    summaries = tuple(
        s for s in (_sanitize_error(r.error_summary) for r in rows if r.error_summary) if s
    )
    return DiscoveryCycleSummaryOps(
        discovery_run_id=discovery_run_id,
        started_at=started,
        finished_at=finished,
        runtime_seconds=round(float(runtime), 4),
        keywords_scanned=len(rows),
        raw_candidates=sum(r.raw_candidates for r in rows),
        unique_candidates=sum(r.unique_candidates for r in rows),
        persisted_videos=sum(r.persisted_videos for r in rows),
        qualification_passed=sum(r.qualification_passed for r in rows),
        qualification_rejected=sum(r.qualification_rejected for r in rows),
        keyword_scan_failures=failures,
        error_summaries=summaries[:10],
    )


def load_discovery_cycle_summaries(
    session: Session,
    *,
    history_limit: int,
    extra_run_id: str | None = None,
):
    """One id-ranking query + one scan-row fetch; build summaries in Python."""
    limit = max(1, min(history_limit, 50))
    id_rows = session.execute(
        select(
            KeywordScanRun.discovery_run_id,
            func.max(KeywordScanRun.started_at).label("last_start"),
        )
        .group_by(KeywordScanRun.discovery_run_id)
        .order_by(func.max(KeywordScanRun.started_at).desc())
        .limit(limit),
    ).all()
    history_ids = [row[0] for row in id_rows]
    fetch_ids = list(history_ids)
    if extra_run_id and extra_run_id not in fetch_ids:
        fetch_ids.append(extra_run_id)
    if not fetch_ids:
        return [], {}

    scan_rows = list(
        session.scalars(
            select(KeywordScanRun).where(KeywordScanRun.discovery_run_id.in_(fetch_ids)),
        ).all(),
    )
    by_run: dict[str, list[KeywordScanRun]] = {}
    for row in scan_rows:
        by_run.setdefault(row.discovery_run_id, []).append(row)

    by_id = {rid: _summarize_scan_runs(rid, by_run.get(rid, [])) for rid in fetch_ids}
    history = [by_id[rid] for rid in history_ids if rid in by_id]
    return history, by_id


def load_monitoring_cycle_runs(session: Session, *, limit: int) -> list[MonitoringCycleRun]:
    capped = max(1, min(limit, 50))
    stmt = (
        select(MonitoringCycleRun)
        .order_by(MonitoringCycleRun.started_at.desc(), MonitoringCycleRun.id.desc())
        .limit(capped)
    )
    return list(session.scalars(stmt).all())


def build_snapshot_metrics_batch(session: Session, *, now: datetime | None = None):
    from app.services.operations_overview_service import SnapshotDailyCount, SnapshotOperationsBlock

    reference = ensure_utc(now or utc_now())
    since_1h = reference - timedelta(hours=1)
    since_24h = reference - timedelta(hours=24)
    dialect = session.get_bind().dialect.name

    if dialect == "postgresql":
        summary_stmt = text(
            """
            SELECT
                MAX(captured_at) AS latest_at,
                COUNT(*) FILTER (WHERE captured_at >= :since_1h)::int AS cnt_1h,
                COUNT(*) FILTER (WHERE captured_at >= :since_24h)::int AS cnt_24h,
                COUNT(DISTINCT video_id) FILTER (WHERE captured_at >= :since_24h)::int AS uniq_24h
            FROM video_snapshots
            """,
        )
    else:
        summary_stmt = text(
            """
            SELECT
                MAX(captured_at) AS latest_at,
                SUM(CASE WHEN captured_at >= :since_1h THEN 1 ELSE 0 END) AS cnt_1h,
                SUM(CASE WHEN captured_at >= :since_24h THEN 1 ELSE 0 END) AS cnt_24h,
                COUNT(DISTINCT CASE WHEN captured_at >= :since_24h THEN video_id END) AS uniq_24h
            FROM video_snapshots
            """,
        )

    summary = session.execute(
        summary_stmt,
        {"since_1h": since_1h, "since_24h": since_24h},
    ).mappings().one()

    day_starts: list[datetime] = []
    for days_ago in range(6, -1, -1):
        day_starts.append(
            (reference - timedelta(days=days_ago)).replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            ),
        )
    range_start = day_starts[0]
    range_end = day_starts[-1] + timedelta(days=1)

    if dialect == "postgresql":
        daily_stmt = text(
            """
            SELECT
                (date_trunc('day', captured_at AT TIME ZONE 'UTC'))::date AS bucket_date,
                COUNT(*)::int AS cnt
            FROM video_snapshots
            WHERE captured_at >= :range_start AND captured_at < :range_end
            GROUP BY 1
            ORDER BY 1
            """,
        )
    else:
        daily_stmt = text(
            """
            SELECT date(captured_at) AS bucket_date, COUNT(*) AS cnt
            FROM video_snapshots
            WHERE captured_at >= :range_start AND captured_at < :range_end
            GROUP BY 1
            ORDER BY 1
            """,
        )

    daily_rows = session.execute(
        daily_stmt,
        {"range_start": range_start, "range_end": range_end},
    ).all()
    counts_by_date: dict[str, int] = {}
    for row in daily_rows:
        raw_date = row[0]
        if hasattr(raw_date, "isoformat"):
            key = raw_date.isoformat()
        else:
            key = str(raw_date)[:10]
        counts_by_date[key] = int(row[1])
    daily: list[SnapshotDailyCount] = []
    for day_start in day_starts:
        key = day_start.date().isoformat()
        daily.append(SnapshotDailyCount(date=key, count=counts_by_date.get(key, 0)))

    latest_at = summary["latest_at"]
    if latest_at is not None and not isinstance(latest_at, datetime):
        text_val = str(latest_at).replace(" ", "T", 1)
        latest_at = datetime.fromisoformat(text_val)
    if latest_at is not None and latest_at.tzinfo is not None:
        latest_at = ensure_utc(latest_at).replace(tzinfo=None)

    return SnapshotOperationsBlock(
        latest_snapshot_at=latest_at,
        snapshots_last_1h=int(summary["cnt_1h"] or 0),
        snapshots_last_24h=int(summary["cnt_24h"] or 0),
        unique_videos_snapshotted_last_24h=int(summary["uniq_24h"] or 0),
        daily_counts_last_7d=daily,
    )
