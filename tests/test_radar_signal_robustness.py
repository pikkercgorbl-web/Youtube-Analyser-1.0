"""Tests for signal robustness diagnostics (Stage 1.9E)."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.radar_signal_robustness import (
    attach_within_keyword_percentile,
    bootstrap_stability,
    classification_metrics,
    compute_within_keyword_vph_percentiles,
    failure_reason_diagnostics,
    filter_primary_population,
    filter_vph_population,
    jaccard,
    min_views_boundary_analysis,
    overlap_analysis,
    top_k_by_field,
    winner_thresholds,
    within_views_vph_control,
)


def _row(**kwargs: object) -> dict:
    base = {
        "video_id": "v1",
        "t0_keywords": ["gaming"],
        "t0_views": 1000,
        "t0_vph": 500.0,
        "t0_views_per_subscriber": None,
        "t0_age_hours": 10.0,
        "t0_content_format": "regular",
        "t0_qualification_outcome": "rejected",
        "t0_filter_reason": "min_views",
        "absolute_view_growth": 100.0,
    }
    base.update(kwargs)
    return base


def test_identical_population_filters() -> None:
    rows = [
        _row(),
        _row(video_id="v2", t0_content_format="short"),
        _row(video_id="v3", t0_vph=None),
    ]
    primary = filter_primary_population(rows)
    vph = filter_vph_population(primary)
    assert len(primary) == 2
    assert len(vph) == 1


def test_top_k_selector_and_pr_metrics() -> None:
    rows = [
        _row(video_id="a", t0_views=100, absolute_view_growth=10),
        _row(video_id="b", t0_views=200, absolute_view_growth=1000),
        _row(video_id="c", t0_views=300, absolute_view_growth=500),
    ]
    threshold = winner_thresholds(rows)["top_10_pct"]
    selected = top_k_by_field(rows, "t0_views", 0.34)
    metrics = classification_metrics(rows, selected_ids=selected, winner_threshold=threshold)
    assert metrics["selected"] >= 1


def test_jaccard_overlap() -> None:
    assert jaccard({"a", "b"}, {"b", "c"}) == round(1 / 3, 4)


def test_within_views_stratification() -> None:
    rows = [_row(video_id=f"v{i}", t0_views=i * 1000, t0_vph=10 + i) for i in range(1, 25)]
    result = within_views_vph_control(rows, winner_threshold=500)
    assert isinstance(result, dict)


def test_age_bands_preserves_negative_growth() -> None:
    rows = [_row(absolute_view_growth=-5)]
    primary = filter_primary_population(rows)
    assert primary[0]["absolute_view_growth"] == -5


def test_keyword_local_winner_threshold_per_keyword() -> None:
    mapping = compute_within_keyword_vph_percentiles(
        [
            _row(video_id="a", t0_keywords=["gaming"], t0_vph=10),
            _row(video_id="b", t0_keywords=["gaming"], t0_vph=100),
        ],
    )
    assert mapping["b"]["gaming"] > mapping["a"]["gaming"]


def test_multi_keyword_max_percentile() -> None:
    enriched = attach_within_keyword_percentile(
        [
            _row(video_id="x", t0_keywords=["gaming", "travel"], t0_vph=50),
            _row(video_id="y", t0_keywords=["gaming"], t0_vph=10),
            _row(video_id="z", t0_keywords=["travel"], t0_vph=200),
        ],
    )
    x = next(item for item in enriched if item["video_id"] == "x")
    assert x["vph_percentile_within_keyword_max"] is not None


def test_qualification_confusion_matrix() -> None:
    rows = [
        _row(video_id="p", t0_qualification_outcome="passed", absolute_view_growth=1000),
        _row(video_id="r", t0_qualification_outcome="rejected", absolute_view_growth=10),
    ]
    thresholds = winner_thresholds(rows)
    from app.services.radar_signal_robustness import qualification_diagnostics

    result = qualification_diagnostics(rows, thresholds)
    assert "top_10_pct_winners" in result


def test_min_views_boundary_grouping() -> None:
    rows = [_row(t0_views=500, absolute_view_growth=50), _row(video_id="b", t0_views=15000, absolute_view_growth=200)]
    thresholds = winner_thresholds(rows)
    result = min_views_boundary_analysis(rows, winner_threshold=thresholds["top_10_pct"])
    assert "<1k" in result["bins"]


def test_missing_v_s_separation() -> None:
    rows = [
        _row(t0_filter_reason="min_viral_coeff", t0_views_per_subscriber=None),
        _row(video_id="b", t0_filter_reason="min_viral_coeff", t0_views_per_subscriber=0.5),
    ]
    from app.services.radar_signal_robustness import min_viral_coeff_diagnostics

    result = min_viral_coeff_diagnostics(rows, winner_threshold=100)
    assert result["v_s_missing"]["n"] == 1
    assert result["v_s_available"]["n"] == 1


def test_bootstrap_reproducibility() -> None:
    rows = [_row(video_id=f"v{i}", t0_views=i * 100, t0_vph=i * 10, absolute_view_growth=i * 50) for i in range(1, 40)]
    a = bootstrap_stability(filter_vph_population(rows), resamples=200, seed=42)
    b = bootstrap_stability(filter_vph_population(rows), resamples=200, seed=42)
    assert a == b


def test_overlap_outcome_groups() -> None:
    rows = [_row(video_id=f"v{i}", t0_views=i * 1000, t0_vph=i * 100, absolute_view_growth=i * 10) for i in range(1, 30)]
    thresholds = winner_thresholds(rows)
    result = overlap_analysis(rows, top_fraction=0.10, winner_threshold=thresholds["top_10_pct"])
    assert "outcomes" in result


def test_failure_reason_diagnostics() -> None:
    rows = [_row(t0_filter_reason="min_views"), _row(video_id="b", t0_filter_reason="min_viral_coeff")]
    result = failure_reason_diagnostics(rows, winner_thresholds(rows))
    assert "limitation" in result


async def main() -> None:
    tests = [
        test_identical_population_filters,
        test_top_k_selector_and_pr_metrics,
        test_jaccard_overlap,
        test_within_views_stratification,
        test_age_bands_preserves_negative_growth,
        test_keyword_local_winner_threshold_per_keyword,
        test_multi_keyword_max_percentile,
        test_qualification_confusion_matrix,
        test_min_views_boundary_grouping,
        test_missing_v_s_separation,
        test_bootstrap_reproducibility,
        test_overlap_outcome_groups,
        test_failure_reason_diagnostics,
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
    print("All signal robustness tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
