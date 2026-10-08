"""Late overdue checkpoint capture stops replanning without age-aligned completion."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.channel_momentum_age_vph import select_age_aligned_measurement
from app.models.orm import VideoSnapshot
from app.services.snapshot_collection_policy import (
    ExistingSnapshot,
    build_capture_requests,
    find_matching_snapshot,
    plan_video_revisits,
    snapshot_fulfills_checkpoint_late,
    SnapshotCollectionPolicy,
)

UTC = timezone.utc
PUB = datetime(2026, 9, 14, 8, 0, tzinfo=UTC)
POLICY = SnapshotCollectionPolicy()


def _late_snap(
    *,
    cp: int,
    age: float,
    snap_id: int,
    reason: str = "overdue",
    fetch_status: str = "ok",
    source: str = "monitoring_worker",
) -> ExistingSnapshot:
    return ExistingSnapshot(
        snapshot_id=snap_id,
        age_hours=age,
        captured_at=PUB + timedelta(hours=age),
        source=source,
        fetch_status=fetch_status,
        target_checkpoint_hours=cp,
        capture_reason=reason,
    )


def test_late_cp24_not_selected_again() -> None:
    snaps = [_late_snap(cp=24, age=32.0, snap_id=101)]
    plan = plan_video_revisits(
        video_id="v1",
        published_at=PUB,
        existing_snapshots=snaps,
        current_time=PUB + timedelta(hours=33),
        content_format="regular",
    )
    cp24 = next(cp for cp in plan.checkpoints if cp.target_age_hours == 24)
    assert cp24.status == "fulfilled_late"
    assert 24 not in [c.target_age_hours for c in plan.due_checkpoints]
    requests = build_capture_requests(plan, requested_at=PUB + timedelta(hours=33), source="monitoring_worker")
    assert all(r.checkpoint_age_hours != 24 for r in requests)


def test_late_cp6_not_selected_again() -> None:
    snaps = [_late_snap(cp=6, age=10.0, snap_id=102)]
    plan = plan_video_revisits(
        video_id="v1",
        published_at=PUB,
        existing_snapshots=snaps,
        current_time=PUB + timedelta(hours=11),
        content_format="regular",
    )
    cp6 = next(cp for cp in plan.checkpoints if cp.target_age_hours == 6)
    assert cp6.status == "fulfilled_late"
    assert 6 not in [c.target_age_hours for c in plan.due_checkpoints]


def test_failed_fetch_allows_repeat() -> None:
    snaps = [_late_snap(cp=24, age=32.0, snap_id=103, fetch_status="missing")]
    plan = plan_video_revisits(
        video_id="v1",
        published_at=PUB,
        existing_snapshots=snaps,
        current_time=PUB + timedelta(hours=33),
        content_format="regular",
    )
    cp24 = next(cp for cp in plan.checkpoints if cp.target_age_hours == 24)
    assert cp24.status == "overdue"


def test_other_checkpoint_still_due() -> None:
    snaps = [_late_snap(cp=24, age=32.0, snap_id=104)]
    plan = plan_video_revisits(
        video_id="v1",
        published_at=PUB,
        existing_snapshots=snaps,
        current_time=PUB + timedelta(hours=33),
        content_format="regular",
    )
    cp48 = next(cp for cp in plan.checkpoints if cp.target_age_hours == 48)
    assert cp48.status in ("due", "overdue", "pending")


def test_late_snapshot_not_momentum_age_aligned() -> None:
    pub = datetime(2026, 10, 6, 5, 0, 38, tzinfo=UTC)
    captured = pub + timedelta(hours=32.4)
    snap = VideoSnapshot(
        id=1,
        video_id="yVaPgwNlfLo",
        channel_id="ch",
        captured_at=captured,
        published_at=pub,
        age_hours=32.4,
        views=1000,
        source="monitoring_worker",
        run_id="run:1",
        fetch_status="ok",
        raw_metadata={"checkpoint_age_hours": 24, "capture_reason": "overdue"},
    )
    assert select_age_aligned_measurement(
        video_id="yVaPgwNlfLo",
        published_at=pub,
        snapshots=[snap],
        horizon_hours=24,
        tolerance_hours=6,
    ) is None


def test_published_at_rematch_age_aligned_still_wins() -> None:
    published_fixed = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    captured = published_fixed + timedelta(hours=24)
    aligned = ExistingSnapshot(snapshot_id=1, captured_at=captured, age_hours=24.0)
    assert find_matching_snapshot([aligned], 24, POLICY, published_at=published_fixed) is not None


def test_published_at_rematch_late_metadata_still_fulfills() -> None:
    published_fixed = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    captured = published_fixed + timedelta(hours=32)
    late = ExistingSnapshot(
        snapshot_id=2,
        captured_at=captured,
        age_hours=32.0,
        source="monitoring_worker",
        fetch_status="ok",
        target_checkpoint_hours=24,
        capture_reason="overdue",
    )
    assert snapshot_fulfills_checkpoint_late(late, 24)
    plan = plan_video_revisits(
        video_id="v1",
        published_at=published_fixed,
        existing_snapshots=[late],
        current_time=published_fixed + timedelta(hours=33),
        content_format="regular",
    )
    cp24 = next(cp for cp in plan.checkpoints if cp.target_age_hours == 24)
    assert cp24.status == "fulfilled_late"


def test_age_aligned_beats_late_for_same_checkpoint() -> None:
    aligned = ExistingSnapshot(snapshot_id=1, age_hours=24.0, captured_at=PUB + timedelta(hours=24))
    late = _late_snap(cp=24, age=32.0, snap_id=2)
    plan = plan_video_revisits(
        video_id="v1",
        published_at=PUB,
        existing_snapshots=[late, aligned],
        current_time=PUB + timedelta(hours=33),
        content_format="regular",
    )
    cp24 = next(cp for cp in plan.checkpoints if cp.target_age_hours == 24)
    assert cp24.status == "completed"


def main() -> None:
    tests = [
        test_late_cp24_not_selected_again,
        test_late_cp6_not_selected_again,
        test_failed_fetch_allows_repeat,
        test_other_checkpoint_still_due,
        test_late_snapshot_not_momentum_age_aligned,
        test_published_at_rematch_age_aligned_still_wins,
        test_published_at_rematch_late_metadata_still_fulfills,
        test_age_aligned_beats_late_for_same_checkpoint,
    ]
    for fn in tests:
        fn()
        print(f"OK {fn.__name__}")
    print(f"All {len(tests)} late checkpoint tests passed.")


if __name__ == "__main__":
    main()
