"""Tests for channel baseline T0 capture (Stage 1.10A)."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.youtube.client import ChannelVideoBrowseModel, YouTubeVideoDetails
from app.services.radar_candidate import RadarCandidate
from app.services.radar_channel_baseline import (
    ChannelBaselineConfig,
    VELOCITY_BASELINE_UNAVAILABLE,
    apply_baseline_features_to_candidate,
    assert_leakage_invariant,
    build_candidate_baseline_features,
    build_eligible_history,
    classify_history_format,
    collect_channel_baselines_for_candidates,
    compute_view_distribution,
)
from app.services.radar_validation_t0_dataset import (
    serialize_t0_candidate,
    serialize_t0_candidate_with_baseline,
)


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


def test_candidate_excluded_from_history() -> None:
    discovered = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
    browse = [_browse("cand1"), _browse("prev1")]
    details = {"prev1": _details("prev1", discovered - timedelta(days=1))}
    eligible, _ = build_eligible_history(
        browse_videos=browse,
        details_by_id=details,
        candidate_video_id="cand1",
        discovered_at=discovered,
        requested_count=20,
        exclusion_counts={},
    )
    assert len(eligible) == 1
    assert eligible[0].video_id == "prev1"


def test_future_video_excluded() -> None:
    discovered = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
    browse = [_browse("prev1")]
    details = {"prev1": _details("prev1", discovered + timedelta(hours=1))}
    exclusions: dict[str, int] = {}
    eligible, leakage = build_eligible_history(
        browse_videos=browse,
        details_by_id=details,
        candidate_video_id="cand1",
        discovered_at=discovered,
        requested_count=20,
        exclusion_counts=exclusions,
    )
    assert eligible == []
    assert leakage == 1
    assert exclusions.get("future_videos_excluded") == 1


def test_shorts_excluded() -> None:
    fmt = classify_history_format(duration_seconds=30, browse=_browse("s", duration_text="0:30"))
    assert fmt == "short"


def test_live_excluded() -> None:
    fmt = classify_history_format(
        duration_seconds=600,
        browse=_browse("l", duration_text="LIVE"),
    )
    assert fmt == "live"


def test_max_history_count_respected() -> None:
    discovered = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
    browse = [_browse(f"v{i}") for i in range(30)]
    details = {
        f"v{i}": _details(f"v{i}", discovered - timedelta(days=i + 1), views_count=i * 100)
        for i in range(30)
    }
    eligible, _ = build_eligible_history(
        browse_videos=browse,
        details_by_id=details,
        candidate_video_id="cand1",
        discovered_at=discovered,
        requested_count=20,
        exclusion_counts={},
    )
    assert len(eligible) == 20


def test_median_p75_p90_views() -> None:
    dist = compute_view_distribution([100, 200, 300, 400, 500])
    assert dist["channel_median_views"] == 300
    assert dist["channel_p75_views"] == 400
    assert dist["channel_max_views"] == 500


def test_views_vs_channel_median() -> None:
    features = build_candidate_baseline_features(
        candidate=_candidate(discovery_views=1000),
        eligible_history=[],
        config=ChannelBaselineConfig(),
        status="insufficient_history",
        found_count=0,
        leakage_count=0,
        collected_at=datetime.now(timezone.utc),
    )
    features_with_hist = build_candidate_baseline_features(
        candidate=_candidate(discovery_views=1000),
        eligible_history=[
            __import__(
                "app.services.radar_channel_baseline",
                fromlist=["HistoryVideoRow"],
            ).HistoryVideoRow(
                video_id="a",
                views_count=500,
                published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                duration_seconds=600,
                content_format="regular",
            ),
        ],
        config=ChannelBaselineConfig(min_useful_history=1),
        status="partial",
        found_count=1,
        leakage_count=0,
        collected_at=datetime.now(timezone.utc),
    )
    assert features_with_hist["views_vs_channel_median"] == 2.0


def test_zero_denominator_null() -> None:
    features = build_candidate_baseline_features(
        candidate=_candidate(discovery_views=100),
        eligible_history=[],
        config=ChannelBaselineConfig(),
        status="insufficient_history",
        found_count=0,
        leakage_count=0,
        collected_at=datetime.now(timezone.utc),
    )
    assert features["views_vs_channel_median"] is None


def test_insufficient_history_status() -> None:
    from app.services.radar_channel_baseline import resolve_baseline_status

    assert (
        resolve_baseline_status(
            eligible_count=2,
            requested_count=20,
            min_useful=5,
            fetch_failed=False,
            channel_missing=False,
        )
        == "insufficient_history"
    )


class _FakeClient:
    def __init__(self) -> None:
        self.channel_calls = 0

    async def get_channel_videos_tab(
        self,
        channel_id: str,
        *,
        max_results: int,
    ) -> tuple[str, list[ChannelVideoBrowseModel]]:
        self.channel_calls += 1
        discovered = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
        return "Ch", [_browse("p1"), _browse("p2")]

    def get_videos(self, video_ids: list[str]) -> list[YouTubeVideoDetails]:
        discovered = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
        return [
            _details("p1", discovered - timedelta(days=2), views_count=100),
            _details("p2", discovered - timedelta(days=3), views_count=200),
        ]


async def test_same_channel_cache_reused() -> None:
    client = _FakeClient()
    c1 = _candidate(video_id="a1")
    c2 = _candidate(video_id="a2")
    stats = await collect_channel_baselines_for_candidates(
        [c1, c2],
        client,  # type: ignore[arg-type]
        config=ChannelBaselineConfig(min_useful_history=2),
    )
    assert client.channel_calls == 1
    assert stats.cache_hits == 1


def test_leakage_invariant() -> None:
    from app.services.radar_channel_baseline import HistoryVideoRow

    discovered = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
    rows = [
        HistoryVideoRow("a", 1, discovered - timedelta(hours=1), 600, "regular"),
    ]
    assert assert_leakage_invariant(rows, discovered) == 0


def test_missing_channel() -> None:
    features = build_candidate_baseline_features(
        candidate=_candidate(channel_id=""),
        eligible_history=[],
        config=ChannelBaselineConfig(),
        status="channel_unavailable",
        found_count=0,
        leakage_count=0,
        collected_at=datetime.now(timezone.utc),
    )
    assert features["channel_baseline_status"] == "channel_unavailable"


def test_partial_metadata() -> None:
    discovered = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
    browse = [_browse("p1")]
    eligible, _ = build_eligible_history(
        browse_videos=browse,
        details_by_id={},
        candidate_video_id="cand1",
        discovered_at=discovered,
        requested_count=20,
        exclusion_counts={},
    )
    assert eligible == []


def test_no_fake_velocity_baseline() -> None:
    features = build_candidate_baseline_features(
        candidate=_candidate(),
        eligible_history=[],
        config=ChannelBaselineConfig(),
        status="ok",
        found_count=10,
        leakage_count=0,
        collected_at=datetime.now(timezone.utc),
    )
    assert features["velocity_baseline_status"] == VELOCITY_BASELINE_UNAVAILABLE
    assert features["vph_vs_channel_median"] is None


def test_t0_serialization_unchanged_when_baseline_disabled() -> None:
    candidate = _candidate()
    assert serialize_t0_candidate(candidate) == serialize_t0_candidate_with_baseline(candidate)


def test_baseline_fields_serialized_when_present() -> None:
    candidate = _candidate()
    apply_baseline_features_to_candidate(
        candidate,
        build_candidate_baseline_features(
            candidate=candidate,
            eligible_history=[],
            config=ChannelBaselineConfig(),
            status="insufficient_history",
            found_count=0,
            leakage_count=0,
            collected_at=datetime.now(timezone.utc),
        ),
    )
    row = serialize_t0_candidate_with_baseline(candidate)
    assert row["channel_baseline_status"] == "insufficient_history"
    assert "channel_median_views" in row


async def main() -> None:
    tests = [
        test_candidate_excluded_from_history,
        test_future_video_excluded,
        test_shorts_excluded,
        test_live_excluded,
        test_max_history_count_respected,
        test_median_p75_p90_views,
        test_views_vs_channel_median,
        test_zero_denominator_null,
        test_insufficient_history_status,
        test_leakage_invariant,
        test_missing_channel,
        test_partial_metadata,
        test_no_fake_velocity_baseline,
        test_t0_serialization_unchanged_when_baseline_disabled,
        test_baseline_fields_serialized_when_present,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"OK {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")
    try:
        await test_same_channel_cache_reused()
        print("OK test_same_channel_cache_reused")
    except Exception as exc:
        failed += 1
        print(f"FAIL test_same_channel_cache_reused: {exc}")
    if failed:
        raise SystemExit(f"{failed} test(s) failed")
    print("All channel baseline tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
