"""Tests for advisory lifecycle recommendations (Stage 1.20D)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.models.orm import KeywordDiscoveryHit, KeywordScanRun, TargetKeyword
from app.services.keyword_evidence_service import get_keyword_evidence
from app.services.keyword_lifecycle_recommendation_service import (
    evaluate_lifecycle_recommendation,
    get_lifecycle_recommendation,
    list_lifecycle_recommendations,
)
from app.services.keyword_scheduling_policy import (
    LIFECYCLE_ACTIVE,
    LIFECYCLE_ARCHIVED,
    LIFECYCLE_PROBATION,
    LIFECYCLE_WEAK,
    PROBATION_READY_SCAN_COUNT,
)

UTC = timezone.utc


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _add_ok_scans(session, keyword_id: int, n: int) -> None:
    for i in range(n):
        session.add(
            KeywordScanRun(
                keyword_id=keyword_id,
                discovery_run_id=f"run_{keyword_id}_{i}",
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
                status="ok",
            ),
        )


def test_probation_insufficient_scans() -> None:
    session = _session()
    kw = TargetKeyword(keyword="prob", lifecycle_status=LIFECYCLE_PROBATION, source_type="suggestion")
    session.add(kw)
    session.commit()
    _add_ok_scans(session, kw.id, PROBATION_READY_SCAN_COUNT - 1)
    session.commit()
    rec = get_lifecycle_recommendation(session, kw.id)
    assert rec is not None
    assert rec.recommendation == "insufficient_evidence"


def test_probation_preliminary_with_yield_not_promote() -> None:
    session = _session()
    kw = TargetKeyword(keyword="prob-yield", lifecycle_status=LIFECYCLE_PROBATION, source_type="suggestion")
    session.add(kw)
    session.flush()
    _add_ok_scans(session, kw.id, PROBATION_READY_SCAN_COUNT)
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="v1",
            discovery_run_id="d1",
            discovered_at=datetime.now(UTC),
            video_existed_before_discovery=False,
            persisted_for_monitoring=True,
        ),
    )
    session.commit()
    rec = get_lifecycle_recommendation(session, kw.id)
    assert rec is not None
    assert rec.recommendation == "preliminary_review"
    assert rec.calibration_required is True
    assert rec.recommendation != "promote_active"


def test_probation_preliminary_zero_yield() -> None:
    session = _session()
    kw = TargetKeyword(keyword="prob-zero", lifecycle_status=LIFECYCLE_PROBATION, source_type="suggestion")
    session.add(kw)
    session.commit()
    _add_ok_scans(session, kw.id, PROBATION_READY_SCAN_COUNT)
    session.commit()
    rec = get_lifecycle_recommendation(session, kw.id)
    assert rec is not None
    assert rec.recommendation == "preliminary_review"
    assert rec.calibration_required is True
    assert rec.recommendation != "move_weak"


def test_active_keep_calibration_required() -> None:
    session = _session()
    kw = TargetKeyword(keyword="act", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    session.add(kw)
    session.commit()
    rec = get_lifecycle_recommendation(session, kw.id)
    assert rec is not None
    assert rec.recommendation == "keep"
    assert rec.calibration_required is True


def test_archived_keep_no_restore() -> None:
    session = _session()
    kw = TargetKeyword(keyword="old", lifecycle_status=LIFECYCLE_ARCHIVED, source_type="seed")
    session.add(kw)
    session.commit()
    rec = get_lifecycle_recommendation(session, kw.id)
    assert rec is not None
    assert rec.recommendation == "keep"
    assert rec.recommendation != "restore_active"


def test_weak_keep_not_promote() -> None:
    session = _session()
    kw = TargetKeyword(keyword="weak", lifecycle_status=LIFECYCLE_WEAK, source_type="suggestion")
    session.add(kw)
    session.commit()
    rec = get_lifecycle_recommendation(session, kw.id)
    assert rec is not None
    assert rec.recommendation == "keep"
    assert rec.recommendation != "promote_active"


def test_list_batch() -> None:
    session = _session()
    session.add_all(
        [
            TargetKeyword(keyword="a", lifecycle_status=LIFECYCLE_PROBATION),
            TargetKeyword(keyword="b", lifecycle_status=LIFECYCLE_ACTIVE),
        ],
    )
    session.commit()
    result = list_lifecycle_recommendations(session, limit=10)
    assert len(result.items) == 2


def test_no_strong_actions_by_default() -> None:
    session = _session()
    for status in (LIFECYCLE_PROBATION, LIFECYCLE_ACTIVE, LIFECYCLE_WEAK, LIFECYCLE_ARCHIVED):
        kw = TargetKeyword(keyword=f"k-{status}", lifecycle_status=status)
        session.add(kw)
        session.flush()
        _add_ok_scans(session, kw.id, 5)
    session.commit()
    result = list_lifecycle_recommendations(session, limit=20)
    strong = {"promote_active", "move_weak", "archive_candidate", "restore_active"}
    for item in result.items:
        assert item.recommendation not in strong


def main() -> None:
    tests = [
        test_probation_insufficient_scans,
        test_probation_preliminary_with_yield_not_promote,
        test_probation_preliminary_zero_yield,
        test_active_keep_calibration_required,
        test_archived_keep_no_restore,
        test_weak_keep_not_promote,
        test_list_batch,
        test_no_strong_actions_by_default,
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
    print("All lifecycle recommendation tests passed.")


if __name__ == "__main__":
    main()
