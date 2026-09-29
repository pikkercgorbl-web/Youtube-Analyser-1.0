"""Tests for offline T0 distribution review (Stage 1.9B)."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.radar_t0_distribution_review import (
    _classify_age_bucket,
    _vph_bins,
    _vph_tail_counts,
    build_keyword_comparison_row,
    check_keyword_invariants,
    filter_regular_records,
    is_regular_record,
    review_t0_cohort_from_manifest,
    write_distribution_review,
)


def _record(**kwargs: object) -> dict:
    base = {
        "video_id": "v1",
        "content_format": "regular",
        "qualification_state": "rejected",
        "discovery_views": 1000,
        "vph_at_t0": 250.0,
        "age_hours_at_t0": 2.0,
        "views_per_subscriber_at_t0": None,
        "final_subscribers": None,
        "subscriber_fetch_status": "not_attempted",
    }
    base.update(kwargs)
    return base


def test_regular_filter() -> None:
    records = [_record(content_format="regular"), _record(video_id="v2", content_format="short")]
    regular = filter_regular_records(records)
    assert len(regular) == 1
    assert is_regular_record(regular[0])


def test_invariants() -> None:
    records = [
        _record(video_id="a", qualification_state="passed"),
        _record(video_id="b", qualification_state="rejected"),
        _record(video_id="c", content_format="short", qualification_state="rejected"),
    ]
    checks = check_keyword_invariants(records)
    assert checks["invariant_qualification_ok"] is True
    assert checks["regular_count"] == 2
    assert checks["excluded_after_enrichment"] == 1
    assert checks["invariant_regular_split_ok"] is True


def test_vph_bins_and_tail() -> None:
    values = [50.0, 150.0, 750.0, 2500.0, 15000.0, 120000.0]
    bins = _vph_bins(values)
    assert bins[">100k"] == 1
    tail = _vph_tail_counts(values)
    assert tail[">=1000"] == 3
    assert tail[">=100000"] == 1


def test_age_buckets() -> None:
    assert _classify_age_bucket(-0.5) == "negative_or_zero"
    assert _classify_age_bucket(0.5) == "<=1h"
    assert _classify_age_bucket(25.0) == ">24h"


def test_keyword_comparison_row() -> None:
    records = [
        _record(discovery_views=10000, vph_at_t0=5000, age_hours_at_t0=5.0),
        _record(video_id="v2", content_format="short"),
    ]
    row = build_keyword_comparison_row("gaming", records)
    assert row["regular_count"] == 1
    assert row["median_views"] == 10000.0
    assert row["median_vph"] == 5000.0


def test_review_from_mini_manifest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        jsonl = tmp_path / "cohort.jsonl"
        jsonl.write_text(
            "\n".join(
                [
                    json.dumps(_record(video_id="a", qualification_state="passed", final_subscribers=100, views_per_subscriber_at_t0=10.0)),
                    json.dumps(_record(video_id="b", content_format="short")),
                ],
            ),
            encoding="utf-8",
        )
        manifest = {
            "cohort_run_id": "test_run",
            "timestamp": "2026-09-11T00:00:00+00:00",
            "keywords": ["gaming"],
            "per_keyword": [
                {
                    "keyword": "gaming",
                    "dataset_path": str(jsonl),
                    "status": "PARTIAL",
                    "raw_candidates": 2,
                    "regular_candidates": 1,
                    "excluded_after_enrichment": 1,
                },
            ],
            "totals": {},
        }
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        review = review_t0_cohort_from_manifest(manifest_path)
        assert review["overview"]["raw_records"] == 2
        assert review["overview"]["regular_records"] == 1
        assert review["verification"]["NO_NETWORK_REQUESTS"] is True
        assert review["verification"]["NO_DB_WRITES"] is True

        json_out, md_out = write_distribution_review(review, output_dir=tmp_path, review_id="test")
        assert json_out.exists()
        assert md_out.exists()


async def main() -> None:
    tests = [
        test_regular_filter,
        test_invariants,
        test_vph_bins_and_tail,
        test_age_buckets,
        test_keyword_comparison_row,
        test_review_from_mini_manifest,
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
    print("All T0 distribution review tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
