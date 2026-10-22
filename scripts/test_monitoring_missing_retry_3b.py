"""Fix 3B — missing capture does not complete checkpoint; same video stays due."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.snapshot_collection_policy import (
    MONITORING_CAPTURE_SOURCE,
    build_capture_requests,
    plan_video_revisits,
)

UTC = timezone.utc


def test_missing_leaves_checkpoint_due_next_cycle() -> None:
    published = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
    now = published + timedelta(hours=25)
    plan = plan_video_revisits(
        video_id="YXodhWM0RiI",
        published_at=published,
        existing_snapshots=(),
        current_time=now,
    )
    assert plan.due_checkpoints, "24h checkpoint should be due/overdue at age 25h"
    cp24 = next(cp for cp in plan.checkpoints if cp.target_age_hours == 24)
    assert cp24.status in ("due", "overdue")

    requests = build_capture_requests(
        plan,
        requested_at=now,
        source=MONITORING_CAPTURE_SOURCE,
        run_id_prefix="monitoring_test_",
    )
    assert len(requests) >= 1
    assert requests[0].video_id == "YXodhWM0RiI"
    assert requests[0].checkpoint_age_hours == 24

    # Second cycle: still no successful snapshot → same checkpoint still due.
    plan2 = plan_video_revisits(
        video_id="YXodhWM0RiI",
        published_at=published,
        existing_snapshots=(),
        current_time=now + timedelta(minutes=15),
    )
    cp24b = next(cp for cp in plan2.checkpoints if cp.target_age_hours == 24)
    assert cp24b.status in ("due", "overdue")
    requests2 = build_capture_requests(
        plan2,
        requested_at=now + timedelta(minutes=15),
        source=MONITORING_CAPTURE_SOURCE,
        run_id_prefix="monitoring_test2_",
    )
    assert requests2[0].video_id == "YXodhWM0RiI"
    assert requests2[0].checkpoint_age_hours == 24


if __name__ == "__main__":
    test_missing_leaves_checkpoint_due_next_cycle()
    print("ok")
