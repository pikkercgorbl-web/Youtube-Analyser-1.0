"""Smoke tests for in-memory RadarCandidate layer (Stage 1.1)."""

from __future__ import annotations

import asyncio
import sys
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
    RadarChannelHit,
)
from app.services.radar_candidate import (
    DISCOVERY_SOURCE_INNERTUBE,
    QUALIFICATION_PASSED,
    QUALIFICATION_PENDING,
    QUALIFICATION_REJECTED,
    RadarCandidate,
    RadarVideoOutcome,
    apply_signal_snapshot,
    apply_video_outcomes,
    build_candidate_summary,
)
from app.services.radar_filter_metrics import FILTER_SKIP_MIN_VIEWS

SETTINGS = ExplosiveChannelSettings(
    id=1,
    max_age_days=180,
    min_views=DEFAULT_MIN_VIEWS,
    min_viral_coeff=DEFAULT_MIN_VIRAL_COEFF,
    upload_period="all",
)
THRESHOLDS = ExplosiveChannelThresholds(
    min_views=DEFAULT_MIN_VIEWS,
    min_viral_coeff=DEFAULT_MIN_VIRAL_COEFF,
)
HIT = RadarChannelHit(channel_name="Test Channel", viral_coefficient=10.0)


def _video(
    *,
    video_id: str = "vid1",
    channel_id: str = "UC1234567890123456789012",
    title: str = "Test video",
    views_count: int = 100_000,
    subscribers_count: int = 10_000,
    published_text: str = "3 days ago",
) -> VideoSearchModel:
    return VideoSearchModel(
        video_id=video_id,
        channel_id=channel_id,
        channel_title="Test Channel",
        title=title,
        views_count=views_count,
        subscribers_count=subscribers_count,
        published_text=published_text,
    )


def test_viral_coefficient_calculated() -> None:
    candidate = RadarCandidate.from_video_search(
        _video(views_count=10_000, subscribers_count=500),
        keyword="test",
        discovery_source=DISCOVERY_SOURCE_INNERTUBE,
    )
    apply_signal_snapshot(candidate)
    assert candidate.viral_coefficient == 20.0


def test_viral_coefficient_zero_subscribers() -> None:
    candidate = RadarCandidate.from_video_search(
        _video(subscribers_count=0),
        keyword="test",
        discovery_source=DISCOVERY_SOURCE_INNERTUBE,
    )
    apply_signal_snapshot(candidate)
    assert candidate.viral_coefficient is None


def test_viral_coefficient_missing_subscribers() -> None:
    candidate = RadarCandidate.from_video_search(
        _video(),
        keyword="test",
        discovery_source=DISCOVERY_SOURCE_INNERTUBE,
    )
    candidate.subscribers = None
    apply_signal_snapshot(candidate)
    assert candidate.viral_coefficient is None


def test_unavailable_signals_are_none_not_zero() -> None:
    candidate = RadarCandidate.from_video_search(
        _video(subscribers_count=0, published_text=""),
        keyword="test",
        discovery_source=DISCOVERY_SOURCE_INNERTUBE,
    )
    apply_signal_snapshot(candidate)
    assert candidate.viral_coefficient is None
    assert candidate.vph is None
    assert candidate.video_age_days is None


async def test_rejected_candidate_still_has_signals() -> None:
    service = ExplosiveChannelsService()
    db = MagicMock()
    video = _video(video_id="reject", views_count=12_000, subscribers_count=500)
    candidate = RadarCandidate.from_video_search(
        video,
        keyword="test",
        discovery_source=DISCOVERY_SOURCE_INNERTUBE,
    )
    apply_signal_snapshot(candidate)

    with patch.object(service, "_get_or_create_settings", return_value=SETTINGS):
        with patch.object(service, "get_thresholds", return_value=THRESHOLDS):
            with patch(
                "app.services.explosive_channels_service.fetch_channel_subscribers_from_homepage",
                new_callable=AsyncMock,
                return_value=None,
            ):
                with patch(
                    "app.services.explosive_channels_service.asyncio.sleep",
                    new_callable=AsyncMock,
                ):
                    result = await service.process_radar_videos(
                        db,
                        [video],
                        collect_video_outcomes=True,
                    )

    apply_video_outcomes([candidate], list(result.video_outcomes))
    assert candidate.qualification_state == QUALIFICATION_REJECTED
    assert candidate.first_failure_reason == FILTER_SKIP_MIN_VIEWS
    assert candidate.viral_coefficient == 24.0
    assert candidate.vph is not None
    assert candidate.video_age_days == 3.0
    assert result.passed_count == 0
    assert result.skipped_count == 1


def test_candidate_summary_includes_signal_availability() -> None:
    candidate = RadarCandidate.from_video_search(
        _video(views_count=10_000, subscribers_count=500, published_text="2 days ago"),
        keyword="minecraft",
        discovery_source=DISCOVERY_SOURCE_INNERTUBE,
    )
    apply_signal_snapshot(candidate)
    summary = build_candidate_summary("minecraft", [candidate])
    assert summary["signal_availability"]["viral_coefficient"] == 1
    assert summary["signal_availability"]["vph"] == 1
    assert summary["signal_availability"]["video_age_days"] == 1
    assert "signal_ranges" in summary


def test_candidate_from_video_search_defaults_pending() -> None:
    video = _video()
    candidate = RadarCandidate.from_video_search(
        video,
        keyword="minecraft",
        discovery_source=DISCOVERY_SOURCE_INNERTUBE,
    )
    assert candidate.video_id == "vid1"
    assert candidate.channel_id == video.channel_id
    assert candidate.keyword == "minecraft"
    assert candidate.discovery_source == DISCOVERY_SOURCE_INNERTUBE
    assert candidate.views == 100_000
    assert candidate.subscribers == 10_000
    assert candidate.format_passed is True
    assert candidate.qualification_state == QUALIFICATION_PENDING
    assert candidate.first_failure_reason is None


def test_apply_rejected_outcome() -> None:
    candidate = RadarCandidate.from_video_search(
        _video(),
        keyword="test",
        discovery_source=DISCOVERY_SOURCE_INNERTUBE,
    )
    apply_video_outcomes(
        [candidate],
        [
            RadarVideoOutcome(
                candidate.video_id,
                QUALIFICATION_REJECTED,
                FILTER_SKIP_MIN_VIEWS,
            ),
        ],
    )
    assert candidate.qualification_state == QUALIFICATION_REJECTED
    assert candidate.first_failure_reason == FILTER_SKIP_MIN_VIEWS


def test_apply_passed_outcome() -> None:
    candidate = RadarCandidate.from_video_search(
        _video(),
        keyword="test",
        discovery_source=DISCOVERY_SOURCE_INNERTUBE,
    )
    apply_video_outcomes(
        [candidate],
        [RadarVideoOutcome(candidate.video_id, QUALIFICATION_PASSED, None)],
    )
    assert candidate.qualification_state == QUALIFICATION_PASSED
    assert candidate.first_failure_reason is None


def test_apply_outcomes_matches_by_video_id() -> None:
    first = RadarCandidate.from_video_search(
        _video(video_id="a"),
        keyword="test",
        discovery_source=DISCOVERY_SOURCE_INNERTUBE,
    )
    second = RadarCandidate.from_video_search(
        _video(video_id="b"),
        keyword="test",
        discovery_source=DISCOVERY_SOURCE_INNERTUBE,
    )
    apply_video_outcomes(
        [first, second],
        [
            RadarVideoOutcome("b", QUALIFICATION_PASSED, None),
            RadarVideoOutcome("a", QUALIFICATION_REJECTED, FILTER_SKIP_MIN_VIEWS),
        ],
    )
    assert first.qualification_state == QUALIFICATION_REJECTED
    assert second.qualification_state == QUALIFICATION_PASSED


def test_candidate_summary_counts_match_outcomes() -> None:
    candidates = [
        RadarCandidate.from_video_search(
            _video(video_id="pass"),
            keyword="minecraft",
            discovery_source=DISCOVERY_SOURCE_INNERTUBE,
        ),
        RadarCandidate.from_video_search(
            _video(video_id="reject1"),
            keyword="minecraft",
            discovery_source=DISCOVERY_SOURCE_INNERTUBE,
        ),
        RadarCandidate.from_video_search(
            _video(video_id="reject2"),
            keyword="minecraft",
            discovery_source=DISCOVERY_SOURCE_INNERTUBE,
        ),
    ]
    apply_video_outcomes(
        candidates,
        [
            RadarVideoOutcome("pass", QUALIFICATION_PASSED, None),
            RadarVideoOutcome("reject1", QUALIFICATION_REJECTED, FILTER_SKIP_MIN_VIEWS),
            RadarVideoOutcome("reject2", QUALIFICATION_REJECTED, "min_viral_coeff"),
        ],
    )
    summary = build_candidate_summary("minecraft", candidates)
    assert summary["candidate_count"] == 3
    assert summary["passed_count"] == 1
    assert summary["rejected_count"] == 2
    assert summary["parse_error_count"] == 0
    assert summary["rejection_reasons"] == {
        "min_views": 1,
        "min_viral_coeff": 1,
    }


async def test_qualification_unchanged_without_outcome_collection() -> None:
    service = ExplosiveChannelsService()
    db = MagicMock()
    videos = [
        _video(video_id="reject", views_count=1_000),
        _video(video_id="pass", views_count=100_000, subscribers_count=10_000),
    ]

    with patch.object(service, "_get_or_create_settings", return_value=SETTINGS):
        with patch.object(service, "get_thresholds", return_value=THRESHOLDS):
            with patch.object(service, "_register_channel_video", return_value=HIT):
                with patch(
                    "app.services.explosive_channels_service.fetch_channel_subscribers_from_homepage",
                    new_callable=AsyncMock,
                    return_value=None,
                ):
                    with patch(
                        "app.services.explosive_channels_service.asyncio.sleep",
                        new_callable=AsyncMock,
                    ):
                        without = await service.process_radar_videos(db, videos)
                        with_outcomes = await service.process_radar_videos(
                            db,
                            videos,
                            collect_video_outcomes=True,
                        )

    assert without.skipped_count == with_outcomes.skipped_count
    assert without.passed_count == with_outcomes.passed_count
    assert without.parse_error_count == with_outcomes.parse_error_count
    assert len(without.hits) == len(with_outcomes.hits)
    assert without.video_outcomes == ()
    assert len(with_outcomes.video_outcomes) == 2
    assert with_outcomes.video_outcomes[0].first_failure_reason == FILTER_SKIP_MIN_VIEWS
    assert with_outcomes.video_outcomes[1].qualification_state == QUALIFICATION_PASSED


async def main() -> None:
    sync_tests = [
        test_viral_coefficient_calculated,
        test_viral_coefficient_zero_subscribers,
        test_viral_coefficient_missing_subscribers,
        test_unavailable_signals_are_none_not_zero,
        test_candidate_summary_includes_signal_availability,
        test_candidate_from_video_search_defaults_pending,
        test_apply_rejected_outcome,
        test_apply_passed_outcome,
        test_apply_outcomes_matches_by_video_id,
        test_candidate_summary_counts_match_outcomes,
    ]
    async_tests = [
        test_rejected_candidate_still_has_signals,
        test_qualification_unchanged_without_outcome_collection,
    ]

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
    print("All radar candidate tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
