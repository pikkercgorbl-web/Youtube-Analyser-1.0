"""Tests for keyword lifecycle calibration (Stage 1.20E)."""

from __future__ import annotations

import csv
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.models.orm import KeywordDiscoveryHit, KeywordScanRun, TargetKeyword
from app.services.keyword_lifecycle_calibration_service import (
    _streak_stats,
    build_calibration_report,
    build_scan_calibration_rows,
    maturity_group_for,
)
from app.services.keyword_scheduling_policy import LIFECYCLE_ACTIVE, LIFECYCLE_PROBATION, PROBATION_READY_SCAN_COUNT

UTC = timezone.utc


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_failed_scan_not_zero_yield() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k", lifecycle_status=LIFECYCLE_PROBATION)
    session.add(kw)
    session.flush()
    session.add(
        KeywordScanRun(
            keyword_id=kw.id,
            discovery_run_id="r1",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            status="failed",
            raw_candidates=0,
            persisted_videos=0,
        ),
    )
    session.commit()
    rows = build_scan_calibration_rows(session, [kw.id])
    assert len(rows) == 1
    assert rows[0].scan_failed is True
    assert rows[0].zero_new_video_yield is False


def test_successful_zero_new_is_zero_yield() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k2", lifecycle_status=LIFECYCLE_PROBATION)
    session.add(kw)
    session.flush()
    session.add(
        KeywordScanRun(
            keyword_id=kw.id,
            discovery_run_id="r2",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            status="ok",
            raw_candidates=5,
            persisted_videos=2,
        ),
    )
    session.commit()
    rows = build_scan_calibration_rows(session, [kw.id])
    assert rows[0].zero_new_video_yield is True
    assert rows[0].zero_raw_result is False


def test_zero_raw_vs_zero_new() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k3", lifecycle_status=LIFECYCLE_PROBATION)
    session.add(kw)
    session.flush()
    session.add(
        KeywordScanRun(
            keyword_id=kw.id,
            discovery_run_id="r3",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            status="ok",
            raw_candidates=0,
            persisted_videos=0,
        ),
    )
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="v",
            discovery_run_id="r3",
            discovered_at=datetime.now(UTC),
            video_existed_before_discovery=False,
        ),
    )
    session.commit()
    rows = build_scan_calibration_rows(session, [kw.id])
    assert rows[0].zero_raw_result is True
    assert rows[0].zero_new_video_yield is False


def test_streak_calculation() -> None:
    max_run, tail = _streak_stats([True, True, False, True])
    assert max_run == 2
    assert tail == 1


def test_maturity_groups() -> None:
    assert maturity_group_for(0) == "lt_3"
    assert maturity_group_for(3) == "3_5"
    assert maturity_group_for(7) == "6_10"
    assert maturity_group_for(11) == "gt_10"


def test_report_no_lifecycle_writes() -> None:
    session = _session()
    kw = TargetKeyword(keyword="stable", lifecycle_status=LIFECYCLE_PROBATION)
    session.add(kw)
    session.commit()
    before = session.scalar(select(func.count()).select_from(TargetKeyword))
    build_calibration_report(session, limit=10)
    after = session.scalar(select(func.count()).select_from(TargetKeyword))
    assert before == after


def test_strong_recommendations_near_zero() -> None:
    session = _session()
    kw = TargetKeyword(keyword="p", lifecycle_status=LIFECYCLE_PROBATION)
    session.add(kw)
    session.flush()
    for i in range(PROBATION_READY_SCAN_COUNT):
        session.add(
            KeywordScanRun(
                keyword_id=kw.id,
                discovery_run_id=f"s{i}",
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
                status="ok",
            ),
        )
    session.commit()
    report = build_calibration_report(session, include_breakout=False, include_delayed=False, limit=10)
    strong = {"promote_active", "move_weak", "archive_candidate", "restore_active"}
    assert sum(report.recommendation_counts.get(k, 0) for k in strong) == 0


def test_spearman_insufficient_sample() -> None:
    session = _session()
    session.add(TargetKeyword(keyword="solo", lifecycle_status=LIFECYCLE_ACTIVE))
    session.commit()
    report = build_calibration_report(session, include_breakout=False, include_delayed=False, limit=5)
    for assoc in report.associations:
        if assoc.n < 10:
            assert assoc.rho is None


def test_csv_export_deterministic_headers() -> None:
    from dataclasses import asdict

    session = _session()
    session.add(TargetKeyword(keyword="csv-k", lifecycle_status=LIFECYCLE_ACTIVE))
    session.commit()
    report = build_calibration_report(session, include_breakout=False, include_delayed=False, limit=5)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "keyword_calibration.csv"
        rows = [asdict(report.keyword_rows[0])] if report.keyword_rows else []
        with path.open("w", encoding="utf-8", newline="") as handle:
            if rows:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerow({k: rows[0][k] for k in rows[0]})
        text = path.read_text(encoding="utf-8")
        assert "keyword_id" in text.splitlines()[0]


def test_readiness_not_ready_by_default() -> None:
    session = _session()
    session.add(TargetKeyword(keyword="r", lifecycle_status=LIFECYCLE_PROBATION))
    session.commit()
    report = build_calibration_report(session, include_breakout=False, include_delayed=False, limit=5)
    assert any(r.readiness == "NOT_READY" for r in report.readiness)
    assert report.outcome_72h_coverage.get("calibration_status") == "CALIBRATION_NOT_READY"


def main() -> None:
    tests = [
        test_failed_scan_not_zero_yield,
        test_successful_zero_new_is_zero_yield,
        test_zero_raw_vs_zero_new,
        test_streak_calculation,
        test_maturity_groups,
        test_report_no_lifecycle_writes,
        test_strong_recommendations_near_zero,
        test_spearman_insufficient_sample,
        test_csv_export_deterministic_headers,
        test_readiness_not_ready_by_default,
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
    print("All keyword lifecycle calibration tests passed.")


if __name__ == "__main__":
    main()
