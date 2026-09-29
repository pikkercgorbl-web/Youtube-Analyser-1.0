"""Tests for snapshot collection / revisit policy (Stage 1.12B)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.snapshot_collection_policy import (
    ExistingSnapshot,
    SnapshotCollectionPolicy,
    VideoRevisitInput,
    build_capture_requests,
    checkpoint_match_window,
    checkpoint_priority_key,
    plan_revisits_for_videos,
    plan_video_revisits,
)

UTC = timezone.utc
PUB = datetime(2026, 9, 14, 8, 0, tzinfo=UTC)


def _plan(
    *,
    age_hours: float,
    snapshots: list[ExistingSnapshot] | None = None,
    **kwargs: object,
) -> object:
    current = PUB + timedelta(hours=age_hours)
    return plan_video_revisits(
        video_id="v1",
        published_at=PUB,
        existing_snapshots=snapshots or [],
        current_time=current,
        content_format="regular",
        **kwargs,  # type: ignore[arg-type]
    )


def test_before_6h_all_pending() -> None:
    plan = _plan(age_hours=5.0)
    assert all(cp.status == "pending" for cp in plan.checkpoints)
    assert plan.due_checkpoints == ()


def test_at_6h_no_snapshot_due() -> None:
    plan = _plan(age_hours=6.0)
    cp6 = plan.checkpoints[0]
    assert cp6.target_age_hours == 6
    assert cp6.status == "due"
    assert cp6.recommended_action == "capture_now"


def test_acceptable_6h_snapshot_completed() -> None:
    plan = _plan(age_hours=6.5, snapshots=[ExistingSnapshot(age_hours=6.2, snapshot_id=1)])
    assert plan.checkpoints[0].status == "completed"


def test_snapshot_outside_tolerance_not_complete() -> None:
    plan = _plan(age_hours=7.5, snapshots=[ExistingSnapshot(age_hours=4.0, snapshot_id=1)])
    assert plan.checkpoints[0].status != "completed"
    assert plan.checkpoints[0].status in ("due", "overdue")


def test_24h_missed_age_30_overdue() -> None:
    plan = _plan(age_hours=30.0)
    cp24 = next(cp for cp in plan.checkpoints if cp.target_age_hours == 24)
    assert cp24.status == "overdue"


def test_overdue_capture_uses_real_age() -> None:
    plan = _plan(age_hours=30.0)
    requests = build_capture_requests(plan, requested_at=PUB + timedelta(hours=30), source="test")
    cp24 = next(r for r in requests if r.checkpoint_age_hours == 24)
    assert cp24.current_age_hours == 30.0
    assert cp24.checkpoint_age_hours == 24


def test_expired_checkpoint() -> None:
    plan = _plan(age_hours=40.0)
    cp24 = next(cp for cp in plan.checkpoints if cp.target_age_hours == 24)
    assert cp24.status == "expired"
    assert cp24.recommended_action == "none"


def test_expired_not_in_due_list() -> None:
    plan = _plan(age_hours=40.0)
    assert all(cp.target_age_hours != 24 for cp in plan.due_checkpoints)


def test_completed_not_scheduled_again() -> None:
    snaps = [ExistingSnapshot(age_hours=6.0, snapshot_id=1)]
    plan = _plan(age_hours=8.0, snapshots=snaps)
    assert plan.checkpoints[0].status == "completed"
    assert 6 not in [cp.target_age_hours for cp in plan.due_checkpoints]


def test_one_snapshot_one_checkpoint() -> None:
    plan = _plan(age_hours=20.0, snapshots=[ExistingSnapshot(age_hours=12.0, snapshot_id=1)])
    completed = [cp for cp in plan.checkpoints if cp.status == "completed"]
    assert len(completed) == 1
    assert completed[0].target_age_hours == 12


def test_short_not_eligible() -> None:
    plan = _plan(age_hours=10.0, is_short=True)
    assert plan.monitoring_status == "ineligible"
    assert plan.checkpoints == ()


def test_live_not_eligible() -> None:
    plan = _plan(age_hours=10.0, is_live=True)
    assert plan.monitoring_status == "ineligible"


def test_invalid_published_at_stops() -> None:
    plan = plan_video_revisits(
        video_id="v1",
        published_at=None,
        existing_snapshots=[],
        current_time=PUB + timedelta(hours=10),
        content_format="regular",
    )
    assert plan.monitoring_status == "ineligible"
    assert plan.stop_reason == "missing_published_at"


def test_72h_completed_monitoring_stopped() -> None:
    snaps = [ExistingSnapshot(age_hours=72.0, snapshot_id=9)]
    plan = _plan(age_hours=80.0, snapshots=snaps)
    assert plan.monitoring_status == "stopped"
    assert plan.stop_reason == "final_checkpoint_completed"


def test_72h_expired_monitoring_stopped() -> None:
    plan = _plan(age_hours=120.0)
    cp72 = next(cp for cp in plan.checkpoints if cp.target_age_hours == 72)
    assert cp72.status == "expired"
    assert plan.monitoring_status == "stopped"
    assert plan.stop_reason == "final_checkpoint_expired"


def test_deterministic_priority_ordering() -> None:
    plan = _plan(age_hours=14.0)
    requests = build_capture_requests(plan, requested_at=PUB + timedelta(hours=14), source="test")
    targets = [r.checkpoint_age_hours for r in requests]
    assert targets == sorted(
        targets,
        key=lambda target: next(
            (
                checkpoint_priority_key(plan, cp)
                for cp in plan.due_checkpoints
                if cp.target_age_hours == target
            ),
            (999, 999, target),
        ),
    )


def test_batch_matches_single() -> None:
    current = PUB + timedelta(hours=30)
    item = VideoRevisitInput(
        video_id="v1",
        published_at=PUB,
        content_format="regular",
    )
    single = plan_video_revisits(
        video_id="v1",
        published_at=PUB,
        existing_snapshots=[],
        current_time=current,
        content_format="regular",
    )
    batch = plan_revisits_for_videos(
        [item],
        snapshots_by_video_id={"v1": []},
        current_time=current,
    )[0]
    assert batch.checkpoints == single.checkpoints
    assert batch.due_checkpoints == single.due_checkpoints


def test_match_window_documented_6h() -> None:
    lo, hi = checkpoint_match_window(6, SnapshotCollectionPolicy())
    assert lo == 5.0
    assert hi == 7.0


def main() -> None:
    tests = [
        test_before_6h_all_pending,
        test_at_6h_no_snapshot_due,
        test_acceptable_6h_snapshot_completed,
        test_snapshot_outside_tolerance_not_complete,
        test_24h_missed_age_30_overdue,
        test_overdue_capture_uses_real_age,
        test_expired_checkpoint,
        test_expired_not_in_due_list,
        test_completed_not_scheduled_again,
        test_one_snapshot_one_checkpoint,
        test_short_not_eligible,
        test_live_not_eligible,
        test_invalid_published_at_stops,
        test_72h_completed_monitoring_stopped,
        test_72h_expired_monitoring_stopped,
        test_deterministic_priority_ordering,
        test_batch_matches_single,
        test_match_window_documented_6h,
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
        raise SystemExit(f"{failed} test(s) failed")
    print("All snapshot collection policy tests passed.")


if __name__ == "__main__":
    main()
