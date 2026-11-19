"""Smoke tests for radar qualification filter metrics (Stage 0)."""

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
from app.services.radar_filter_metrics import (
    FILTER_SKIP_LANGUAGE,
    FILTER_SKIP_MIN_SUBSCRIBERS,
    FILTER_SKIP_MIN_VIEWS,
    FILTER_SKIP_MIN_VIRAL_COEFF,
    RadarFilterMetrics,
)

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
) -> VideoSearchModel:
    return VideoSearchModel(
        video_id=video_id,
        channel_id=channel_id,
        channel_title="Test Channel",
        title=title,
        views_count=views_count,
        subscribers_count=subscribers_count,
        published_text="3 days ago",
    )


async def _process(
    videos: list[VideoSearchModel],
    *,
    filter_metrics: RadarFilterMetrics | None = None,
    upload_period: str = "all",
    blacklist_words: list[str] | None = None,
    filter_title_language: bool = True,
) -> tuple[object, RadarFilterMetrics]:
    service = ExplosiveChannelsService()
    db = MagicMock()
    metrics = filter_metrics or RadarFilterMetrics.empty()

    with patch.object(service, "_get_or_create_settings", return_value=SETTINGS):
        with patch.object(service, "get_thresholds", return_value=THRESHOLDS):
            with patch.object(
                service,
                "_register_channel_video",
                return_value=HIT,
            ) as register_mock:
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
                            videos,
                            upload_period=upload_period,
                            blacklist_words=blacklist_words,
                            filter_title_language=filter_title_language,
                            filter_metrics=metrics,
                        )
    return result, metrics, register_mock


async def test_skip_min_views() -> None:
    result, metrics, register_mock = await _process([_video(views_count=1_000)])
    assert result.skipped_count == 1
    assert result.passed_count == 0
    assert metrics.filter_skip_reasons.get(FILTER_SKIP_MIN_VIEWS) == 1
    register_mock.assert_not_called()


async def test_skip_min_subscribers() -> None:
    result, metrics, register_mock = await _process([_video(subscribers_count=0)])
    assert result.skipped_count == 1
    assert result.passed_count == 0
    assert metrics.filter_skip_reasons.get(FILTER_SKIP_MIN_SUBSCRIBERS) == 1
    register_mock.assert_not_called()


async def test_skip_min_viral_coeff() -> None:
    # 60k views / 100k subs = 0.6x < 3.0x
    result, metrics, register_mock = await _process(
        [_video(views_count=60_000, subscribers_count=100_000)],
    )
    assert result.skipped_count == 1
    assert result.passed_count == 0
    assert metrics.filter_skip_reasons.get(FILTER_SKIP_MIN_VIRAL_COEFF) == 1
    register_mock.assert_not_called()


async def test_skip_language() -> None:
    result, metrics, register_mock = await _process(
        [_video(title="\u0905\u0915\u094d\u0937\u0930 test")],
    )
    assert result.skipped_count == 1
    assert metrics.filter_skip_reasons.get(FILTER_SKIP_LANGUAGE) == 1
    register_mock.assert_not_called()


async def test_passed_video() -> None:
    result, metrics, register_mock = await _process(
        [_video(views_count=100_000, subscribers_count=10_000)],
    )
    assert result.passed_count == 1
    assert result.skipped_count == 0
    assert metrics.passed_videos == 1
    assert metrics.unique_channels == 1
    register_mock.assert_called_once()


async def test_first_failure_is_min_views_not_subscribers() -> None:
    _, metrics, _ = await _process(
        [_video(views_count=1_000, subscribers_count=0)],
    )
    assert metrics.filter_skip_reasons.get(FILTER_SKIP_MIN_VIEWS) == 1
    assert FILTER_SKIP_MIN_SUBSCRIBERS not in metrics.filter_skip_reasons


async def test_qualification_result_unchanged_without_metrics_collector() -> None:
    service = ExplosiveChannelsService()
    db = MagicMock()
    videos = [
        _video(video_id="a", views_count=1_000),
        _video(video_id="b", views_count=100_000, subscribers_count=10_000),
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
                        with_metrics = await service.process_radar_videos(
                            db,
                            videos,
                            filter_metrics=RadarFilterMetrics.empty(),
                        )

    assert without.skipped_count == with_metrics.skipped_count
    assert without.passed_count == with_metrics.passed_count
    assert without.parse_error_count == with_metrics.parse_error_count
    assert len(without.hits) == len(with_metrics.hits)


async def main() -> None:
    tests = [
        test_skip_min_views,
        test_skip_min_subscribers,
        test_skip_min_viral_coeff,
        test_skip_language,
        test_passed_video,
        test_first_failure_is_min_views_not_subscribers,
        test_qualification_result_unchanged_without_metrics_collector,
    ]
    failed = 0
    for test in tests:
        name = test.__name__
        try:
            await test()
            print(f"OK {name}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {name}: {exc}")

    if failed:
        raise SystemExit(f"{failed} test(s) failed")
    print("All radar filter metrics tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
