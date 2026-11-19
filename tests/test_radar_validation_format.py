"""Tests for validation-only radar content format filters (Stage 1.8 Step 1)."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.youtube.client import (
    RadarContentFormatFilters,
    VideoSearchModel,
    filter_radar_videos_by_format,
)
from app.services.explosive_channels_radar_worker import (
    AnalysisScanResult,
    get_radar_content_filters,
    set_radar_content_filters,
)
from app.services.radar_candidate import (
    DISCOVERY_SOURCE_INNERTUBE,
    RadarCandidate,
)
from app.services.radar_candidate_dataset import serialize_candidate
from app.services.radar_validation_format import (
    VALIDATION_CONTENT_FILTERS,
    validation_content_filters,
)
from app.services.radar_validation_scan import run_validation_analysis_scan


def _video(
    *,
    video_id: str,
    is_short: bool = False,
    is_live: bool = False,
    content_renderer: str = "videoRenderer",
) -> VideoSearchModel:
    return VideoSearchModel(
        video_id=video_id,
        channel_id="UC1234567890123456789012",
        channel_title="Channel",
        title=f"Title {video_id}",
        views_count=50_000,
        subscribers_count=1_000,
        published_text="2 days ago",
        is_short=is_short,
        is_live=is_live,
        content_renderer=content_renderer,
    )


def test_validation_filters_enable_short_and_stream_exclusion() -> None:
    assert VALIDATION_CONTENT_FILTERS.exclude_shorts is True
    assert VALIDATION_CONTENT_FILTERS.exclude_streams is True
    assert VALIDATION_CONTENT_FILTERS.exclude_videos is False


def test_validation_context_applies_filters() -> None:
    set_radar_content_filters(exclude_shorts=False, exclude_streams=False, exclude_videos=False)
    with validation_content_filters():
        active = get_radar_content_filters()
        assert active == VALIDATION_CONTENT_FILTERS


def test_production_defaults_restored_after_validation_context() -> None:
    set_radar_content_filters(exclude_shorts=False, exclude_streams=False, exclude_videos=False)
    with validation_content_filters():
        pass
    assert get_radar_content_filters() == RadarContentFormatFilters()


def test_custom_production_filters_restored_after_validation_context() -> None:
    custom = RadarContentFormatFilters(
        exclude_streams=True,
        exclude_shorts=False,
        exclude_videos=True,
    )
    set_radar_content_filters(
        exclude_streams=custom.exclude_streams,
        exclude_shorts=custom.exclude_shorts,
        exclude_videos=custom.exclude_videos,
    )
    with validation_content_filters():
        assert get_radar_content_filters() == VALIDATION_CONTENT_FILTERS
    assert get_radar_content_filters() == custom


def test_shorts_and_live_excluded_before_candidate_creation() -> None:
    videos = [
        _video(video_id="regular"),
        _video(video_id="short-flag", is_short=True),
        _video(video_id="live-flag", is_live=True),
        _video(video_id="short-renderer", content_renderer="reelItemRenderer"),
    ]
    with validation_content_filters():
        filtered = filter_radar_videos_by_format(videos, get_radar_content_filters())

    assert [video.video_id for video in filtered] == ["regular"]

    candidates = [
        RadarCandidate.from_video_search(
            video,
            keyword="gaming",
            discovery_source=DISCOVERY_SOURCE_INNERTUBE,
            discovered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        for video in filtered
    ]
    assert len(candidates) == 1
    assert candidates[0].is_short is False
    assert candidates[0].is_live is False
    assert candidates[0].content_renderer == "videoRenderer"


def test_candidate_exports_format_fields() -> None:
    candidate = RadarCandidate.from_video_search(
        _video(video_id="regular"),
        keyword="gaming",
        discovery_source=DISCOVERY_SOURCE_INNERTUBE,
    )
    record = serialize_candidate(candidate)
    assert record["is_short"] is False
    assert record["is_live"] is False
    assert record["content_renderer"] == "videoRenderer"


async def test_run_validation_analysis_scan_uses_validation_filters() -> None:
    worker = AsyncMock()
    worker.run_analysis_scan = AsyncMock(
        return_value=AnalysisScanResult(
            keyword="gaming",
            candidates=[],
            pages_scanned=0,
            min_views=10_000,
            min_viral_coeff=3.0,
            upload_period="all",
        ),
    )

    set_radar_content_filters(exclude_shorts=False, exclude_streams=False, exclude_videos=False)

    async def _assert_filters_during_scan(_keyword: str) -> AnalysisScanResult:
        active = get_radar_content_filters()
        assert active == VALIDATION_CONTENT_FILTERS
        return AnalysisScanResult(
            keyword="gaming",
            candidates=[],
            pages_scanned=0,
            min_views=10_000,
            min_viral_coeff=3.0,
            upload_period="all",
        )

    worker.run_analysis_scan = AsyncMock(side_effect=_assert_filters_during_scan)

    with patch(
        "app.services.radar_validation_scan.validation_content_filters",
        wraps=validation_content_filters,
    ):
        await run_validation_analysis_scan(worker, "gaming")

    assert get_radar_content_filters() == RadarContentFormatFilters()


async def main() -> None:
    sync_tests = [
        test_validation_filters_enable_short_and_stream_exclusion,
        test_validation_context_applies_filters,
        test_production_defaults_restored_after_validation_context,
        test_custom_production_filters_restored_after_validation_context,
        test_shorts_and_live_excluded_before_candidate_creation,
        test_candidate_exports_format_fields,
    ]
    async_tests = [test_run_validation_analysis_scan_uses_validation_filters]

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
    print("All validation format tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
