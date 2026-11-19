"""Tests for Stage 1.17C breakout historical evaluation."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.breakout_rank_v1_evaluation import (
    COHORT_1_JOINED,
    COHORT_2_JOINED,
    FROZEN_JOINED_SHA256,
    apply_breakout_ranks,
    evaluate_cohort,
    run_full_evaluation,
)
from app.services.breakout_ranking_service import rank_breakout_v1
from app.services.radar_t0_data_quality import load_t0_jsonl

GOLDEN_SIGNAL = {
    "cohort_1": {
        "views_rho": 0.7966,
        "vph_rho": 0.8275,
        "views_top10": 0.6214,
        "vph_top10": 0.7029,
        "signal_n": 2794,
        "vph_n": 2760,
    },
    "cohort_2": {
        "views_rho": 0.7826,
        "vph_rho": 0.8082,
        "views_top10": 0.5,
        "vph_top10": 0.62,
        "signal_n": 494,
        "vph_n": 494,
    },
}

GOLDEN_PRODUCTION = {
    "cohort_2": {
        "eligible_n": 494,
        "vph_rho": 0.8082,
        "breakout_rho": 0.8083,
        "vph_top10": 0.62,
        "breakout_top10": 0.62,
        "spearman_rank_equiv": 1.0,
    },
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_frozen_joined_artifacts_unchanged() -> None:
    artifacts = ROOT / "artifacts"
    for name, expected in FROZEN_JOINED_SHA256.items():
        path = artifacts / name
        assert path.is_file(), f"missing {name}"
        assert _sha256(path) == expected, f"frozen hash changed for {name}"


def test_imports_production_rank_breakout_v1() -> None:
    rows = load_t0_jsonl(ROOT / "artifacts" / COHORT_2_JOINED)[:5]
    _, eligible = apply_breakout_ranks(rows)
    assert eligible
    assert eligible[0]["breakout_rank_version"] == "breakout_v1"
    assert rank_breakout_v1.__module__ == "app.services.breakout_ranking_service"


def test_golden_cohort2_signal_metrics() -> None:
    report = evaluate_cohort(
        ROOT / "artifacts" / COHORT_2_JOINED,
        cohort_id="stage110_20260914_141029",
        elapsed_hours_label=71.9567,
    )
    sig = report["signal_validation_metrics"]
    golden = GOLDEN_SIGNAL["cohort_2"]
    assert report["signal_validation_row_count"] == golden["signal_n"]
    assert sig["views"]["spearman_vs_absolute_view_growth"]["rho"] == golden["views_rho"]
    assert sig["vph"]["spearman_vs_absolute_view_growth"]["rho"] == golden["vph_rho"]
    assert sig["views"]["top10_capture"]["capture_rate"] == golden["views_top10"]
    assert sig["vph"]["top10_capture"]["capture_rate"] == golden["vph_top10"]


def test_golden_cohort1_signal_metrics_tolerance() -> None:
    report = evaluate_cohort(
        ROOT / "artifacts" / COHORT_1_JOINED,
        cohort_id="T0_T67_20260914_124311",
        elapsed_hours_label=67.0689,
    )
    sig = report["signal_validation_metrics"]
    golden = GOLDEN_SIGNAL["cohort_1"]
    assert sig["views"]["spearman_vs_absolute_view_growth"]["rho"] == golden["views_rho"]
    assert sig["vph"]["spearman_vs_absolute_view_growth"]["rho"] == golden["vph_rho"]
    assert sig["views"]["top10_capture"]["capture_rate"] == golden["views_top10"]
    assert sig["vph"]["top10_capture"]["capture_rate"] == golden["vph_top10"]


def test_breakout_matches_vph_on_cohort2() -> None:
    report = evaluate_cohort(
        ROOT / "artifacts" / COHORT_2_JOINED,
        cohort_id="stage110_20260914_141029",
    )
    prod = report["production_eligibility_metrics"]
    golden = GOLDEN_PRODUCTION["cohort_2"]
    assert report["eligibility"]["production_eligible_count"] == golden["eligible_n"]
    vph_rho = prod["vph"]["spearman_vs_absolute_view_growth"]["rho"]
    br_rho = prod["breakout_v1"]["spearman_vs_absolute_view_growth"]["rho"]
    assert abs(float(vph_rho) - float(br_rho)) <= 0.0002
    assert prod["vph"]["top10_capture"]["capture_rate"] == golden["vph_top10"]
    assert prod["breakout_v1_rank_top10"]["capture_rate"] == golden["breakout_top10"]
    eq = report["equivalence"]
    assert eq["spearman_breakout_rank_vs_raw_vph_rank"]["rho"] == golden["spearman_rank_equiv"]
    assert eq["effectively_identical_to_vph_order"] is True


def test_ranking_deterministic() -> None:
    path = ROOT / "artifacts" / COHORT_2_JOINED
    first = evaluate_cohort(path, cohort_id="stage110")
    second = evaluate_cohort(path, cohort_id="stage110")
    assert first["equivalence"] == second["equivalence"]
    assert (
        first["production_eligibility_metrics"]["breakout_v1"]["spearman_vs_absolute_view_growth"]
        == second["production_eligibility_metrics"]["breakout_v1"]["spearman_vs_absolute_view_growth"]
    )


def test_full_evaluation_acceptance_passes() -> None:
    report = run_full_evaluation(ROOT / "artifacts")
    assert report["acceptance"]["pass"] is True


def main() -> None:
    tests = [
        test_frozen_joined_artifacts_unchanged,
        test_imports_production_rank_breakout_v1,
        test_golden_cohort2_signal_metrics,
        test_golden_cohort1_signal_metrics_tolerance,
        test_breakout_matches_vph_on_cohort2,
        test_ranking_deterministic,
        test_full_evaluation_acceptance_passes,
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
    print("All breakout rank v1 evaluation tests passed.")


if __name__ == "__main__":
    main()
