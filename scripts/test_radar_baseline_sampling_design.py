"""Tests for baseline sampling design (Stage 1.10B)."""

from __future__ import annotations

import random
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.radar_baseline_sampling_design import (
    SAMPLING_SEED,
    SamplingRecord,
    apply_per_channel_cap,
    assign_channel_size_stratum,
    assign_vph_stratum,
    capped_proportional_keyword_allocation,
    compute_vph_boundaries,
    execute_frozen_t0_sampler,
    filter_regular_sampling_pool,
    proportional_keyword_allocation,
    sample_design_a_vph_heavy,
)


def test_vph_stratum_assignment() -> None:
    bounds = {"p25": 10.0, "p75": 100.0, "p90": 500.0}
    assert assign_vph_stratum(5, bounds) == "low"
    assert assign_vph_stratum(50, bounds) == "medium"
    assert assign_vph_stratum(200, bounds) == "high"
    assert assign_vph_stratum(600, bounds) == "very_high"


def test_keyword_caps() -> None:
    counts = {f"kw{i}": 100 for i in range(10)}
    capped = capped_proportional_keyword_allocation(counts, 100, cap_fraction=0.18)
    assert all(value <= 18 for value in capped.values())
    assert sum(capped.values()) == 100


def test_dedupe_video_id_in_pool_filter() -> None:
    pool = filter_regular_sampling_pool(
        [
            {"content_format": "regular", "vph_at_t0": 1.0, "channel_id": "c1", "video_id": "a"},
            {"content_format": "short", "vph_at_t0": 1.0, "channel_id": "c1", "video_id": "b"},
        ],
    )
    assert len(pool) == 1


def test_per_channel_cap() -> None:
    records = {
        "a": SamplingRecord("a", "ch1", "gaming", 10.0, 100, 1.0, None, "high", "unknown"),
        "b": SamplingRecord("b", "ch1", "gaming", 9.0, 90, 1.0, None, "high", "unknown"),
        "c": SamplingRecord("c", "ch2", "gaming", 8.0, 80, 1.0, None, "medium", "unknown"),
    }
    capped = apply_per_channel_cap(["a", "b", "c"], records, max_per_channel=1)
    assert capped == ["a", "c"]


def test_missing_subscriber_unknown_stratum() -> None:
    assert assign_channel_size_stratum(None, 0, {"p33": 1000.0, "p67": 5000.0}) == "unknown"


def test_proportional_allocation() -> None:
    alloc = proportional_keyword_allocation({"a": 50, "b": 50}, 10)
    assert sum(alloc.values()) == 10


def test_capped_allocation() -> None:
    alloc = capped_proportional_keyword_allocation(
        {f"kw{i}": 200 for i in range(10)},
        50,
    )
    assert sum(alloc.values()) == 50


def test_deterministic_sampling_seed() -> None:
    records = []
    for i in range(30):
        if i >= 25:
            stratum = "very_high"
        elif i >= 15:
            stratum = "high"
        elif i >= 5:
            stratum = "medium"
        else:
            stratum = "low"
        records.append(
            SamplingRecord(f"v{i}", f"ch{i}", "gaming", float(i), i, 1.0, None, stratum, "unknown"),
        )
    alloc = {"gaming": 10}
    rng1 = random.Random(SAMPLING_SEED)
    rng2 = random.Random(SAMPLING_SEED)
    a = sample_design_a_vph_heavy(records, target_size=10, keyword_allocation=alloc, rng=rng1, max_per_channel=2)
    b = sample_design_a_vph_heavy(records, target_size=10, keyword_allocation=alloc, rng=rng2, max_per_channel=2)
    assert a == b


def test_frozen_sampler_no_t67_fields() -> None:
    record = {
        "video_id": "v1",
        "channel_id": "c1",
        "keyword": "gaming",
        "content_format": "regular",
        "vph_at_t0": 9999.0,
        "absolute_view_growth": 1_000_000,
    }
    bounds = compute_vph_boundaries([{"vph_at_t0": 100.0}, {"vph_at_t0": 9999.0}])
    rng = random.Random(0)
    assert execute_frozen_t0_sampler(
        record,
        vph_bounds=bounds,
        keyword_cap=100,
        keyword_selected={},
        channel_selected={},
        max_per_channel=2,
        rng=rng,
    )


def test_sample_size_accounting() -> None:
    alloc = capped_proportional_keyword_allocation({f"kw{i}": 100 for i in range(8)}, 40)
    assert sum(alloc.values()) == 40


def main() -> None:
    tests = [
        test_vph_stratum_assignment,
        test_keyword_caps,
        test_dedupe_video_id_in_pool_filter,
        test_per_channel_cap,
        test_missing_subscriber_unknown_stratum,
        test_proportional_allocation,
        test_capped_allocation,
        test_deterministic_sampling_seed,
        test_frozen_sampler_no_t67_fields,
        test_sample_size_accounting,
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
    print("All baseline sampling design tests passed.")


if __name__ == "__main__":
    main()
