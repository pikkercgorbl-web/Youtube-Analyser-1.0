"""Tests for dual-layer T0 capture on RadarCandidate (Stage 1.8 Step 2)."""

from __future__ import annotations

import asyncio
import copy
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.youtube.client import VideoSearchModel
from app.models.orm import ExplosiveChannelSettings
from app.services.explosive_channels_service import (
    DEFAULT_MIN_VIEWS,
    DEFAULT_MIN_VIRAL_COEFF,
    ExplosiveChannelThresholds,
    ExplosiveChannelsService,
)
from app.services.radar_candidate import (
    DISCOVERY_SOURCE_INNERTUBE,
    QUALIFICATION_PASSED,
    QUALIFICATION_REJECTED,
    RadarCandidate,
    RadarVideoOutcome,
    apply_subscriber_enrichment,
    apply_video_outcomes,
)
from app.services.radar_candidate_dataset import serialize_candidate
from app.services.radar_filter_metrics import FILTER_SKIP_MIN_VIRAL_COEFF


def _video(
    *,
    views_count: int = 20_000,
    subscribers_count: int = 0,
    published_text: str = "2 days ago",
) -> VideoSearchModel:
    return VideoSearchModel(
        video_id="vid123",
        channel_id="UC1234567890123456789012",
        channel_title="Channel",
        title="Test video",
        views_count=views_count,
        subscribers_count=subscribers_count,
        published_text=published_text,
    )


def test_discovery_snapshot_preserved_at_creation() -> None:
    discovered_at = datetime(2026, 9, 12, 10, 30, 15, tzinfo=timezone.utc)
    candidate = RadarCandidate.from_video_search(
        _video(views_count=20_000, subscribers_count=500),
        keyword="gaming",
        discovery_source=DISCOVERY_SOURCE_INNERTUBE,
        discovered_at=discovered_at,
    )
    assert candidate.discovery_views == 20_000
    assert candidate.discovery_subscribers == 500
    assert candidate.discovery_published_text == "2 days ago"
    assert candidate.discovered_at == discovered_at
    assert candidate.views == 20_000
    assert candidate.subscribers == 500


def test_subscriber_enrichment_preserves_discovery_and_sets_final() -> None:
    candidate = RadarCandidate.from_video_search(
        _video(subscribers_count=0),
        keyword="gaming",
        discovery_source=DISCOVERY_SOURCE_INNERTUBE,
    )
    cache = {"UC1234567890123456789012": 25_000}
    apply_subscriber_enrichment([candidate], cache)
    assert candidate.discovery_subscribers == 0
    assert candidate.final_subscribers == 25_000
    assert candidate.subscriber_fetch_status == "homepage_fetched"


def test_subscriber_enrichment_unavailable_is_null_not_zero() -> None:
    candidate = RadarCandidate.from_video_search(
        _video(subscribers_count=0),
        keyword="gaming",
        discovery_source=DISCOVERY_SOURCE_INNERTUBE,
    )
    cache = {"UC1234567890123456789012": None}
    apply_subscriber_enrichment([candidate], cache)
    assert candidate.final_subscribers is None
    assert candidate.subscriber_fetch_status == "unavailable"


def test_discovery_subscribers_used_as_final_without_homepage_fetch() -> None:
    candidate = RadarCandidate.from_video_search(
        _video(subscribers_count=12_000),
        keyword="gaming",
        discovery_source=DISCOVERY_SOURCE_INNERTUBE,
    )
    apply_subscriber_enrichment([candidate], {})
    assert candidate.final_subscribers == 12_000
    assert candidate.subscriber_fetch_status == "discovery"


def test_t0_immutability_after_enrichment() -> None:
    discovered_at = datetime(2026, 9, 12, 10, 30, 15, tzinfo=timezone.utc)
    candidate = RadarCandidate.from_video_search(
        _video(views_count=20_000, subscribers_count=0),
        keyword="gaming",
        discovery_source=DISCOVERY_SOURCE_INNERTUBE,
        discovered_at=discovered_at,
    )
    before = copy.deepcopy(candidate)
    apply_subscriber_enrichment([candidate], {"UC1234567890123456789012": 25_000})

    candidate.views = 20_500
    candidate.subscribers = 99_999
    candidate.published_text = "changed"

    assert candidate.discovery_views == before.discovery_views == 20_000
    assert candidate.discovered_at == before.discovered_at == discovered_at
    assert candidate.discovery_subscribers == before.discovery_subscribers == 0
    assert candidate.discovery_published_text == before.discovery_published_text


def test_jsonl_serialization_exports_subscriber_layers() -> None:
    candidate = RadarCandidate.from_video_search(
        _video(subscribers_count=0),
        keyword="gaming",
        discovery_source=DISCOVERY_SOURCE_INNERTUBE,
    )
    apply_subscriber_enrichment([candidate], {"UC1234567890123456789012": 25_000})
    record = serialize_candidate(candidate)
    assert record["discovery_subscribers"] == 0
    assert record["final_subscribers"] == 25_000
    assert record["discovery_views"] == 20_000
    assert record["subscriber_fetch_status"] == "homepage_fetched"


def test_qualification_outcomes_unchanged_by_subscriber_enrichment() -> None:
    candidate = RadarCandidate.from_video_search(
        _video(subscribers_count=0),
        keyword="gaming",
        discovery_source=DISCOVERY_SOURCE_INNERTUBE,
    )
    outcomes = [
        RadarVideoOutcome(
            candidate.video_id,
            QUALIFICATION_REJECTED,
            FILTER_SKIP_MIN_VIRAL_COEFF,
        ),
    ]
    apply_video_outcomes([candidate], outcomes)
    apply_subscriber_enrichment([candidate], {"UC1234567890123456789012": 25_000})
    assert candidate.qualification_state == QUALIFICATION_REJECTED
    assert candidate.first_failure_reason == FILTER_SKIP_MIN_VIRAL_COEFF


async def test_qualification_behavior_unchanged_with_real_service() -> None:
    service = ExplosiveChannelsService()
    db = MagicMock()
    video = VideoSearchModel(
        video_id="pass",
        channel_id="UC1234567890123456789012",
        channel_title="Channel",
        title="Video",
        views_count=100_000,
        subscribers_count=0,
        published_text="3 days ago",
    )
    settings = ExplosiveChannelSettings(
        id=1,
        max_age_days=180,
        min_views=DEFAULT_MIN_VIEWS,
        min_viral_coeff=DEFAULT_MIN_VIRAL_COEFF,
        upload_period="all",
    )
    thresholds = ExplosiveChannelThresholds(
        min_views=DEFAULT_MIN_VIEWS,
        min_viral_coeff=DEFAULT_MIN_VIRAL_COEFF,
    )
    cache: dict[str, int | None] = {"UC1234567890123456789012": 10_000}

    with patch.object(service, "_get_or_create_settings", return_value=settings):
        with patch.object(service, "get_thresholds", return_value=thresholds):
            with patch(
                "app.services.explosive_channels_service.fetch_channel_subscribers_from_homepage",
                new_callable=AsyncMock,
            ) as fetch:
                with patch(
                    "app.services.explosive_channels_service.asyncio.sleep",
                    new_callable=AsyncMock,
                ):
                    result = await service.process_radar_videos(
                        db,
                        [video],
                        register_channels=False,
                        collect_video_outcomes=True,
                        subscriber_cache=cache,
                    )

    fetch.assert_not_called()
    candidate = RadarCandidate.from_video_search(
        video,
        keyword="gaming",
        discovery_source=DISCOVERY_SOURCE_INNERTUBE,
    )
    apply_video_outcomes([candidate], list(result.video_outcomes))
    apply_subscriber_enrichment([candidate], cache)
    assert result.passed_count == 1
    assert candidate.qualification_state == QUALIFICATION_PASSED
    assert candidate.discovery_subscribers == 0
    assert candidate.final_subscribers == 10_000


async def main() -> None:
    sync_tests = [
        test_discovery_snapshot_preserved_at_creation,
        test_subscriber_enrichment_preserves_discovery_and_sets_final,
        test_subscriber_enrichment_unavailable_is_null_not_zero,
        test_discovery_subscribers_used_as_final_without_homepage_fetch,
        test_t0_immutability_after_enrichment,
        test_jsonl_serialization_exports_subscriber_layers,
        test_qualification_outcomes_unchanged_by_subscriber_enrichment,
    ]
    async_tests = [test_qualification_behavior_unchanged_with_real_service]

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
    print("All validation T0 capture tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
