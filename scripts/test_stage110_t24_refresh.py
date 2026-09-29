"""Tests for Stage 1.10C T24 refresh (frozen cohort)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.youtube.client import YouTubeVideoDetails
from app.services.radar_stage110_t24_refresh import (
    T48_CHECKPOINT,
    T72_CHECKPOINT,
    build_stage110_refresh_record,
    verify_frozen_artifacts,
    verify_refresh_output,
)

ARTIFACTS = ROOT / "artifacts"
FREEZE = ARTIFACTS / "cohort_T0_stage110_20260914_141029_freeze.json"


def test_frozen_hashes_and_sample_count() -> None:
    verified = verify_frozen_artifacts(artifacts_dir=ARTIFACTS, freeze_path=FREEZE)
    assert len(verified["sample_rows"]) == 500


def test_baseline_preserved_in_refresh_record() -> None:
    row = verified_row = verify_frozen_artifacts(artifacts_dir=ARTIFACTS)["sample_rows"][0]
    snap = datetime(2026, 9, 15, 14, 10, 29, tzinfo=timezone.utc)
    t0_ref = datetime(2026, 9, 14, 14, 10, 29, tzinfo=timezone.utc)
    details = YouTubeVideoDetails(
        video_id=row["video_id"],
        channel_id=row["channel_id"],
        title="Current",
        published_at=datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc),
        views_count=int(row["t0_views"]) + 100,
        likes_count=1,
        comments_count=0,
        duration_seconds=600,
    )
    out = build_stage110_refresh_record(
        row,
        snapshot_at=snap,
        t0_reference_at=t0_ref,
        actual_elapsed_hours=24.0,
        details=details,
        fetch_status="refreshed",
    )
    assert out["video_id"] == row["video_id"]
    assert out["vph_at_t0"] == row["vph_at_t0"]
    assert out["channel_median_views"] == row["channel_median_views"]
    assert out["fetch_status"] == "refreshed"
    assert out["actual_elapsed_hours"] == 24.0
    assert out["target_checkpoint_hours"] == 24
    assert "keyword_score" not in out


def test_missing_no_fake_views() -> None:
    row = verify_frozen_artifacts(artifacts_dir=ARTIFACTS)["sample_rows"][1]
    out = build_stage110_refresh_record(
        row,
        snapshot_at=datetime.now(timezone.utc),
        t0_reference_at=datetime(2026, 9, 14, 14, 10, 29, tzinfo=timezone.utc),
        actual_elapsed_hours=25.0,
        details=None,
        fetch_status="missing",
    )
    assert out["views_current"] is None
    assert out["fetch_status"] == "missing"


def test_t72_checkpoint_metadata() -> None:
    row = verify_frozen_artifacts(artifacts_dir=ARTIFACTS)["sample_rows"][0]
    out = build_stage110_refresh_record(
        row,
        snapshot_at=datetime(2026, 9, 17, 14, 10, 29, tzinfo=timezone.utc),
        t0_reference_at=datetime(2026, 9, 14, 14, 10, 29, tzinfo=timezone.utc),
        actual_elapsed_hours=72.0,
        details=None,
        fetch_status="missing",
        checkpoint=T72_CHECKPOINT,
    )
    assert out["checkpoint_label"] == "T72"
    assert out["target_checkpoint_hours"] == 72
    assert out["schema_version"] == "1.10C_T72"


def test_t48_checkpoint_metadata() -> None:
    row = verify_frozen_artifacts(artifacts_dir=ARTIFACTS)["sample_rows"][0]
    out = build_stage110_refresh_record(
        row,
        snapshot_at=datetime(2026, 9, 16, 14, 10, 29, tzinfo=timezone.utc),
        t0_reference_at=datetime(2026, 9, 14, 14, 10, 29, tzinfo=timezone.utc),
        actual_elapsed_hours=48.01,
        details=None,
        fetch_status="missing",
        checkpoint=T48_CHECKPOINT,
    )
    assert out["checkpoint_label"] == "T48"
    assert out["target_checkpoint_hours"] == 48
    assert out["schema_version"] == "1.10C_T48"


def test_output_invariants_mock() -> None:
    sample = verify_frozen_artifacts(artifacts_dir=ARTIFACTS)["sample_rows"][:3]
    outputs = []
    for row in sample:
        outputs.append(
            build_stage110_refresh_record(
                row,
                snapshot_at=datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc),
                t0_reference_at=datetime(2026, 9, 14, 14, 10, 29, tzinfo=timezone.utc),
                actual_elapsed_hours=24.8,
                details=None,
                fetch_status="missing",
            ),
        )
    inv = verify_refresh_output(
        sample_rows=sample,
        output_records=outputs,
        counts={"refreshed": 0, "missing": 3, "failed": 0},
    )
    assert inv["baseline_fields_unchanged"]
    assert inv["no_fake_zero_views_on_missing"]


def main() -> None:
    tests = [
        test_frozen_hashes_and_sample_count,
        test_baseline_preserved_in_refresh_record,
        test_missing_no_fake_views,
        test_t48_checkpoint_metadata,
        test_t72_checkpoint_metadata,
        test_output_invariants_mock,
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
    print("All stage110 T24 refresh tests passed.")


if __name__ == "__main__":
    main()
