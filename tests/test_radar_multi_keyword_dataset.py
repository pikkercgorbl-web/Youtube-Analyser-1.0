"""Tests for multi-keyword dataset collection orchestration (Stage 1.7)."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from dataclasses import dataclass
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
from app.services.radar_filter_metrics import FILTER_SKIP_MIN_VIEWS, FILTER_SKIP_MIN_VIRAL_COEFF
from app.services.radar_multi_keyword_dataset import (
    DEFAULT_KEYWORDS,
    ExperimentSettings,
    aggregate_collection_summary,
    build_keyword_output_paths,
    check_candidate_invariant,
    collect_keywords_sequential,
    compute_basic_signal_availability,
    export_keyword_dataset,
    finalize_keyword_failure,
    finalize_keyword_success,
    render_collection_markdown,
    safe_keyword_slug,
    write_collection_summary,
)


@dataclass
class _FakeScanResult:
    keyword: str
    candidates: list[RadarCandidate]
    pages_scanned: int
    min_views: int = 10_000
    min_viral_coeff: float = 3.0
    upload_period: str = "all"


def _candidate(
    *,
    video_id: str = "vid1",
    keyword: str = "gaming",
    state: str = QUALIFICATION_REJECTED,
    reason: str | None = FILTER_SKIP_MIN_VIEWS,
    subscribers: int | None = 0,
    viral: float | None = None,
    vph: float | None = 100.0,
    age: float | None = 1.0,
) -> RadarCandidate:
    return RadarCandidate(
        video_id=video_id,
        channel_id="UC1234567890123456789012",
        keyword=keyword,
        discovery_source=DISCOVERY_SOURCE_INNERTUBE,
        discovered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        video_title="Test title",
        channel_title="Test channel",
        published_text="1 day ago",
        views=1000,
        subscribers=subscribers,
        qualification_state=state,
        first_failure_reason=reason,
        viral_coefficient=viral,
        vph=vph,
        video_age_days=age,
    )


def test_default_keywords_has_ten() -> None:
    assert len(DEFAULT_KEYWORDS) == 10
    assert "gaming" in DEFAULT_KEYWORDS
    assert "AI tools" in DEFAULT_KEYWORDS


def test_safe_keyword_slug() -> None:
    assert safe_keyword_slug("AI tools") == "ai_tools"
    assert safe_keyword_slug("self improvement") == "self_improvement"
    assert safe_keyword_slug("interesting facts!") == "interesting_facts"


def test_metadata_contains_experiment_settings() -> None:
    candidates = [_candidate(video_id="a")]
    settings = ExperimentSettings(
        min_views=10_000,
        min_viral_coeff=3.0,
        upload_period="all",
    )
    with tempfile.TemporaryDirectory() as tmp:
        _, meta_path, metadata = export_keyword_dataset(
            keyword="gaming",
            candidates=candidates,
            output_dir=Path(tmp),
            settings=settings,
            source="test",
            duration_seconds=12.5,
            pages_scanned=7,
        )
        assert meta_path.exists()
        assert metadata["register_channels"] is False
        assert metadata["production_db_registration"] is False
        assert metadata["min_views"] == 10_000
        assert metadata["min_viral_coeff"] == 3.0
        assert metadata["upload_period"] == "all"
        assert metadata["pages_scanned"] == 7


def test_invariant_calculation() -> None:
    counts = {"passed": 2, "rejected": 5, "parse_errors": 1, "pending": 0}
    assert check_candidate_invariant(counts, 8) is True
    assert check_candidate_invariant(counts, 9) is False
    assert check_candidate_invariant({**counts, "pending": 1}, 8) is False


async def test_failed_keyword_not_marked_success() -> None:
    async def _boom(_keyword: str) -> _FakeScanResult:
        raise RuntimeError("scan failed")

    settings = ExperimentSettings(min_views=10_000, min_viral_coeff=3.0, upload_period="all")
    with tempfile.TemporaryDirectory() as tmp:
        results = await collect_keywords_sequential(
            ["gaming"],
            scan_keyword=_boom,
            output_dir=Path(tmp),
            settings=settings,
            source="test",
        )
        assert len(results) == 1
        assert results[0].status == "failed"
        assert results[0].error_type == "RuntimeError"
        assert results[0].jsonl_path is None


def test_summary_aggregation() -> None:
    settings = ExperimentSettings(min_views=10_000, min_viral_coeff=3.0, upload_period="all")
    from app.services.radar_multi_keyword_dataset import KeywordCollectionResult

    results = [
        KeywordCollectionResult(
            keyword="gaming",
            status="success",
            counts={"total": 10, "passed": 2, "rejected": 7, "parse_errors": 1},
            rejection_reasons={"min_views": 5, "min_viral_coeff": 2},
            signal_availability=compute_basic_signal_availability(
                [_candidate(), _candidate(video_id="b", subscribers=100, viral=5.0, state=QUALIFICATION_PASSED, reason=None)],
            ),
        ),
        KeywordCollectionResult(
            keyword="travel",
            status="failed",
            error_type="RuntimeError",
            error_message="boom",
        ),
    ]
    summary = aggregate_collection_summary(
        results,
        settings=settings,
        explosive_channels_before=50,
        explosive_channels_after=50,
    )
    assert summary["keywords_successful"] == 1
    assert summary["keywords_failed"] == 1
    assert summary["totals"]["total_candidates"] == 10
    assert summary["totals"]["total_passed"] == 2
    assert summary["production_db_registration_occurred"] is False
    assert settings.register_channels is False


def test_db_registration_flags_false() -> None:
    settings = ExperimentSettings(min_views=10_000, min_viral_coeff=3.0, upload_period="all")
    assert settings.register_channels is False
    assert settings.production_db_registration is False
    assert settings.matches_expected() is True


def test_signal_availability_calculation() -> None:
    candidates = [
        _candidate(video_id="a", subscribers=100, viral=4.0),
        _candidate(video_id="b", subscribers=None, viral=None, vph=None, age=None),
        _candidate(
            video_id="c",
            state=QUALIFICATION_PASSED,
            reason=None,
            subscribers=1000,
            viral=5.0,
        ),
    ]
    availability = compute_basic_signal_availability(candidates)
    assert availability["views"]["availability_pct"] == 100.0
    assert availability["subscribers_field_present"]["available_count"] == 2
    assert availability["subscribers_gt_zero"]["available_count"] == 2
    assert availability["vph"]["available_count"] == 2
    assert availability["viral_coefficient"]["available_count"] == 2


def test_output_paths_unique() -> None:
    ts = datetime(2026, 9, 11, 10, 0, 0, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        path_a, meta_a = build_keyword_output_paths(out, "gaming", ts)
        path_b, meta_b = build_keyword_output_paths(out, "travel", ts)
        assert path_a != path_b
        assert meta_a != meta_b
        assert "gaming" in path_a.name
        assert "travel" in path_b.name


def test_empty_candidate_result() -> None:
    settings = ExperimentSettings(min_views=10_000, min_viral_coeff=3.0, upload_period="all")
    with tempfile.TemporaryDirectory() as tmp:
        result = finalize_keyword_success(
            keyword="travel",
            candidates=[],
            output_dir=Path(tmp),
            settings=settings,
            source="test",
            duration_seconds=1.0,
            pages_scanned=0,
        )
        assert result.status == "success"
        assert result.counts["total"] == 0
        assert Path(result.jsonl_path).exists()
        meta = json.loads(Path(result.meta_path).read_text(encoding="utf-8"))
        assert meta["total_candidates"] == 0
        assert meta["passed"] == 0


def test_invariant_failure_marks_failed() -> None:
    settings = ExperimentSettings(min_views=10_000, min_viral_coeff=3.0, upload_period="all")
    bad_candidates = [_candidate(state=QUALIFICATION_PASSED, reason=None), _candidate()]
    bad_candidates[1].qualification_state = "pending"
    with tempfile.TemporaryDirectory() as tmp:
        result = finalize_keyword_success(
            keyword="gaming",
            candidates=bad_candidates,
            output_dir=Path(tmp),
            settings=settings,
            source="test",
            duration_seconds=1.0,
            pages_scanned=1,
        )
        assert result.status == "failed"
        assert result.error_type == "InvariantError"
        assert result.jsonl_path is None


def test_markdown_renders_tables() -> None:
    settings = ExperimentSettings(min_views=10_000, min_viral_coeff=3.0, upload_period="all")
    from app.services.radar_multi_keyword_dataset import KeywordCollectionResult

    summary = aggregate_collection_summary(
        [
            KeywordCollectionResult(
                keyword="gaming",
                status="success",
                counts={"total": 3, "passed": 1, "rejected": 2, "parse_errors": 0},
                pages_scanned=5,
                duration_seconds=10.0,
                rejection_reasons={"min_views": 2},
                signal_availability=compute_basic_signal_availability([_candidate()]),
            ),
        ],
        settings=settings,
        explosive_channels_before=1,
        explosive_channels_after=1,
    )
    md = render_collection_markdown(summary)
    assert "| gaming | success |" in md
    assert "Subscriber availability" in md


async def main() -> None:
    sync_tests = [
        test_default_keywords_has_ten,
        test_safe_keyword_slug,
        test_metadata_contains_experiment_settings,
        test_invariant_calculation,
        test_summary_aggregation,
        test_db_registration_flags_false,
        test_signal_availability_calculation,
        test_output_paths_unique,
        test_empty_candidate_result,
        test_invariant_failure_marks_failed,
        test_markdown_renders_tables,
    ]
    async_tests = [test_failed_keyword_not_marked_success]

    failed = 0
    for test in sync_tests:
        try:
            test()
            print(f"OK {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")

    for test in async_tests:
        try:
            await test()
            print(f"OK {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")

    if failed:
        raise SystemExit(f"{failed} test(s) failed")
    print("All multi-keyword dataset tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
