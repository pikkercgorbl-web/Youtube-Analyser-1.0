"""Checkpoint matching uses captured_at vs corrected published_at."""

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
    find_matching_snapshot,
)

POLICY = SnapshotCollectionPolicy()

UTC = timezone.utc


def test_rematch_uses_captured_at_with_new_published_at() -> None:
    published_wrong = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
    published_fixed = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    captured = published_fixed + timedelta(hours=24)
    snap = ExistingSnapshot(snapshot_id=1, captured_at=captured, age_hours=2.0)
    matched = find_matching_snapshot([snap], 24, POLICY, published_at=published_wrong)
    assert matched is None
    matched_fixed = find_matching_snapshot([snap], 24, POLICY, published_at=published_fixed)
    assert matched_fixed is not None


def main() -> None:
    test_rematch_uses_captured_at_with_new_published_at()
    print("OK snapshot published_at rematch")


if __name__ == "__main__":
    main()
