"""Tests for Stage 1.18C keyword performance historical validation."""

from __future__ import annotations

import hashlib
import math
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.keyword_performance_validation import (
    COHORT_2_JOINED,
    FROZEN_JOINED_SHA256,
    analyze_frozen_cohort,
    build_early_top_decile_video_set,
    expand_frozen_observations,
    filter_frozen_signal_row,
    keyword_level_q1_analysis,
    run_full_validation,
    write_artifacts,
)
from app.services.radar_t0_data_quality import load_t0_jsonl


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_frozen_joined_hashes_unchanged() -> None:
    artifacts = ROOT / "artifacts"
    for name, expected in FROZEN_JOINED_SHA256.items():
        path = artifacts / name
        assert path.is_file(), name
        assert _sha256(path) == expected


def test_early_top_decile_uses_discovery_vph_only() -> None:
    rows = load_t0_jsonl(ROOT / "artifacts" / COHORT_2_JOINED)
    signal = [r for r in rows if filter_frozen_signal_row(r)]
    top = build_early_top_decile_video_set(signal)
    n = len({str(r["video_id"]) for r in signal if r.get("t0_vph") is not None})
    assert len(top) == max(1, math.ceil(n * 0.10))


def test_cohort2_q1_spearman_positive_vph_signal() -> None:
    report = analyze_frozen_cohort(
        ROOT / "artifacts" / COHORT_2_JOINED,
        cohort_id="stage110_test",
    )
    q1 = report["attribution_comparison"]["all_hits"]["q1"]
    rho = q1["median_vph_at_discovery_vs_median_absolute_view_growth_72h"]["spearman"]["rho"]
    assert rho is not None
    assert float(rho) > 0.2
    assert q1["keywords_with_any_72h_outcome"] >= 5


def test_first_discovery_reduces_observations_vs_all_hits() -> None:
    rows = load_t0_jsonl(ROOT / "artifacts" / COHORT_2_JOINED)
    signal = [r for r in rows if filter_frozen_signal_row(r)]
    top = build_early_top_decile_video_set(signal)
    all_obs = expand_frozen_observations(signal, mode="all_hits", early_top_decile_videos=top)
    first_obs = expand_frozen_observations(
        signal,
        mode="first_discovery",
        early_top_decile_videos=top,
    )
    assert len(first_obs) <= len(all_obs)
    assert len(first_obs) == len({str(r["video_id"]) for r in signal})


def test_full_validation_deterministic_artifact_sha() -> None:
    artifacts = ROOT / "artifacts"
    tick = iter([0.0, 2.5, 0.0, 2.5])
    with patch(
        "app.services.keyword_performance_validation.time.perf_counter",
        side_effect=lambda: next(tick),
    ):
        report = run_full_validation(artifacts, session=None)
        report.pop("generated_at", None)
        hashes1 = write_artifacts(report, artifacts)
        report2 = run_full_validation(artifacts, session=None)
        report2.pop("generated_at", None)
        hashes2 = write_artifacts(report2, artifacts)
        assert hashes1["json_sha256"] == hashes2["json_sha256"]
    assert report["metric_decision_matrix"]["current_breakout_rank_live"] == (
        "weak_or_redundant_for_historical_prediction"
    )


def test_confirmed_breakout_recommendation_retains_alias() -> None:
    report = run_full_validation(ROOT / "artifacts", session=None)
    rec = report["confirmed_breakout_count"]
    assert rec["recommendation"] == "B"
    assert rec["not_delayed_confirmation"] is True


def test_decision_matrix_uses_frozen_cohort2_q1() -> None:
    report = run_full_validation(ROOT / "artifacts", session=None)
    matrix = report["metric_decision_matrix"]
    assert matrix["median_vph_at_discovery"] == "useful_evidence"
    assert matrix["early_top_decile_rate"] == "useful_evidence"


if __name__ == "__main__":
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"OK {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    print(f"Done: {failures} failures")
    raise SystemExit(failures)
