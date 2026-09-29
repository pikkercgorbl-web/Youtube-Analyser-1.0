"""Smoke tests for offline RadarCandidate dataset analysis (Stage 1.6)."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.radar_candidate_analysis import (
    GROUP_PASSED,
    GROUP_REJECTED_MIN_VIEWS,
    GROUP_REJECTED_MIN_VIRAL_COEFF,
    analyze_candidate_dataset,
    analyze_min_viral_coeff_group,
    generate_initial_observations,
    load_candidate_records,
    numeric_distribution,
    split_candidate_groups,
    _top_candidates,
)
from app.services.radar_filter_metrics import FILTER_SKIP_MIN_VIEWS, FILTER_SKIP_MIN_VIRAL_COEFF


def _record(
    *,
    video_id: str = "v1",
    state: str = "rejected",
    reason: str | None = FILTER_SKIP_MIN_VIEWS,
    views: int = 1000,
    subscribers: int | None = 0,
    vph: float | None = 100.0,
    viral: float | None = None,
    age: float | None = 1.0,
) -> dict:
    return {
        "keyword": "gaming",
        "video_id": video_id,
        "channel_id": "UC1234567890123456789012",
        "video_title": f"Title {video_id}",
        "channel_title": "Channel",
        "published_text": "1 day ago",
        "views": views,
        "subscribers": subscribers,
        "video_age_days": age,
        "vph": vph,
        "viral_coefficient": viral,
        "qualification_state": state,
        "first_failure_reason": reason,
        "discovery_source": "innertube",
        "discovered_at": "2026-09-11T09:53:38+00:00",
    }


def test_group_splitting() -> None:
    records = [
        _record(video_id="pass", state="passed", reason=None, views=50000),
        _record(video_id="mv", reason=FILTER_SKIP_MIN_VIEWS),
        _record(video_id="mvc", reason=FILTER_SKIP_MIN_VIRAL_COEFF, viral=0.5, subscribers=1000),
        _record(video_id="lang", reason="language"),
        _record(video_id="err", state="parse_error", reason="parse_error", vph=None),
    ]
    groups = split_candidate_groups(records)
    assert len(groups[GROUP_PASSED]) == 1
    assert len(groups[GROUP_REJECTED_MIN_VIEWS]) == 1
    assert len(groups[GROUP_REJECTED_MIN_VIRAL_COEFF]) == 1
    assert len(groups["rejected_language"]) == 1
    assert len(groups["parse_errors"]) == 1


def test_none_not_converted_to_zero() -> None:
    records = [_record(vph=None, viral=None, age=None, subscribers=None)]
    analysis = analyze_candidate_dataset(records)
    availability = analysis["signal_availability"]
    assert availability["vph"]["available_count"] == 0
    assert availability["viral_coefficient"]["available_count"] == 0
    assert availability["subscribers"]["available_count"] == 0


def test_availability_counts() -> None:
    records = [
        _record(video_id="a", vph=10.0, viral=2.0, subscribers=100),
        _record(video_id="b", vph=None, viral=None, subscribers=0),
    ]
    analysis = analyze_candidate_dataset(records)
    availability = analysis["signal_availability"]
    assert availability["vph"]["available_count"] == 1
    assert availability["viral_coefficient"]["available_count"] == 1
    assert availability["subscribers"]["meaningful_count"] == 1


def test_percentile_calculations() -> None:
    stats = numeric_distribution([1.0, 2.0, 3.0, 4.0, 5.0])
    assert stats["count"] == 5
    assert stats["min"] == 1.0
    assert stats["median"] == 3.0
    assert stats["max"] == 5.0
    assert stats["p75"] >= stats["median"]
    assert stats["p90"] >= stats["p75"]


def test_min_viral_split() -> None:
    records = [
        _record(video_id="with", reason=FILTER_SKIP_MIN_VIRAL_COEFF, viral=0.4, subscribers=500),
        _record(video_id="without", reason=FILTER_SKIP_MIN_VIRAL_COEFF, viral=None, subscribers=0),
    ]
    result = analyze_min_viral_coeff_group(records)
    assert result["with_viral_coefficient"] == 1
    assert result["without_viral_coefficient"] == 1


def test_top_n_sorting() -> None:
    records = [
        _record(video_id="low", vph=10.0),
        _record(video_id="high", vph=100.0),
        _record(video_id="mid", vph=50.0),
    ]
    top = _top_candidates(records, sort_field="vph", limit=2)
    assert top[0]["video_id"] == "high"
    assert top[1]["video_id"] == "mid"


def test_empty_dataset() -> None:
    analysis = analyze_candidate_dataset([])
    assert analysis["dataset"]["candidate_count"] == 0
    assert analysis["groups"]["all"]["count"] == 0


def test_single_candidate_dataset() -> None:
    records = [_record(video_id="only", state="passed", reason=None, views=12345, vph=999.0)]
    analysis = analyze_candidate_dataset(records)
    assert analysis["dataset"]["candidate_count"] == 1
    assert analysis["dataset"]["passed"] == 1
    assert analysis["groups"]["passed"]["views"]["median"] == 12345


def test_load_jsonl_roundtrip() -> None:
    record = _record(video_id="jsonl")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sample.jsonl"
        path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
        loaded = load_candidate_records(path)
    assert loaded[0]["video_id"] == "jsonl"
    assert loaded[0]["vph"] == 100.0


def test_initial_observations_are_factual() -> None:
    records = [
        _record(video_id="pass", state="passed", reason=None, views=50000, vph=500.0),
        _record(video_id="reject", reason=FILTER_SKIP_MIN_VIEWS, views=1000, vph=50.0),
    ]
    analysis = analyze_candidate_dataset(records)
    observations = analysis["initial_observations"]
    assert any("contains 2 candidates" in item for item in observations)
    assert all("should replace" not in item.lower() for item in observations)
    assert all("best" not in item.lower() for item in observations)


def test_analysis_does_not_mutate_records() -> None:
    records = [_record(video_id="a"), _record(video_id="b", vph=200.0)]
    before = copy.deepcopy(records)
    analyze_candidate_dataset(records)
    assert records == before


def main() -> None:
    tests = [
        test_group_splitting,
        test_none_not_converted_to_zero,
        test_availability_counts,
        test_percentile_calculations,
        test_min_viral_split,
        test_top_n_sorting,
        test_empty_dataset,
        test_single_candidate_dataset,
        test_load_jsonl_roundtrip,
        test_initial_observations_are_factual,
        test_analysis_does_not_mutate_records,
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
    print("All radar candidate analysis tests passed.")


if __name__ == "__main__":
    main()
