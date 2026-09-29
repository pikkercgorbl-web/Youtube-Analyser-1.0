"""Tests for T72+ refresh snapshot (Stage 1.9C)."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.youtube.client import YouTubeVideoDetails
from app.services.radar_t72_refresh import (
    build_refresh_snapshot,
    build_unique_refresh_cohort,
    calc_elapsed_hours,
    calc_growth_fields,
    file_fingerprint,
    fingerprint_t0_artifacts,
    refresh_video_details,
    run_t72_refresh,
    t0_artifacts_unchanged,
    verify_refresh_invariants,
)


def _t0_row(**kwargs: object) -> dict:
    base = {
        "video_id": "vid1",
        "keyword": "gaming",
        "discovered_at": "2026-09-11T17:39:03+00:00",
        "discovery_views": 1000,
        "final_subscribers": None,
        "published_at": "2026-09-11T10:00:00+00:00",
        "age_hours_at_t0": 7.0,
        "vph_at_t0": 142.86,
        "views_per_subscriber_at_t0": None,
        "content_format": "regular",
        "qualification_state": "rejected",
        "first_failure_reason": "min_views",
    }
    base.update(kwargs)
    return base


def _details(video_id: str = "vid1", views: int = 1500) -> YouTubeVideoDetails:
    return YouTubeVideoDetails(
        video_id=video_id,
        channel_id="UC1234567890123456789012",
        title="Title",
        published_at=datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc),
        views_count=views,
        likes_count=0,
        comments_count=0,
        duration_seconds=600,
    )


def test_dedupe_cross_keyword_and_merge_keywords() -> None:
    rows = [
        _t0_row(keyword="gaming"),
        _t0_row(keyword="travel"),
        _t0_row(video_id="vid2", keyword="gaming"),
    ]
    cohort, stats = build_unique_refresh_cohort(rows)
    assert stats["t0_rows"] == 3
    assert stats["unique_video_ids"] == 2
    assert stats["cross_keyword_duplicates_collapsed"] == 1
    by_id = {item["video_id"]: item for item in cohort}
    assert by_id["vid1"]["t0_keywords"] == ["gaming", "travel"]
    assert by_id["vid1"]["t0_row_occurrences"] == 2


def test_elapsed_hours_calculation() -> None:
    t0 = datetime(2026, 9, 11, 17, 39, 3, tzinfo=timezone.utc)
    snap = datetime(2026, 9, 14, 17, 39, 3, tzinfo=timezone.utc)
    assert calc_elapsed_hours(t0, snap) == 72.0


def test_growth_calculations() -> None:
    growth = calc_growth_fields(t0_views=1000, current_views=2500, elapsed_hours_from_t0=50.0)
    assert growth["absolute_view_growth"] == 1500
    assert growth["view_growth_multiple"] == 2.5
    assert growth["avg_growth_views_per_hour"] == 30.0


def test_t0_views_zero_multiple_none() -> None:
    growth = calc_growth_fields(t0_views=0, current_views=100, elapsed_hours_from_t0=10.0)
    assert growth["view_growth_multiple"] is None
    assert growth["absolute_view_growth"] == 100


def test_missing_api_video() -> None:
    cohort, _ = build_unique_refresh_cohort([_t0_row(video_id="missing")])
    records, counts = build_refresh_snapshot(
        cohort,
        details_by_id={},
        failed_ids=set(),
        snapshot_at=datetime(2026, 9, 14, 18, 0, tzinfo=timezone.utc),
        t0_reference_at=datetime(2026, 9, 11, 17, 39, 3, tzinfo=timezone.utc),
    )
    assert counts["missing"] == 1
    assert records[0]["refresh_status"] == "missing"
    assert records[0]["current_views"] is None
    assert records[0]["absolute_view_growth"] is None


def test_partial_api_response() -> None:
    cohort, _ = build_unique_refresh_cohort([_t0_row(video_id="a"), _t0_row(video_id="b")])
    records, counts = build_refresh_snapshot(
        cohort,
        details_by_id={"a": _details("a", 2000)},
        failed_ids=set(),
        snapshot_at=datetime(2026, 9, 14, 18, 0, tzinfo=timezone.utc),
        t0_reference_at=datetime(2026, 9, 11, 17, 39, 3, tzinfo=timezone.utc),
    )
    assert counts["refreshed"] == 1
    assert counts["missing"] == 1


def test_failed_batch_ids() -> None:
    client = MagicMock()
    client.get_videos.side_effect = RuntimeError("api down")
    details, batches, failed = refresh_video_details(client, ["a", "b"])
    assert batches == 1
    assert failed == {"a", "b"}
    assert details == {}


def test_invariant_accounting() -> None:
    cohort, _ = build_unique_refresh_cohort([_t0_row(video_id="a"), _t0_row(video_id="b")])
    records, counts = build_refresh_snapshot(
        cohort,
        details_by_id={"a": _details("a", 2000)},
        failed_ids={"b"},
        snapshot_at=datetime(2026, 9, 14, 18, 0, tzinfo=timezone.utc),
        t0_reference_at=datetime(2026, 9, 11, 17, 39, 3, tzinfo=timezone.utc),
    )
    inv = verify_refresh_invariants(records, counts)
    assert inv["accounting_ok"] is True
    assert inv["growth_sanity_ok"] is True


def test_t0_input_files_not_modified_by_refresh() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        jsonl = tmp_path / "cohort.jsonl"
        jsonl.write_text(json.dumps(_t0_row()) + "\n", encoding="utf-8")
        manifest = {
            "timestamp": "2026-09-11T17:39:03+00:00",
            "per_keyword": [{"keyword": "gaming", "dataset_path": str(jsonl)}],
        }
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        before = fingerprint_t0_artifacts(manifest, manifest_path)
        client = MagicMock()
        client.get_videos.return_value = [_details()]

        run_t72_refresh(
            manifest_path,
            client=client,
            output_dir=tmp_path,
            snapshot_at=datetime(2026, 9, 14, 18, 0, tzinfo=timezone.utc),
            t0_fingerprints_before=before,
        )

        after = fingerprint_t0_artifacts(manifest, manifest_path)
        assert t0_artifacts_unchanged(before, after) is True
        assert file_fingerprint(jsonl).sha256 == before[1].sha256


async def main() -> None:
    tests = [
        test_dedupe_cross_keyword_and_merge_keywords,
        test_elapsed_hours_calculation,
        test_growth_calculations,
        test_t0_views_zero_multiple_none,
        test_missing_api_video,
        test_partial_api_response,
        test_failed_batch_ids,
        test_invariant_accounting,
        test_t0_input_files_not_modified_by_refresh,
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
    print("All T72 refresh tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
