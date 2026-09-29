"""Tests for keyword lifecycle and scheduling (Stage 1.16B)."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.models.orm import KeywordLifecycleEvent, KeywordScanRun, TargetKeyword
from app.services.discovery_keyword_selection import select_discovery_keywords
from app.services.keyword_lifecycle_service import (
    apply_post_scan_schedule,
    create_keyword,
    find_keyword_by_normalized,
    set_keyword_lifecycle,
)
from app.services.keyword_schedule_state import get_keyword_schedule_state, is_keyword_due
from app.services.keyword_scheduling_policy import (
    DEFAULT_SCHEDULING_POLICY,
    LIFECYCLE_ACTIVE,
    LIFECYCLE_ARCHIVED,
    LIFECYCLE_PROBATION,
    LIFECYCLE_WEAK,
)
from app.services.metrics import ensure_utc
from app.services.target_keywords_service import TargetKeywordsService

UTC = timezone.utc


def _engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


def _session():
    return sessionmaker(bind=_engine())()


def _now() -> datetime:
    return datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


def test_existing_keyword_defaults_active_due() -> None:
    session = _session()
    row = TargetKeyword(keyword="seed", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    session.add(row)
    session.commit()
    assert row.lifecycle_status == LIFECYCLE_ACTIVE
    assert is_keyword_due(row, now=_now())


def test_intervals_per_lifecycle() -> None:
    policy = DEFAULT_SCHEDULING_POLICY
    assert policy.interval_seconds_for(LIFECYCLE_PROBATION) == 6 * 3600
    assert policy.interval_seconds_for(LIFECYCLE_ACTIVE) == 24 * 3600
    assert policy.interval_seconds_for(LIFECYCLE_WEAK) == 72 * 3600
    assert policy.interval_seconds_for(LIFECYCLE_ARCHIVED) is None


def test_archived_never_selected() -> None:
    session = _session()
    session.add(
        TargetKeyword(
            keyword="gone",
            lifecycle_status=LIFECYCLE_ARCHIVED,
            next_scan_at=_now() - timedelta(days=1),
        ),
    )
    session.commit()
    assert select_discovery_keywords(session, now=_now()) == []


def test_overdue_weak_beats_fresh_active() -> None:
    session = _session()
    now = _now()
    session.add_all(
        [
            TargetKeyword(
                keyword="weak",
                lifecycle_status=LIFECYCLE_WEAK,
                next_scan_at=now - timedelta(days=5),
            ),
            TargetKeyword(
                keyword="active",
                lifecycle_status=LIFECYCLE_ACTIVE,
                next_scan_at=now - timedelta(minutes=2),
            ),
        ],
    )
    session.commit()
    batch = select_discovery_keywords(session, batch_size=1, now=now)
    assert batch[0].keyword == "weak"


def test_successful_scan_updates_next_scan_at() -> None:
    session = _session()
    finished = _now()
    kw = TargetKeyword(
        keyword="k",
        lifecycle_status=LIFECYCLE_ACTIVE,
        next_scan_at=finished - timedelta(hours=1),
    )
    session.add(kw)
    session.commit()
    apply_post_scan_schedule(session, kw.id, finished_at=finished, scan_succeeded=True)
    session.commit()
    session.refresh(kw)
    assert ensure_utc(kw.last_checked) == ensure_utc(finished)
    assert ensure_utc(kw.next_scan_at) == ensure_utc(finished + timedelta(hours=24))


def test_failed_scan_retry_delay() -> None:
    session = _session()
    finished = _now()
    kw = TargetKeyword(keyword="k", lifecycle_status=LIFECYCLE_ACTIVE, next_scan_at=finished)
    session.add(kw)
    session.commit()
    apply_post_scan_schedule(session, kw.id, finished_at=finished, scan_succeeded=False)
    session.refresh(kw)
    assert ensure_utc(kw.next_scan_at) == ensure_utc(finished + timedelta(hours=2))


def test_lifecycle_transition_stores_event() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    session.add(kw)
    session.commit()
    record = set_keyword_lifecycle(session, kw.id, LIFECYCLE_WEAK, "manual review", now=_now())
    session.commit()
    events = session.scalars(select(KeywordLifecycleEvent)).all()
    assert len(events) == 1
    assert events[0].to_status == LIFECYCLE_WEAK
    assert record.status_reason == "manual review"


def test_archived_to_active_immediate_due() -> None:
    session = _session()
    kw = TargetKeyword(
        keyword="k",
        lifecycle_status=LIFECYCLE_ARCHIVED,
        next_scan_at=None,
    )
    session.add(kw)
    session.commit()
    now = _now()
    set_keyword_lifecycle(session, kw.id, LIFECYCLE_ACTIVE, "reactivate", now=now)
    session.refresh(kw)
    assert ensure_utc(kw.next_scan_at) == ensure_utc(now)
    assert is_keyword_due(kw, now=now)


def test_normalized_duplicate_reused() -> None:
    session = _session()
    first = create_keyword(session, "AI tools", lifecycle_status=LIFECYCLE_PROBATION)
    second = create_keyword(session, "  ai   tools ", lifecycle_status=LIFECYCLE_PROBATION)
    assert first.id == second.id
    assert find_keyword_by_normalized(session, "AI TOOLS") is not None


def test_probation_ready_hint_no_auto_promote() -> None:
    session = _session()
    kw = create_keyword(session, "new", lifecycle_status=LIFECYCLE_PROBATION)
    for i in range(3):
        session.add(
            KeywordScanRun(
                keyword_id=kw.id,
                discovery_run_id=f"run{i}",
                started_at=_now(),
                finished_at=_now(),
                status="ok",
            ),
        )
    session.commit()
    state = get_keyword_schedule_state(session, kw.id)
    assert state is not None
    assert state.probation_ready_for_review is True
    assert state.scheduling_hint == "probation_ready_for_review"
    assert kw.lifecycle_status == LIFECYCLE_PROBATION


def test_no_auto_weak_from_performance() -> None:
    text = (ROOT / "app" / "services" / "keyword_lifecycle_service.py").read_text(encoding="utf-8")
    assert "duplicate_rate" not in text
    assert "qualification_pass" not in text.lower() or "PROBATION_READY" in text


def test_discovery_worker_rotation_still_works() -> None:
    session = _session()
    now = _now()
    for i in range(3):
        session.add(
            TargetKeyword(
                keyword=f"k{i}",
                lifecycle_status=LIFECYCLE_ACTIVE,
                next_scan_at=now - timedelta(hours=i + 1),
            ),
        )
    session.commit()
    svc = TargetKeywordsService()
    batch1 = svc.pick_due_batch(session, batch_size=2, )
    assert len(batch1) == 2


def _run_script(name: str) -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / name)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)


def test_regressions() -> None:
    _run_script("test_discovery_cycle.py")
    _run_script("test_discovery_worker.py")
    _run_script("test_keyword_performance.py")
    _run_script("test_monitoring_worker.py")
    _run_script("test_monitoring_api.py")


def main() -> None:
    tests = [
        test_existing_keyword_defaults_active_due,
        test_intervals_per_lifecycle,
        test_archived_never_selected,
        test_overdue_weak_beats_fresh_active,
        test_successful_scan_updates_next_scan_at,
        test_failed_scan_retry_delay,
        test_lifecycle_transition_stores_event,
        test_archived_to_active_immediate_due,
        test_normalized_duplicate_reused,
        test_probation_ready_hint_no_auto_promote,
        test_no_auto_weak_from_performance,
        test_discovery_worker_rotation_still_works,
        test_regressions,
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
    print("All keyword lifecycle scheduling tests passed.")


if __name__ == "__main__":
    main()
