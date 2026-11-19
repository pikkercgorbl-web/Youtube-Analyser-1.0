"""Tests for multi-keyword validation T0 cohort orchestration (Stage 1.9A)."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.explosive_channels_radar_worker import AnalysisScanResult
from app.services.radar_candidate import (
    DISCOVERY_SOURCE_INNERTUBE,
    QUALIFICATION_PASSED,
    QUALIFICATION_REJECTED,
    RadarCandidate,
)
from app.services.radar_validation_cohort import (
    VALIDATION_COHORT_KEYWORDS,
    KeywordCohortResult,
    aggregate_enrichment_from_results,
    build_cohort_manifest_with_aggregates,
    collect_validation_cohort,
    determine_keyword_status,
    finalize_keyword_cohort_failure,
    finalize_keyword_cohort_success,
    keyword_output_slug,
    write_cohort_manifest,
)
from app.services.radar_validation_t0_dataset import split_raw_and_regular


def _candidate(
    *,
    video_id: str = "vid1",
    keyword: str = "gaming",
    state: str = QUALIFICATION_PASSED,
    content_format: str = "regular",
    enrichment_status: str = "ok",
    is_short: bool = False,
    is_live: bool = False,
    first_failure_reason: str | None = None,
) -> RadarCandidate:
    return RadarCandidate(
        video_id=video_id,
        channel_id="UC1234567890123456789012",
        keyword=keyword,
        discovery_source=DISCOVERY_SOURCE_INNERTUBE,
        discovered_at=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
        video_title="Title",
        channel_title="Channel",
        discovery_views=10_000,
        discovery_subscribers=0,
        discovery_published_text="2 hours ago",
        views=10_000,
        subscribers=0,
        qualification_state=state,
        first_failure_reason=first_failure_reason,
        content_format=content_format,
        enrichment_status=enrichment_status,
        is_short=is_short,
        is_live=is_live,
        vph_at_t0=5000.0,
        age_hours_at_t0=2.0,
        duration_seconds=600,
        published_at=datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc),
    )


def test_all_ten_keywords_defined() -> None:
    assert len(VALIDATION_COHORT_KEYWORDS) == 10
    assert "AI tools" in VALIDATION_COHORT_KEYWORDS
    assert "travel" in VALIDATION_COHORT_KEYWORDS


async def test_keyword_failure_does_not_block_other_results() -> None:
    ts = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)

    async def scan_fn(worker, keyword, client):
        if keyword == "bad":
            raise RuntimeError("scan failed")
        return (
            AnalysisScanResult(
                keyword=keyword,
                candidates=[_candidate(video_id=f"{keyword}-1", keyword=keyword)],
                pages_scanned=1,
                min_views=10_000,
                min_viral_coeff=3.0,
                upload_period="all",
            ),
            {"missing_video_count": 0},
        )

    with tempfile.TemporaryDirectory() as tmp:
        worker = MagicMock()
        results = await collect_validation_cohort(
            ["gaming", "bad", "travel"],
            worker=worker,
            youtube_client=MagicMock(),
            output_dir=Path(tmp),
            cohort_timestamp=ts,
            scan_keyword=scan_fn,
        )

    assert len(results) == 3
    assert results[0].status in {"SUCCESS", "PARTIAL"}
    assert results[1].status == "FAILED"
    assert results[2].status in {"SUCCESS", "PARTIAL"}


def test_per_keyword_jsonl_paths_are_unique() -> None:
    ts = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        paths = []
        for keyword in ["gaming", "AI tools"]:
            result = finalize_keyword_cohort_success(
                keyword=keyword,
                candidates=[_candidate(video_id=f"{keyword}-1", keyword=keyword)],
                output_dir=out,
                duration_seconds=1.0,
                missing_video_count=0,
                cohort_timestamp=ts,
            )
            paths.append(result.jsonl_path)
        assert len(set(paths)) == 2
        assert all(Path(path).exists() for path in paths)


def test_manifest_contains_all_keywords() -> None:
    ts = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
    results = [
        KeywordCohortResult(
            keyword=kw,
            status="SUCCESS",
            jsonl_path=f"/tmp/{keyword_output_slug(kw)}.jsonl",
            meta_path=f"/tmp/{keyword_output_slug(kw)}_meta.json",
            raw_candidates=10,
            regular_candidates=10,
            passed=1,
            rejected=9,
            invariant_ok=True,
            enrichment_summary={"enrichment_ok": 10, "enrichment_partial": 0, "enrichment_failed": 0},
        )
        for kw in VALIDATION_COHORT_KEYWORDS
    ]
    manifest = build_cohort_manifest_with_aggregates(
        keywords=list(VALIDATION_COHORT_KEYWORDS),
        results=results,
        cohort_timestamp=ts,
        total_duration_seconds=100.0,
        explosive_channels_before=12,
        explosive_channels_after=12,
    )
    assert len(manifest["per_keyword"]) == 10
    assert manifest["keywords_successful"] == 10
    assert manifest["totals"]["raw_candidates"] == 100


def test_raw_regular_excluded_counts_consistent() -> None:
    candidates = [
        _candidate(video_id="a", content_format="regular"),
        _candidate(video_id="b", content_format="short"),
        _candidate(video_id="c", content_format="unknown"),
    ]
    raw, regular = split_raw_and_regular(candidates)
    assert len(raw) == 3
    assert len(regular) == 1
    ts = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as tmp:
        result = finalize_keyword_cohort_success(
            keyword="gaming",
            candidates=candidates,
            output_dir=Path(tmp),
            duration_seconds=2.0,
            missing_video_count=0,
            cohort_timestamp=ts,
        )
    assert result.raw_candidates == 3
    assert result.regular_candidates == 1
    assert result.excluded_after_enrichment == 2


def test_invariant_preserved() -> None:
    candidates = [
        _candidate(video_id="p", state=QUALIFICATION_PASSED),
        _candidate(video_id="r", state=QUALIFICATION_REJECTED, first_failure_reason="min_views"),
    ]
    ts = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as tmp:
        result = finalize_keyword_cohort_success(
            keyword="gaming",
            candidates=candidates,
            output_dir=Path(tmp),
            duration_seconds=1.0,
            missing_video_count=0,
            cohort_timestamp=ts,
        )
    assert result.invariant_ok is True
    assert result.passed == 1
    assert result.rejected == 1


def test_format_violations_detected() -> None:
    candidates = [_candidate(is_short=True, content_format="short")]
    ts = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as tmp:
        result = finalize_keyword_cohort_success(
            keyword="gaming",
            candidates=candidates,
            output_dir=Path(tmp),
            duration_seconds=1.0,
            missing_video_count=0,
            cohort_timestamp=ts,
        )
    assert result.format_violations == 1
    assert result.regular_candidates == 0


def test_production_registration_disabled_in_manifest() -> None:
    ts = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
    manifest = build_cohort_manifest_with_aggregates(
        keywords=["gaming"],
        results=[
            KeywordCohortResult(keyword="gaming", status="SUCCESS", raw_candidates=1, regular_candidates=1),
        ],
        cohort_timestamp=ts,
        total_duration_seconds=1.0,
        explosive_channels_before=12,
        explosive_channels_after=12,
    )
    assert manifest["production_db_registration_occurred"] is False


def test_t0_discovery_fields_immutable_in_export() -> None:
    candidate = _candidate()
    candidate.discovery_views = 20_000
    candidate.views = 20_000
    ts = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as tmp:
        result = finalize_keyword_cohort_success(
            keyword="gaming",
            candidates=[candidate],
            output_dir=Path(tmp),
            duration_seconds=1.0,
            missing_video_count=0,
            cohort_timestamp=ts,
        )
        record = json.loads(Path(result.jsonl_path).read_text(encoding="utf-8").strip())
    assert record["discovery_views"] == 20_000
    assert record["discovered_at"].endswith("+00:00")
    assert record["video_id"] == "vid1"


def test_failed_keyword_in_manifest() -> None:
    ts = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
    results = [
        finalize_keyword_cohort_failure(
            keyword="broken",
            error_type="RuntimeError",
            error_message="boom",
            duration_seconds=3.0,
        ),
    ]
    manifest = build_cohort_manifest_with_aggregates(
        keywords=["broken"],
        results=results,
        cohort_timestamp=ts,
        total_duration_seconds=3.0,
        explosive_channels_before=12,
        explosive_channels_after=12,
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = write_cohort_manifest(manifest, output_dir=Path(tmp), cohort_timestamp=ts)
        loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["keywords_failed"] == 1
    assert loaded["per_keyword"][0]["status"] == "FAILED"
    assert loaded["per_keyword"][0]["error_message"] == "boom"


def test_determine_keyword_status_partial_on_exclusions() -> None:
    assert determine_keyword_status(
        error_type=None,
        invariant_ok=True,
        excluded_after_enrichment=2,
        enrichment_failed=0,
    ) == "PARTIAL"


async def main() -> None:
    sync_tests = [
        test_all_ten_keywords_defined,
        test_per_keyword_jsonl_paths_are_unique,
        test_manifest_contains_all_keywords,
        test_raw_regular_excluded_counts_consistent,
        test_invariant_preserved,
        test_format_violations_detected,
        test_production_registration_disabled_in_manifest,
        test_t0_discovery_fields_immutable_in_export,
        test_failed_keyword_in_manifest,
        test_determine_keyword_status_partial_on_exclusions,
    ]
    async_tests = [test_keyword_failure_does_not_block_other_results]
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
    print("All validation cohort tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
