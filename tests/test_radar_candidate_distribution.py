"""Smoke tests for radar candidate distribution analysis (Stage 1.3)."""

from __future__ import annotations

import copy
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.radar_candidate import (
    DISCOVERY_SOURCE_INNERTUBE,
    QUALIFICATION_PARSE_ERROR,
    QUALIFICATION_PASSED,
    QUALIFICATION_REJECTED,
    RadarCandidate,
)
from app.services.radar_candidate_distribution import build_candidate_distribution
from app.services.radar_filter_metrics import (
    FILTER_SKIP_MIN_VIEWS,
    FILTER_SKIP_MIN_VIRAL_COEFF,
)


def _candidate(
    *,
    video_id: str = "vid1",
    title: str = "Test video",
    views: int = 10_000,
    subscribers: int | None = 500,
    viral: float | None = 20.0,
    vph: float | None = 100.0,
    age: float | None = 3.0,
    state: str = QUALIFICATION_REJECTED,
    reason: str | None = FILTER_SKIP_MIN_VIEWS,
) -> RadarCandidate:
    return RadarCandidate(
        video_id=video_id,
        channel_id="UC1234567890123456789012",
        keyword="test",
        discovery_source=DISCOVERY_SOURCE_INNERTUBE,
        discovered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        video_title=title,
        channel_title="Channel",
        published_text="3 days ago",
        views=views,
        subscribers=subscribers,
        qualification_state=state,
        first_failure_reason=reason,
        viral_coefficient=viral,
        vph=vph,
        video_age_days=age,
    )


def test_empty_candidates() -> None:
    result = build_candidate_distribution("test", [])
    assert result["total_candidates"] == 0
    assert result["passed"] == 0
    assert result["rejected"] == 0
    assert result["parse_errors"] == 0
    assert result["groups"]["all"]["count"] == 0
    assert result["filter_skip_reasons"] == {}


def test_all_candidates_group() -> None:
    candidates = [
        _candidate(video_id="a", views=100, vph=10.0, age=1.0),
        _candidate(video_id="b", views=200, vph=20.0, age=2.0),
    ]
    result = build_candidate_distribution("test", candidates)
    assert result["total_candidates"] == 2
    all_group = result["groups"]["all"]
    assert all_group["count"] == 2
    assert all_group["views"] == {"count": 2, "min": 100, "max": 200}
    assert all_group["vph"] == {"count": 2, "min": 10.0, "max": 20.0}


def test_passed_and_rejected_groups() -> None:
    candidates = [
        _candidate(
            video_id="pass",
            state=QUALIFICATION_PASSED,
            reason=None,
            views=100_000,
            viral=50.0,
        ),
        _candidate(
            video_id="reject",
            state=QUALIFICATION_REJECTED,
            reason=FILTER_SKIP_MIN_VIEWS,
            views=1_000,
        ),
    ]
    result = build_candidate_distribution("test", candidates)
    assert result["passed"] == 1
    assert result["rejected"] == 1
    assert result["groups"]["passed"]["count"] == 1
    assert result["groups"]["passed"]["views"]["min"] == 100_000
    assert FILTER_SKIP_MIN_VIEWS in result["groups"]
    assert result["groups"][FILTER_SKIP_MIN_VIEWS]["count"] == 1


def test_missing_viral_coefficient() -> None:
    candidates = [
        _candidate(video_id="a", viral=None, subscribers=0),
        _candidate(video_id="b", viral=10.0, subscribers=100),
    ]
    result = build_candidate_distribution("test", candidates)
    assert result["signal_availability"]["viral_coefficient"] == 1
    all_group = result["groups"]["all"]
    assert "viral_coefficient" in all_group
    assert all_group["viral_coefficient"]["count"] == 1


def test_missing_vph_and_age() -> None:
    candidates = [
        _candidate(video_id="a", vph=None, age=None),
        _candidate(video_id="b", vph=50.0, age=5.0),
    ]
    result = build_candidate_distribution("test", candidates)
    assert result["signal_availability"]["vph"] == 1
    assert result["signal_availability"]["video_age_days"] == 1
    all_group = result["groups"]["all"]
    assert all_group["vph"]["count"] == 1
    assert all_group["video_age_days"]["count"] == 1


def test_grouping_by_first_failure_reason() -> None:
    candidates = [
        _candidate(video_id="v1", reason=FILTER_SKIP_MIN_VIEWS),
        _candidate(video_id="v2", reason=FILTER_SKIP_MIN_VIEWS),
        _candidate(video_id="v3", reason=FILTER_SKIP_MIN_VIRAL_COEFF),
    ]
    result = build_candidate_distribution("test", candidates)
    assert result["filter_skip_reasons"] == {
        FILTER_SKIP_MIN_VIEWS: 2,
        FILTER_SKIP_MIN_VIRAL_COEFF: 1,
    }
    assert result["groups"][FILTER_SKIP_MIN_VIEWS]["count"] == 2
    assert result["groups"][FILTER_SKIP_MIN_VIRAL_COEFF]["count"] == 1


def test_sample_limit() -> None:
    candidates = [
        _candidate(
            video_id=f"v{i}",
            title=f"Video {i}",
            reason=FILTER_SKIP_MIN_VIEWS,
        )
        for i in range(10)
    ]
    result = build_candidate_distribution("test", candidates, sample_limit=3)
    samples = result["samples"][FILTER_SKIP_MIN_VIEWS]
    assert len(samples) == 3
    assert samples[0]["title"] == "Video 0"


def test_aggregation_does_not_mutate_candidates() -> None:
    candidates = [_candidate(video_id="a"), _candidate(video_id="b")]
    before = [copy.deepcopy(candidate) for candidate in candidates]
    build_candidate_distribution("test", candidates)
    for original, current in zip(before, candidates, strict=True):
        assert original == current


def test_parse_error_group() -> None:
    candidates = [
        _candidate(
            video_id="err",
            state=QUALIFICATION_PARSE_ERROR,
            reason="parse_error",
            viral=None,
            vph=None,
            age=None,
        ),
    ]
    result = build_candidate_distribution("test", candidates)
    assert result["parse_errors"] == 1
    assert result["groups"]["parse_error"]["count"] == 1
    assert result["filter_skip_reasons"]["parse_error"] == 1


def main() -> None:
    tests = [
        test_empty_candidates,
        test_all_candidates_group,
        test_passed_and_rejected_groups,
        test_missing_viral_coefficient,
        test_missing_vph_and_age,
        test_grouping_by_first_failure_reason,
        test_sample_limit,
        test_aggregation_does_not_mutate_candidates,
        test_parse_error_group,
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
    print("All radar candidate distribution tests passed.")


if __name__ == "__main__":
    main()
