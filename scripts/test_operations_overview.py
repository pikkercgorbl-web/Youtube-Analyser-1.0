"""Tests for operations overview read model (Stage 1.19B)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.models.orm import (
    DiscoveryWorkerState,
    KeywordDiscoveryHit,
    KeywordScanRun,
    MonitoringCycleRun,
    TargetKeyword,
    Video,
    VideoFormat,
    VideoSnapshot,
    Channel,
)
from app.services.keyword_scheduling_policy import LIFECYCLE_ARCHIVED, LIFECYCLE_ACTIVE
from app.services.operations_overview_service import (
    aggregate_discovery_cycle,
    build_operations_overview,
    compute_keyword_outcome_maturity,
    count_keywords_due,
)

UTC = timezone.utc
NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _session():
    return sessionmaker(bind=_engine())()


def test_keyword_due_now_with_null_next_scan_at() -> None:
    session = _session()
    session.add(TargetKeyword(keyword="due-null", lifecycle_status=LIFECYCLE_ACTIVE, next_scan_at=None))
    session.add(
        TargetKeyword(
            keyword="future",
            lifecycle_status=LIFECYCLE_ACTIVE,
            next_scan_at=NOW + timedelta(hours=5),
        ),
    )
    session.commit()
    due_now, due_1h, due_24h = count_keywords_due(session, now=NOW)
    assert due_now == 1
    assert due_1h == 0
    assert due_24h == 1


def test_archived_keyword_excluded_from_due() -> None:
    session = _session()
    session.add(
        TargetKeyword(
            keyword="arch",
            lifecycle_status=LIFECYCLE_ARCHIVED,
            next_scan_at=NOW - timedelta(hours=1),
        ),
    )
    session.commit()
    due_now, _, _ = count_keywords_due(session, now=NOW)
    assert due_now == 0


def test_due_next_1h_and_24h_buckets() -> None:
    session = _session()
    session.add(
        TargetKeyword(
            keyword="in30m",
            lifecycle_status=LIFECYCLE_ACTIVE,
            next_scan_at=NOW + timedelta(minutes=30),
        ),
    )
    session.add(
        TargetKeyword(
            keyword="in12h",
            lifecycle_status=LIFECYCLE_ACTIVE,
            next_scan_at=NOW + timedelta(hours=12),
        ),
    )
    session.add(
        TargetKeyword(
            keyword="in36h",
            lifecycle_status=LIFECYCLE_ACTIVE,
            next_scan_at=NOW + timedelta(hours=36),
        ),
    )
    session.commit()
    _, due_1h, due_24h = count_keywords_due(session, now=NOW)
    assert due_1h == 1
    assert due_24h == 2


def test_discovery_cycle_grouping() -> None:
    session = _session()
    kw_a = TargetKeyword(keyword="k-a")
    kw_b = TargetKeyword(keyword="k-b")
    session.add_all([kw_a, kw_b])
    session.flush()
    run_id = "discovery_test_run"
    for idx, (kw, status) in enumerate(((kw_a, "ok"), (kw_b, "failed"))):
        session.add(
            KeywordScanRun(
                keyword_id=kw.id,
                discovery_run_id=run_id,
                started_at=NOW - timedelta(minutes=10 - idx),
                finished_at=NOW - timedelta(minutes=9 - idx),
                status=status,
                raw_candidates=10,
                unique_candidates=5,
                persisted_videos=2,
                runtime_seconds=1.5,
            ),
        )
    session.commit()
    agg = aggregate_discovery_cycle(session, run_id)
    assert agg.keywords_scanned == 2
    assert agg.raw_candidates == 20
    assert agg.persisted_videos == 4
    assert agg.keyword_scan_failures == 1


def test_monitoring_latest_cycle_mapping() -> None:
    session = _session()
    session.add(
        MonitoringCycleRun(
            run_id="mon-1",
            started_at=NOW - timedelta(minutes=5),
            finished_at=NOW - timedelta(minutes=4),
            runtime_seconds=12.0,
            cycle_status="ok",
            loaded_video_count=100,
            eligible_video_count=80,
            due_count=3,
            overdue_count=1,
            selected_request_count=5,
            inserted_snapshot_count=4,
        ),
    )
    session.commit()
    overview = build_operations_overview(session, discovery_history_limit=1, monitoring_history_limit=1)
    assert overview.monitoring.last_run_id == "mon-1"
    assert overview.monitoring.due_count_at_last_cycle == 3
    assert overview.monitoring.overdue_count_at_last_cycle == 1
    assert overview.monitoring.inserted_snapshot_count == 4


def test_snapshot_counts_and_latest() -> None:
    session = _session()
    session.add(Channel(id="ch", title="C", subscribers_count=1, created_at=NOW))
    session.add(
        Video(
            id="v1",
            title="V",
            views_count=1,
            likes_count=0,
            comments_count=0,
            published_at=NOW - timedelta(days=1),
            duration_seconds=60,
            content_format=VideoFormat.MEDIUM,
            channel_id="ch",
        ),
    )
    session.add(
        VideoSnapshot(
            video_id="v1",
            channel_id="ch",
            captured_at=NOW - timedelta(minutes=30),
            source="t",
            run_id="r",
            views=100,
        ),
    )
    session.add(
        VideoSnapshot(
            video_id="v1",
            channel_id="ch",
            captured_at=NOW - timedelta(hours=2),
            source="t",
            run_id="r2",
            views=90,
        ),
    )
    session.commit()
    overview = build_operations_overview(session)
    assert overview.snapshots.snapshots_last_1h == 1
    assert overview.snapshots.snapshots_last_24h == 2
    assert overview.snapshots.latest_snapshot_at is not None


def test_first_hit_dedupes_rescan_for_maturity() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k")
    session.add(kw)
    session.flush()
    early = NOW - timedelta(hours=100)
    late = NOW - timedelta(hours=90)
    for run_id, at in (("r1", early), ("r2", late)):
        session.add(
            KeywordDiscoveryHit(
                keyword_id=kw.id,
                video_id="v",
                discovery_run_id=run_id,
                discovered_at=at,
                views_at_discovery=10,
                content_format="regular",
                qualification_state="passed",
            ),
        )
    session.commit()
    out = compute_keyword_outcome_maturity(session, now=NOW)
    assert out.attributed_observation_count == 1
    assert out.matured_72h_count == 1


def test_pending_and_matured_valid_missing() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k")
    session.add(kw)
    session.add(Channel(id="ch", title="C", subscribers_count=1, created_at=NOW))
    session.flush()
    pending_at = NOW - timedelta(hours=10)
    matured_at = NOW - timedelta(hours=80)
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="pending-v",
            discovery_run_id="r1",
            discovered_at=pending_at,
            views_at_discovery=5,
            content_format="regular",
            qualification_state="passed",
        ),
    )
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="valid-v",
            discovery_run_id="r2",
            discovered_at=matured_at,
            views_at_discovery=100,
            content_format="regular",
            qualification_state="passed",
        ),
    )
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="missing-v",
            discovery_run_id="r3",
            discovered_at=matured_at,
            views_at_discovery=50,
            content_format="regular",
            qualification_state="passed",
        ),
    )
    session.add(
        Video(
            id="valid-v",
            title="V",
            views_count=1,
            likes_count=0,
            comments_count=0,
            published_at=matured_at - timedelta(days=5),
            duration_seconds=60,
            content_format=VideoFormat.MEDIUM,
            channel_id="ch",
        ),
    )
    target = matured_at + timedelta(hours=72)
    session.add(
        VideoSnapshot(
            video_id="valid-v",
            channel_id="ch",
            captured_at=target,
            source="t",
            run_id="snap",
            views=250,
        ),
    )
    session.commit()
    out = compute_keyword_outcome_maturity(session, now=NOW)
    assert out.pending_72h_count == 1
    assert out.matured_72h_count == 2
    assert out.valid_72h_outcome_count == 1
    assert out.missing_72h_outcome_count == 1


def test_upcoming_maturity_windows() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k")
    session.add(kw)
    session.flush()
    for vid, hours_until_mature in (("v6", 4), ("v24", 20), ("v48", 40)):
        discovered = NOW - timedelta(hours=72 - hours_until_mature)
        session.add(
            KeywordDiscoveryHit(
                keyword_id=kw.id,
                video_id=vid,
                discovery_run_id=f"r-{vid}",
                discovered_at=discovered,
                views_at_discovery=1,
                content_format="regular",
                qualification_state="passed",
            ),
        )
    session.commit()
    out = compute_keyword_outcome_maturity(session, now=NOW)
    assert out.matures_next_6h == 1
    assert out.matures_next_24h == 2
    assert out.matures_next_48h == 3


def test_no_breakout_or_keyword_performance_calls() -> None:
    session = _session()
    with patch("app.services.breakout_ranking_service.rank_breakout_v1") as br:
        with patch("app.services.keyword_performance_service.list_keyword_performance") as kp:
            build_operations_overview(session)
            br.assert_not_called()
            kp.assert_not_called()


def test_live_planner_off_avoids_overview() -> None:
    session = _session()
    with patch("app.services.operations_overview_service.get_monitoring_overview") as overview:
        build_operations_overview(session, include_live_monitoring_planner=False)
        overview.assert_not_called()


def test_bounded_recent_cycle_history() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k")
    session.add(kw)
    session.flush()
    for idx in range(5):
        session.add(
            KeywordScanRun(
                keyword_id=kw.id,
                discovery_run_id=f"run-{idx}",
                started_at=NOW - timedelta(hours=idx),
                finished_at=NOW - timedelta(hours=idx),
                status="ok",
                raw_candidates=1,
                unique_candidates=1,
                persisted_videos=0,
            ),
        )
    session.commit()
    overview = build_operations_overview(session, discovery_history_limit=3)
    assert len(overview.recent_cycles.discovery) == 3


def test_empty_db_response() -> None:
    session = _session()
    overview = build_operations_overview(session)
    assert overview.discovery.keywords_due_now == 0
    assert overview.snapshots.snapshots_last_24h == 0
    assert overview.keyword_outcomes.attributed_observation_count == 0


def test_secrets_redacted_in_discovery_error() -> None:
    session = _session()
    session.add(
        DiscoveryWorkerState(
            id=1,
            status="idle",
            last_error="failed api_key=AIzaSyDeadBeefTokenBearer secret=xyz",
        ),
    )
    session.commit()
    overview = build_operations_overview(session)
    err = overview.errors.discovery_last_cycle_error or ""
    assert "AIzaSyDeadBeefTokenBearer" not in err
    assert "api_key=" not in err.lower() or "[redacted]" in err.lower()


def main() -> None:
    tests = [
        test_keyword_due_now_with_null_next_scan_at,
        test_archived_keyword_excluded_from_due,
        test_due_next_1h_and_24h_buckets,
        test_discovery_cycle_grouping,
        test_monitoring_latest_cycle_mapping,
        test_snapshot_counts_and_latest,
        test_first_hit_dedupes_rescan_for_maturity,
        test_pending_and_matured_valid_missing,
        test_upcoming_maturity_windows,
        test_no_breakout_or_keyword_performance_calls,
        test_live_planner_off_avoids_overview,
        test_bounded_recent_cycle_history,
        test_empty_db_response,
        test_secrets_redacted_in_discovery_error,
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
    print("All operations overview tests passed.")


if __name__ == "__main__":
    main()
