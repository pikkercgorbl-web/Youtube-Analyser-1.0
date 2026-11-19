"""Tests for post-discovery T0 enrichment (Stage 1.8 Step 3)."""

from __future__ import annotations

import asyncio
import copy
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.youtube.client import YouTubeVideoDetails
from app.services.radar_candidate import DISCOVERY_SOURCE_INNERTUBE, RadarCandidate
from app.services.radar_candidate_dataset import serialize_candidate
from app.services.radar_candidate_enrichment import (
    calc_age_hours_at_t0,
    calc_vph_at_t0,
    calc_views_per_subscriber_at_t0,
    classify_content_format,
    enrich_radar_candidates,
    enrich_single_candidate,
)


def _candidate(
    *,
    video_id: str = "vid1",
    discovery_views: int = 10_000,
    final_subscribers: int | None = None,
    is_live: bool = False,
    is_short: bool = False,
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
        discovery_subscribers=0,
        discovery_published_text="2 hours ago",
        views=discovery_views,
        subscribers=0,
        is_live=is_live,
        is_short=is_short,
        final_subscribers=final_subscribers,
    )


def _details(
    *,
    video_id: str = "vid1",
    published_at: datetime | None = None,
    duration_seconds: int = 600,
    views_count: int = 20_000,
) -> YouTubeVideoDetails:
    return YouTubeVideoDetails(
        video_id=video_id,
        channel_id="UC1234567890123456789012",
        title="Title",
        published_at=published_at or datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc),
        views_count=views_count,
        likes_count=0,
        comments_count=0,
        duration_seconds=duration_seconds,
    )


def test_exact_age_from_published_at() -> None:
    discovered_at = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
    published_at = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
    assert calc_age_hours_at_t0(discovered_at, published_at) == 2.0


def test_vph_at_t0_calculation() -> None:
    assert calc_vph_at_t0(10_000, 2.0) == 5000.0


def test_vph_uses_discovery_views_not_api_views() -> None:
    candidate = _candidate(discovery_views=10_000)
    enrich_single_candidate(candidate, _details(views_count=20_000, duration_seconds=600))
    assert candidate.vph_at_t0 == 5000.0
    assert candidate.discovery_views == 10_000


def test_views_per_subscriber_at_t0() -> None:
    candidate = _candidate(discovery_views=10_000, final_subscribers=2000)
    enrich_single_candidate(candidate, _details())
    assert candidate.views_per_subscriber_at_t0 == 5.0


def test_views_per_subscriber_null_when_zero_subscribers() -> None:
    candidate = _candidate(final_subscribers=0)
    enrich_single_candidate(candidate, _details())
    assert candidate.views_per_subscriber_at_t0 is None


def test_views_per_subscriber_null_when_missing_subscribers() -> None:
    candidate = _candidate(final_subscribers=None)
    enrich_single_candidate(candidate, _details())
    assert candidate.views_per_subscriber_at_t0 is None


def test_non_positive_age_does_not_create_vph() -> None:
    candidate = _candidate(discovery_views=10_000)
    same_time = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
    enrich_single_candidate(candidate, _details(published_at=same_time))
    assert candidate.vph_at_t0 is None
    assert candidate.enrichment_status == "partial"


def test_duration_short_classification() -> None:
    candidate = _candidate()
    assert classify_content_format(candidate, 30) == "short"


def test_duration_regular_classification() -> None:
    candidate = _candidate()
    assert classify_content_format(candidate, 600) == "regular"


def test_live_classification_from_discovery_flag() -> None:
    candidate = _candidate(is_live=True)
    assert classify_content_format(candidate, 600) == "live"


def test_missing_api_result_keeps_candidate_with_failed_status() -> None:
    candidate = _candidate()
    enrich_single_candidate(candidate, None)
    assert candidate.enrichment_status == "failed"
    assert candidate.published_at is None
    assert candidate.duration_seconds is None
    assert candidate.video_id == "vid1"


def test_t0_immutability_after_enrichment() -> None:
    candidate = _candidate(discovery_views=20_000)
    before = copy.deepcopy(candidate)
    enrich_single_candidate(candidate, _details(views_count=99_999))
    assert candidate.discovery_views == before.discovery_views == 20_000
    assert candidate.discovered_at == before.discovered_at
    assert candidate.discovery_subscribers == before.discovery_subscribers
    assert candidate.discovery_published_text == before.discovery_published_text


def test_jsonl_serialization_exports_enrichment_fields() -> None:
    candidate = _candidate(final_subscribers=2000)
    enrich_single_candidate(candidate, _details())
    record = serialize_candidate(candidate)
    assert record["published_at"] is not None
    assert record["age_hours_at_t0"] == 2.0
    assert record["vph_at_t0"] == 5000.0
    assert record["views_per_subscriber_at_t0"] == 5.0
    assert record["duration_seconds"] == 600
    assert record["content_format"] == "regular"
    assert record["enrichment_status"] == "ok"


def test_enrich_radar_candidates_batch_no_db_writes() -> None:
    candidates = [_candidate(video_id="a"), _candidate(video_id="b")]
    client = MagicMock()
    client.get_videos.return_value = [
        _details(video_id="a"),
        _details(video_id="b"),
    ]
    enrich_radar_candidates(candidates, client)
    client.get_videos.assert_called_once()
    assert all(candidate.enrichment_status == "ok" for candidate in candidates)


async def main() -> None:
    tests = [
        test_exact_age_from_published_at,
        test_vph_at_t0_calculation,
        test_vph_uses_discovery_views_not_api_views,
        test_views_per_subscriber_at_t0,
        test_views_per_subscriber_null_when_zero_subscribers,
        test_views_per_subscriber_null_when_missing_subscribers,
        test_non_positive_age_does_not_create_vph,
        test_duration_short_classification,
        test_duration_regular_classification,
        test_live_classification_from_discovery_flag,
        test_missing_api_result_keeps_candidate_with_failed_status,
        test_t0_immutability_after_enrichment,
        test_jsonl_serialization_exports_enrichment_fields,
        test_enrich_radar_candidates_batch_no_db_writes,
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
    print("All validation enrichment tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
