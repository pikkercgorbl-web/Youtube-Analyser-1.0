"""Parity tests for operations query consolidation (Stage 1.19B2)."""

from __future__ import annotations

import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.models.orm import (
    Channel,
    DiscoveryWorkerState,
    KeywordDiscoveryHit,
    KeywordScanRun,
    MonitoringCycleRun,
    TargetKeyword,
    Video,
    VideoFormat,
    VideoSnapshot,
)
from app.services.discovery_worker_lock import DISCOVERY_WORKER_STATE_ROW_ID
from app.services.keyword_scheduling_policy import LIFECYCLE_ACTIVE, LIFECYCLE_ARCHIVED
from app.services.operations_overview_queries import (
    build_snapshot_metrics_batch,
    count_keywords_due_batch,
    load_discovery_cycle_summaries,
    load_monitoring_cycle_runs,
)
from app.services.operations_overview_service import (
    aggregate_discovery_cycle,
    build_operations_overview,
    build_operations_overview_sequential,
    build_snapshot_metrics_sequential,
    count_keywords_due_sequential,
    list_recent_discovery_run_ids,
)

UTC = timezone.utc
NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _session():
    return sessionmaker(bind=_engine())()


def _overview_dict(overview) -> dict:
    d = asdict(overview)
    d.pop("generated_at", None)
    d["recent_cycles"] = {
        "discovery": [asdict(c) for c in overview.recent_cycles.discovery],
        "monitoring": [row.run_id for row in overview.recent_cycles.monitoring],
    }
    return d


def test_keyword_due_batch_matches_sequential() -> None:
    session = _session()
    session.add(TargetKeyword(keyword="a", lifecycle_status=LIFECYCLE_ACTIVE, next_scan_at=None))
    session.add(
        TargetKeyword(
            keyword="b",
            lifecycle_status=LIFECYCLE_ACTIVE,
            next_scan_at=NOW + timedelta(minutes=30),
        ),
    )
    session.add(
        TargetKeyword(
            keyword="c",
            lifecycle_status=LIFECYCLE_ARCHIVED,
            next_scan_at=NOW - timedelta(hours=1),
        ),
    )
    session.commit()
    assert count_keywords_due_batch(session, now=NOW) == count_keywords_due_sequential(session, now=NOW)


def test_snapshot_batch_matches_sequential() -> None:
    session = _session()
    session.add(Channel(id="ch", title="C", subscribers_count=1, created_at=NOW))
    session.add(
        Video(
            id="v1",
            channel_id="ch",
            title="T",
            published_at=NOW - timedelta(days=2),
            content_format=VideoFormat.UNKNOWN,
        ),
    )
    session.flush()
    session.add(
        VideoSnapshot(
            video_id="v1",
            channel_id="ch",
            captured_at=NOW - timedelta(minutes=30),
            views=1,
            source="t",
            run_id="r1",
        ),
    )
    session.add(
        VideoSnapshot(
            video_id="v1",
            channel_id="ch",
            captured_at=NOW - timedelta(hours=20),
            views=2,
            source="t",
            run_id="r2",
        ),
    )
    session.commit()
    batch = build_snapshot_metrics_batch(session, now=NOW)
    seq = build_snapshot_metrics_sequential(session, now=NOW)
    assert batch.latest_snapshot_at == seq.latest_snapshot_at
    assert batch.snapshots_last_1h == seq.snapshots_last_1h
    assert batch.snapshots_last_24h == seq.snapshots_last_24h
    assert batch.unique_videos_snapshotted_last_24h == seq.unique_videos_snapshotted_last_24h
    assert batch.daily_counts_last_7d == seq.daily_counts_last_7d


def test_discovery_batch_matches_aggregate() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k")
    session.add(kw)
    session.flush()
    run_id = "run-a"
    session.add(
        KeywordScanRun(
            keyword_id=kw.id,
            discovery_run_id=run_id,
            started_at=NOW - timedelta(minutes=10),
            finished_at=NOW - timedelta(minutes=9),
            status="ok",
            raw_candidates=5,
            unique_candidates=3,
            persisted_videos=1,
            runtime_seconds=2.0,
        ),
    )
    session.commit()
    history, by_id = load_discovery_cycle_summaries(session, history_limit=5)
    ref = aggregate_discovery_cycle(session, run_id)
    assert len(history) == 1
    assert by_id[run_id] == ref


def test_monitoring_single_load_for_latest_and_history() -> None:
    session = _session()
    for idx in range(3):
        session.add(
            MonitoringCycleRun(
                run_id=f"m-{idx}",
                started_at=NOW - timedelta(minutes=idx),
                finished_at=NOW,
                runtime_seconds=1.0,
                cycle_status="ok",
                error_summary="err" if idx == 1 else None,
            ),
        )
    session.commit()
    rows = load_monitoring_cycle_runs(session, limit=2)
    assert len(rows) == 2
    assert rows[0].run_id == "m-0"


def test_full_overview_parity_fixture() -> None:
    session = _session()
    session.add(
        DiscoveryWorkerState(
            id=DISCOVERY_WORKER_STATE_ROW_ID,
            status="idle",
            last_run_id="disc-1",
            last_cycle_status="ok",
        ),
    )
    kw = TargetKeyword(keyword="k", lifecycle_status=LIFECYCLE_ACTIVE, next_scan_at=NOW)
    session.add(kw)
    session.flush()
    session.add(
        KeywordScanRun(
            keyword_id=kw.id,
            discovery_run_id="disc-1",
            started_at=NOW - timedelta(minutes=5),
            finished_at=NOW - timedelta(minutes=4),
            status="ok",
            raw_candidates=1,
            unique_candidates=1,
            persisted_videos=1,
            runtime_seconds=1.0,
        ),
    )
    session.add(
        MonitoringCycleRun(
            run_id="mon-1",
            started_at=NOW - timedelta(minutes=3),
            finished_at=NOW - timedelta(minutes=2),
            runtime_seconds=2.0,
            cycle_status="ok",
        ),
    )
    session.commit()
    consolidated = _overview_dict(
        build_operations_overview(session, now=NOW, discovery_history_limit=5, monitoring_history_limit=5),
    )
    sequential = _overview_dict(
        build_operations_overview_sequential(
            session,
            now=NOW,
            discovery_history_limit=5,
            monitoring_history_limit=5,
        ),
    )
    assert consolidated == sequential


def test_bounded_sql_query_count() -> None:
    session = _session()
    session.add(DiscoveryWorkerState(id=DISCOVERY_WORKER_STATE_ROW_ID, status="idle"))
    session.commit()
    engine = session.get_bind()
    count = 0

    def before_cursor_execute(*_a, **_k) -> None:
        nonlocal count
        count += 1

    event.listen(engine, "before_cursor_execute", before_cursor_execute, retval=False)
    try:
        build_operations_overview(session, now=NOW, discovery_history_limit=5, monitoring_history_limit=5)
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
    assert count <= 12


def main() -> None:
    tests = [
        test_keyword_due_batch_matches_sequential,
        test_snapshot_batch_matches_sequential,
        test_discovery_batch_matches_aggregate,
        test_monitoring_single_load_for_latest_and_history,
        test_full_overview_parity_fixture,
        test_bounded_sql_query_count,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"OK {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")
    if failed:
        raise SystemExit(f"{failed} failed")
    print("All query consolidation tests passed.")


if __name__ == "__main__":
    main()
