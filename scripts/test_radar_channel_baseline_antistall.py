"""Anti-stall guard tests for channel baseline pagination (Stage 1.10C hotfix)."""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.youtube.client import ChannelVideoBrowseModel, YouTubeVideoDetails
from app.services.radar_candidate import RadarCandidate
from app.services.radar_channel_baseline import (
    ChannelBaselineConfig,
    ChannelBaselineRunStats,
    _aggregate_channel_fetch_stats,
    _fetch_channel_cache_entry,
    build_eligible_history,
    collect_channel_baselines_for_candidates,
    resolve_baseline_status,
)
from app.services.radar_channel_baseline import ChannelFetchMeta


def _candidate(**kwargs: object) -> RadarCandidate:
    base = {
        "video_id": "cand1",
        "channel_id": "ch1",
        "keyword": "gaming",
        "discovery_source": "innertube",
        "discovered_at": datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc),
        "video_title": "t",
        "channel_title": "ch",
        "discovery_views": 5000,
    }
    base.update(kwargs)
    return RadarCandidate(**base)  # type: ignore[arg-type]


def _browse(vid: str, **kwargs: object) -> ChannelVideoBrowseModel:
    return ChannelVideoBrowseModel(
        video_id=vid,
        title="x",
        url=f"https://youtube.com/watch?v={vid}",
        duration_text=kwargs.get("duration_text", "10:00"),  # type: ignore[arg-type]
        views_count=kwargs.get("views_count", 1000),  # type: ignore[arg-type]
    )


def _details(vid: str, published_at: datetime, **kwargs: object) -> YouTubeVideoDetails:
    return YouTubeVideoDetails(
        video_id=vid,
        channel_id="ch1",
        title="x",
        published_at=published_at,
        views_count=kwargs.get("views_count", 1000),  # type: ignore[arg-type]
        likes_count=0,
        comments_count=0,
        duration_seconds=kwargs.get("duration_seconds", 600),  # type: ignore[arg-type]
    )


class _PaginatedClient:
    def __init__(
        self,
        pages: list[list[ChannelVideoBrowseModel]],
        *,
        delay_seconds: float = 0.0,
        fail_on_page: int | None = None,
    ) -> None:
        self.pages = pages
        self.delay_seconds = delay_seconds
        self.fail_on_page = fail_on_page
        self._page_index = 0
        self.discovered = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)

    async def iter_channel_videos_tab(
        self,
        channel_id: str,
        *,
        max_pages: int | None = None,
        request_timeout: float | None = None,
    ):
        for page in self.pages:
            self._page_index += 1
            if self.fail_on_page is not None and self._page_index == self.fail_on_page:
                raise RuntimeError("simulated fetch error")
            if self.delay_seconds > 0:
                await asyncio.sleep(self.delay_seconds)
            yield page

    def get_videos(self, video_ids: list[str]) -> list[YouTubeVideoDetails]:
        return [
            _details(
                vid,
                self.discovered - timedelta(days=self._page_index),
                views_count=100,
            )
            for vid in video_ids
        ]


def _regular_pages(count: int, *, page_size: int = 5) -> list[list[ChannelVideoBrowseModel]]:
    pages: list[list[ChannelVideoBrowseModel]] = []
    ids = [f"v{i}" for i in range(count)]
    for i in range(0, len(ids), page_size):
        pages.append([_browse(vid) for vid in ids[i : i + page_size]])
    return pages


async def test_stops_at_20_eligible() -> None:
    client = _PaginatedClient(_regular_pages(30))
    cfg = ChannelBaselineConfig(max_pages_per_channel=20, min_useful_history=5)
    entry = await _fetch_channel_cache_entry(
        client,  # type: ignore[arg-type]
        "ch1",
        tab_fetch_limit=60,
        config=cfg,
        reference_candidate=_candidate(),
    )
    assert entry.fetch_meta is not None
    assert entry.fetch_meta.stop_reason == "target_reached"
    assert entry.fetch_meta.eligible_reference_count == 20
    assert entry.fetch_meta.pages_fetched <= 5


async def test_page_cap_stops_continuation() -> None:
    client = _PaginatedClient(_regular_pages(40))
    cfg = ChannelBaselineConfig(max_pages_per_channel=3, min_useful_history=5)
    entry = await _fetch_channel_cache_entry(
        client,  # type: ignore[arg-type]
        "ch1",
        tab_fetch_limit=60,
        config=cfg,
        reference_candidate=_candidate(),
    )
    assert entry.fetch_meta is not None
    assert entry.fetch_meta.stop_reason == "page_cap"
    assert entry.fetch_meta.pages_fetched == 3
    assert entry.fetch_meta.eligible_reference_count == 15


async def test_channel_timeout_stops_loop() -> None:
    client = _PaginatedClient(_regular_pages(40), delay_seconds=0.05)
    cfg = ChannelBaselineConfig(
        max_pages_per_channel=100,
        max_seconds_per_channel=0.08,
        min_useful_history=5,
    )
    entry = await _fetch_channel_cache_entry(
        client,  # type: ignore[arg-type]
        "ch1",
        tab_fetch_limit=60,
        config=cfg,
        reference_candidate=_candidate(),
    )
    assert entry.fetch_meta is not None
    assert entry.fetch_meta.stop_reason == "channel_timeout"
    assert entry.fetch_meta.eligible_reference_count >= 1


async def test_partial_history_after_page_cap() -> None:
    client = _PaginatedClient(_regular_pages(14))
    cfg = ChannelBaselineConfig(max_pages_per_channel=2, min_useful_history=5)
    entry = await _fetch_channel_cache_entry(
        client,  # type: ignore[arg-type]
        "ch1",
        tab_fetch_limit=60,
        config=cfg,
        reference_candidate=_candidate(),
    )
    eligible, _ = build_eligible_history(
        browse_videos=entry.browse_videos,
        details_by_id=entry.details_by_id,
        candidate_video_id="cand1",
        discovered_at=datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc),
        requested_count=20,
        exclusion_counts={},
    )
    assert len(eligible) == 10
    status = resolve_baseline_status(
        eligible_count=len(eligible),
        requested_count=20,
        min_useful=5,
        fetch_failed=False,
        channel_missing=False,
    )
    assert status == "partial"
    assert entry.fetch_meta is not None
    assert entry.fetch_meta.fetch_status == "partial"


async def test_partial_history_after_timeout() -> None:
    pages = _regular_pages(20)
    client = _PaginatedClient(pages, delay_seconds=0.04)
    cfg = ChannelBaselineConfig(
        max_seconds_per_channel=0.06,
        max_pages_per_channel=50,
        min_useful_history=5,
    )
    entry = await _fetch_channel_cache_entry(
        client,  # type: ignore[arg-type]
        "ch1",
        tab_fetch_limit=60,
        config=cfg,
        reference_candidate=_candidate(),
    )
    assert not entry.fetch_failed
    assert len(entry.browse_videos) >= 5


async def test_insufficient_history_unchanged() -> None:
    client = _PaginatedClient(_regular_pages(2))
    cfg = ChannelBaselineConfig(max_pages_per_channel=2, min_useful_history=5)
    entry = await _fetch_channel_cache_entry(
        client,  # type: ignore[arg-type]
        "ch1",
        tab_fetch_limit=60,
        config=cfg,
        reference_candidate=_candidate(),
    )
    assert entry.fetch_meta is not None
    assert entry.fetch_meta.fetch_status == "insufficient_history"


async def test_no_continuation_exits_normally() -> None:
    client = _PaginatedClient(_regular_pages(3, page_size=3))
    cfg = ChannelBaselineConfig(max_pages_per_channel=10)
    entry = await _fetch_channel_cache_entry(
        client,  # type: ignore[arg-type]
        "ch1",
        tab_fetch_limit=60,
        config=cfg,
        reference_candidate=_candidate(),
    )
    assert entry.fetch_meta is not None
    assert entry.fetch_meta.stop_reason == "no_continuation"


async def test_one_channel_timeout_does_not_abort_cohort() -> None:
    slow = _PaginatedClient(_regular_pages(30), delay_seconds=0.05)
    fast = _PaginatedClient(_regular_pages(8))

    class _MultiClient:
        async def iter_channel_videos_tab(self, channel_id: str, **kwargs: Any):
            if channel_id == "slow":
                async for page in slow.iter_channel_videos_tab(channel_id, **kwargs):
                    yield page
            else:
                async for page in fast.iter_channel_videos_tab(channel_id, **kwargs):
                    yield page

        def get_videos(self, video_ids: list[str]) -> list[YouTubeVideoDetails]:
            return slow.get_videos(video_ids)

    cfg = ChannelBaselineConfig(
        max_seconds_per_channel=0.08,
        max_pages_per_channel=20,
        min_useful_history=2,
    )
    stats = await collect_channel_baselines_for_candidates(
        [
            _candidate(channel_id="slow", video_id="s1"),
            _candidate(channel_id="fast", video_id="f1"),
        ],
        _MultiClient(),  # type: ignore[arg-type]
        config=cfg,
    )
    assert stats.candidates == 2
    assert stats.channels_timeout >= 1


async def test_candidate_self_exclusion() -> None:
    discovered = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
    pages = [[_browse("cand1"), _browse("p1")]]
    client = _PaginatedClient(pages)
    client.discovered = discovered
    entry = await _fetch_channel_cache_entry(
        client,  # type: ignore[arg-type]
        "ch1",
        tab_fetch_limit=60,
        config=ChannelBaselineConfig(max_pages_per_channel=5),
        reference_candidate=_candidate(),
    )
    exclusions: dict[str, int] = {}
    eligible, _ = build_eligible_history(
        browse_videos=entry.browse_videos,
        details_by_id={
            "p1": _details("p1", discovered - timedelta(days=1)),
        },
        candidate_video_id="cand1",
        discovered_at=discovered,
        requested_count=20,
        exclusion_counts=exclusions,
    )
    assert len(eligible) == 1
    assert exclusions.get("candidate_self_excluded", 0) >= 1


async def test_future_video_exclusion() -> None:
    discovered = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
    client = _PaginatedClient([[ _browse("future1") ]])
    client.discovered = discovered

    def get_videos(video_ids: list[str]) -> list[YouTubeVideoDetails]:
        return [_details("future1", discovered + timedelta(hours=1))]

    client.get_videos = get_videos  # type: ignore[method-assign]
    entry = await _fetch_channel_cache_entry(
        client,  # type: ignore[arg-type]
        "ch1",
        tab_fetch_limit=60,
        config=ChannelBaselineConfig(max_pages_per_channel=5),
        reference_candidate=_candidate(),
    )
    eligible, _ = build_eligible_history(
        browse_videos=entry.browse_videos,
        details_by_id=entry.details_by_id,
        candidate_video_id="cand1",
        discovered_at=discovered,
        requested_count=20,
        exclusion_counts={},
    )
    assert eligible == []


async def test_shorts_live_filters_unchanged() -> None:
    discovered = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
    pages = [
        [_browse("short1", duration_text="0:30"), _browse("live1", duration_text="LIVE")],
    ]
    client = _PaginatedClient(pages)
    client.discovered = discovered
    entry = await _fetch_channel_cache_entry(
        client,  # type: ignore[arg-type]
        "ch1",
        tab_fetch_limit=60,
        config=ChannelBaselineConfig(max_pages_per_channel=5),
        reference_candidate=_candidate(),
    )
    exclusions: dict[str, int] = {}
    eligible, _ = build_eligible_history(
        browse_videos=entry.browse_videos,
        details_by_id={
            "short1": _details("short1", discovered - timedelta(days=1), duration_seconds=30),
            "live1": _details("live1", discovered - timedelta(days=1), duration_seconds=600),
        },
        candidate_video_id="cand1",
        discovered_at=discovered,
        requested_count=20,
        exclusion_counts=exclusions,
    )
    assert eligible == []
    assert exclusions.get("shorts_excluded") == 1
    assert exclusions.get("live_excluded") == 1


def test_summary_counters_correct() -> None:
    stats = ChannelBaselineRunStats()
    _aggregate_channel_fetch_stats(
        stats,
        ChannelFetchMeta(pages_fetched=4, stop_reason="page_cap", elapsed_seconds=2.5),
    )
    _aggregate_channel_fetch_stats(
        stats,
        ChannelFetchMeta(pages_fetched=6, stop_reason="target_reached", elapsed_seconds=5.0),
    )
    _aggregate_channel_fetch_stats(
        stats,
        ChannelFetchMeta(pages_fetched=2, stop_reason="channel_timeout", elapsed_seconds=30.0),
    )
    _aggregate_channel_fetch_stats(
        stats,
        ChannelFetchMeta(pages_fetched=1, stop_reason="no_continuation", elapsed_seconds=1.0),
    )
    assert stats.channels_page_cap_reached == 1
    assert stats.channels_target_reached == 1
    assert stats.channels_timeout == 1
    assert stats.channels_no_continuation == 1
    assert stats.max_pages_observed == 6
    assert stats.max_channel_elapsed_seconds == 30.0


async def main() -> None:
    async_tests = [
        test_stops_at_20_eligible,
        test_page_cap_stops_continuation,
        test_channel_timeout_stops_loop,
        test_partial_history_after_page_cap,
        test_partial_history_after_timeout,
        test_insufficient_history_unchanged,
        test_no_continuation_exits_normally,
        test_one_channel_timeout_does_not_abort_cohort,
        test_candidate_self_exclusion,
        test_future_video_exclusion,
        test_shorts_live_filters_unchanged,
    ]
    failed = 0
    try:
        test_summary_counters_correct()
        print("OK test_summary_counters_correct")
    except Exception as exc:
        failed += 1
        print(f"FAIL test_summary_counters_correct: {exc}")

    for test in async_tests:
        try:
            await test()
            print(f"OK {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")

    if failed:
        raise SystemExit(f"{failed} test(s) failed")
    print("All anti-stall channel baseline tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
