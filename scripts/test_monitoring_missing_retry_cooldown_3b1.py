"""Fix 3B.1 — missing retry cooldown uses outcomes table; dry-run never persists."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.models.orm import MonitoringCaptureOutcome
from app.services.metrics import ensure_utc
from app.services.monitoring_missing_retry import (
    filter_capture_requests_by_missing_cooldown,
    missing_capture_retry_interval_seconds,
)
from app.services.monitoring_tier_budget_policy import (
    CaptureRequestBudgetContext,
    MonitoringTier,
)
from app.services.snapshot_collection_policy import SnapshotCaptureRequest, SnapshotCollectionPolicy

UTC = timezone.utc


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _request(video_id: str, cp: int, age: float) -> SnapshotCaptureRequest:
    now = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
    return SnapshotCaptureRequest(
        video_id=video_id,
        channel_id="ch",
        checkpoint_age_hours=cp,
        reason="overdue",
        requested_at=now,
        current_age_hours=age,
        source="monitoring_worker",
        run_id=f"run:{video_id}:cp{cp}",
    )


def _ctx() -> CaptureRequestBudgetContext:
    req = _request("x", 24, 25.0)
    return CaptureRequestBudgetContext(
        request=req,
        tier=MonitoringTier.A,
        raw_vph=1.0,
        is_overdue=True,
        time_to_checkpoint_expiry_hours=10.0,
        time_to_momentum_vph_deadline_hours=None,
    )


def test_interval_24h_uses_match_tolerance() -> None:
    policy = SnapshotCollectionPolicy()
    seconds = missing_capture_retry_interval_seconds(
        checkpoint_age_hours=24,
        current_age_hours=25.0,
        policy=policy,
        worker_interval_seconds=900,
    )
    tolerance_h = 3.6
    assert seconds >= tolerance_h * 3600 - 1


def test_second_cycle_suppressed_after_missing() -> None:
    session = _session()
    now = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
    session.add(
        MonitoringCaptureOutcome(
            monitoring_run_id="m1",
            video_id="vidA",
            checkpoint_age_hours=24,
            capture_run_id="cap1",
            attempted_at=now - timedelta(minutes=10),
            outcome="missing",
            reason_code="yt_items_absent",
        ),
    )
    session.commit()
    req = _request("vidA", 24, 25.0)
    ctx = CaptureRequestBudgetContext(
        request=req,
        tier=MonitoringTier.A,
        raw_vph=1.0,
        is_overdue=True,
        time_to_checkpoint_expiry_hours=11.0,
        time_to_momentum_vph_deadline_hours=None,
    )
    kept, _, suppressed = filter_capture_requests_by_missing_cooldown(
        session,
        requests=[req],
        contexts=[ctx],
        now=now,
    )
    assert suppressed == 1
    assert kept == []


def test_after_cooldown_request_allowed() -> None:
    session = _session()
    now = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
    policy = SnapshotCollectionPolicy()
    interval_s = missing_capture_retry_interval_seconds(
        checkpoint_age_hours=24,
        current_age_hours=25.0,
        policy=policy,
    )
    session.add(
        MonitoringCaptureOutcome(
            monitoring_run_id="m1",
            video_id="vidA",
            checkpoint_age_hours=24,
            capture_run_id="cap1",
            attempted_at=now - timedelta(seconds=interval_s + 60),
            outcome="missing",
            reason_code="yt_items_absent",
        ),
    )
    session.commit()
    req = _request("vidA", 24, 25.0)
    ctx = CaptureRequestBudgetContext(
        request=req,
        tier=MonitoringTier.A,
        raw_vph=1.0,
        is_overdue=True,
        time_to_checkpoint_expiry_hours=11.0,
        time_to_momentum_vph_deadline_hours=None,
    )
    kept, _, suppressed = filter_capture_requests_by_missing_cooldown(
        session,
        requests=[req],
        contexts=[ctx],
        now=now,
    )
    assert suppressed == 0
    assert len(kept) == 1


def test_other_video_and_checkpoint_not_blocked() -> None:
    session = _session()
    now = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
    session.add(
        MonitoringCaptureOutcome(
            monitoring_run_id="m1",
            video_id="vidA",
            checkpoint_age_hours=24,
            capture_run_id="cap1",
            attempted_at=now - timedelta(minutes=5),
            outcome="missing",
            reason_code="yt_items_absent",
        ),
    )
    session.commit()
    req_b = _request("vidB", 24, 25.0)
    req_a48 = _request("vidA", 48, 49.0)
    ctx_b = CaptureRequestBudgetContext(
        request=req_b,
        tier=MonitoringTier.A,
        raw_vph=1.0,
        is_overdue=True,
        time_to_checkpoint_expiry_hours=11.0,
        time_to_momentum_vph_deadline_hours=None,
    )
    ctx_a48 = CaptureRequestBudgetContext(
        request=req_a48,
        tier=MonitoringTier.A,
        raw_vph=1.0,
        is_overdue=True,
        time_to_checkpoint_expiry_hours=11.0,
        time_to_momentum_vph_deadline_hours=None,
    )
    kept, _, suppressed = filter_capture_requests_by_missing_cooldown(
        session,
        requests=[req_b, req_a48],
        contexts=[ctx_b, ctx_a48],
        now=now,
    )
    assert suppressed == 0
    assert len(kept) == 2


def test_fetch_failed_does_not_suppress() -> None:
    session = _session()
    now = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
    session.add(
        MonitoringCaptureOutcome(
            monitoring_run_id="m1",
            video_id="vidA",
            checkpoint_age_hours=24,
            capture_run_id="cap1",
            attempted_at=now - timedelta(minutes=5),
            outcome="fetch_failed",
            reason_code="batch_fetch_failed",
        ),
    )
    session.commit()
    req = _request("vidA", 24, 25.0)
    ctx = _ctx()
    ctx = CaptureRequestBudgetContext(
        request=req,
        tier=MonitoringTier.A,
        raw_vph=1.0,
        is_overdue=True,
        time_to_checkpoint_expiry_hours=11.0,
        time_to_momentum_vph_deadline_hours=None,
    )
    kept, _, suppressed = filter_capture_requests_by_missing_cooldown(
        session,
        requests=[req],
        contexts=[ctx],
        now=now,
    )
    assert suppressed == 0
    assert len(kept) == 1


if __name__ == "__main__":
    test_interval_24h_uses_match_tolerance()
    test_second_cycle_suppressed_after_missing()
    test_after_cooldown_request_allowed()
    test_other_video_and_checkpoint_not_blocked()
    test_fetch_failed_does_not_suppress()
    print("ok")
