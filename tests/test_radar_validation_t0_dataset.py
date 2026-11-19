"""Tests for T0 cohort export and enrichment diagnostics (Stage 1.8 Step 3)."""

from __future__ import annotations

import asyncio
import copy
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.youtube.client import YouTubeVideoDetails
from app.services.radar_candidate import (
    DISCOVERY_SOURCE_INNERTUBE,
    QUALIFICATION_PARSE_ERROR,
    QUALIFICATION_PASSED,
    QUALIFICATION_REJECTED,
    RadarCandidate,
)
from app.services.radar_candidate_enrichment import enrich_radar_candidates, enrich_single_candidate
from app.services.radar_validation_t0_dataset import (
    T0_ENRICHMENT_FIELDS,
    T0_JSONL_FIELDS,
    T0_QUALIFICATION_FIELDS,
    build_enrichment_summary,
    export_cohort_t0_jsonl,
    persist_validation_t0_dataset,
    serialize_t0_candidate,
)


def _candidate(
    *,
    video_id: str = "vid1",
    discovery_views: int = 10_000,
    discovery_subscribers: int = 0,
    final_subscribers: int | None = None,
    subscriber_fetch_status: str | None = "not_attempted",
    state: str = QUALIFICATION_PASSED,
    reason: str | None = None,
    is_short: bool = False,
    is_live: bool = False,
) -> RadarCandidate:
    return RadarCandidate(
        video_id=video_id,
        channel_id="UC1234567890123456789012",
        keyword="gaming",
        discovery_source=DISCOVERY_SOURCE_INNERTUBE,
        discovered_at=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
        video_title="Title",
        channel_title="Channel",
        discovery_views=discovery_views,
        discovery_subscribers=discovery_subscribers,
        discovery_published_text="2 hours ago",
        views=discovery_views,
        subscribers=discovery_subscribers,
        final_subscribers=final_subscribers,
        subscriber_fetch_status=subscriber_fetch_status,
        qualification_state=state,
        first_failure_reason=reason,
        is_short=is_short,
        is_live=is_live,
    )


def _details(
    *,
    video_id: str = "vid1",
    published_at: datetime | None = None,
    duration_seconds: int = 600,
) -> YouTubeVideoDetails:
    return YouTubeVideoDetails(
        video_id=video_id,
        channel_id="UC1234567890123456789012",
        title="Title",
        published_at=published_at or datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc),
        views_count=20_000,
        likes_count=0,
        comments_count=0,
        duration_seconds=duration_seconds,
    )


def test_t0_jsonl_contains_all_required_fields() -> None:
    candidate = _candidate(final_subscribers=2000, subscriber_fetch_status="homepage_fetched")
    enrich_single_candidate(candidate, _details())
    record = serialize_t0_candidate(candidate)

    for field in T0_JSONL_FIELDS:
        assert field in record, f"missing field: {field}"

    assert set(record.keys()) == set(T0_JSONL_FIELDS)


def test_discovery_fields_immutable_after_enrichment_and_export() -> None:
    candidate = _candidate(discovery_views=20_000)
    before = copy.deepcopy(candidate)
    enrich_single_candidate(candidate, _details())

    record = serialize_t0_candidate(candidate)
    assert record["discovery_views"] == before.discovery_views == 20_000
    assert record["discovered_at"] == before.discovered_at.isoformat()
    assert record["discovery_subscribers"] == before.discovery_subscribers
    assert record["discovery_published_text"] == before.discovery_published_text


def test_nullable_enrichment_not_coerced_to_zero() -> None:
    candidate = _candidate(final_subscribers=None, subscriber_fetch_status="unavailable")
    enrich_single_candidate(candidate, None)
    record = serialize_t0_candidate(candidate)

    assert record["final_subscribers"] is None
    assert record["published_at"] is None
    assert record["age_hours_at_t0"] is None
    assert record["vph_at_t0"] is None
    assert record["views_per_subscriber_at_t0"] is None
    assert record["duration_seconds"] is None
    assert record["enrichment_status"] == "failed"


def test_enrichment_summary_counts_statuses() -> None:
    ok_candidate = _candidate(video_id="ok")
    partial_candidate = _candidate(video_id="partial")
    failed_candidate = _candidate(video_id="failed")
    missing_candidate = _candidate(video_id="missing")

    enrich_single_candidate(ok_candidate, _details(video_id="ok"))
    enrich_single_candidate(
        partial_candidate,
        _details(
            video_id="partial",
            published_at=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
        ),
    )
    enrich_single_candidate(failed_candidate, None)
    enrich_single_candidate(missing_candidate, None)

    summary = build_enrichment_summary(
        [ok_candidate, partial_candidate, failed_candidate, missing_candidate],
        missing_video_count=2,
    )

    assert summary["candidates_total"] == 4
    assert summary["enrichment_ok"] == 1
    assert summary["enrichment_partial"] == 1
    assert summary["enrichment_failed"] == 2
    assert summary["missing_video"] == 2
    assert summary["published_at_available"] == 2
    assert summary["duration_available"] == 2
    assert summary["age_hours_available"] == 2
    assert summary["vph_available"] == 1
    assert summary["regular_count"] == 2
    assert summary["unknown_count"] == 2


def test_dataset_export_does_not_write_to_db() -> None:
    candidates = [
        _candidate(video_id="a", state=QUALIFICATION_PASSED),
        _candidate(
            video_id="b",
            state=QUALIFICATION_REJECTED,
            reason="min_views",
        ),
    ]
    for candidate in candidates:
        enrich_single_candidate(candidate, _details(video_id=candidate.video_id))

    session_mock = MagicMock()
    with patch("app.models.db.SessionLocal", return_value=session_mock):
        with tempfile.TemporaryDirectory() as tmp:
            path, enrichment_summary, dataset_summary = persist_validation_t0_dataset(
                candidates,
                keyword="gaming",
                output_dir=Path(tmp),
            )
            session_mock.assert_not_called()
            assert path.exists()
            assert enrichment_summary["candidates_total"] == 2
            assert dataset_summary["invariant_ok"] is True


def test_invariant_preserved_in_dataset_summary() -> None:
    candidates = [
        _candidate(video_id="pass", state=QUALIFICATION_PASSED),
        _candidate(video_id="reject", state=QUALIFICATION_REJECTED, reason="min_views"),
        _candidate(
            video_id="err",
            state=QUALIFICATION_PARSE_ERROR,
            reason="parse_error",
        ),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        path, _, dataset_summary = persist_validation_t0_dataset(
            candidates,
            keyword="gaming",
            output_dir=Path(tmp),
        )

        assert dataset_summary["candidate_count"] == 3
        assert dataset_summary["passed"] == 1
        assert dataset_summary["rejected"] == 1
        assert dataset_summary["parse_errors"] == 1
        assert dataset_summary["invariant_ok"] is True
        assert dataset_summary["path"] == str(path)

        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 3
        first = json.loads(lines[0])
        for field in T0_ENRICHMENT_FIELDS + T0_QUALIFICATION_FIELDS:
            assert field in first


def test_export_cohort_t0_jsonl_filename_pattern() -> None:
    candidates = [_candidate(state=QUALIFICATION_PASSED)]
    ts = datetime(2026, 9, 12, 10, 30, 45, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as tmp:
        path = export_cohort_t0_jsonl(
            candidates,
            keyword="gaming",
            output_dir=Path(tmp),
            timestamp=ts,
        )
    assert path.name == "cohort_T0_20260912_103045_gaming.jsonl"


def test_enrich_radar_candidates_reports_missing_video_count() -> None:
    candidates = [_candidate(video_id="found"), _candidate(video_id="missing")]
    client = MagicMock()
    client.get_videos.return_value = [_details(video_id="found")]
    result = enrich_radar_candidates(candidates, client)
    assert result["missing_video_count"] == 1
    assert candidates[0].enrichment_status == "ok"
    assert candidates[1].enrichment_status == "failed"


async def main() -> None:
    tests = [
        test_t0_jsonl_contains_all_required_fields,
        test_discovery_fields_immutable_after_enrichment_and_export,
        test_nullable_enrichment_not_coerced_to_zero,
        test_enrichment_summary_counts_statuses,
        test_dataset_export_does_not_write_to_db,
        test_invariant_preserved_in_dataset_summary,
        test_export_cohort_t0_jsonl_filename_pattern,
        test_enrich_radar_candidates_reports_missing_video_count,
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
    print("All validation T0 dataset tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
