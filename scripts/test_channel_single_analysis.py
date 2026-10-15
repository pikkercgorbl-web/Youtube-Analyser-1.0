"""Single-channel analysis v1 — comparison rules (no network)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models.orm import VideoFormat
from app.models.schemas import ChannelSingleAnalysisPublication
from app.services.channel_single_analysis_compare import (
    PublicationForCompare,
    compute_focus_comparison,
    peer_age_in_window,
)
from app.services.channel_single_analysis_overview import compute_views_rank
from app.services.channel_single_analysis_http import _compute_comparison_result


def _pub(
    vid: str,
    *,
    views: int,
    hours_ago: float,
    fmt: VideoFormat = VideoFormat.MEDIUM,
    channel_id: str = "UC1",
) -> PublicationForCompare:
    now = datetime.now(timezone.utc)
    published = now - timedelta(hours=hours_ago)
    return PublicationForCompare(
        video_id=vid,
        channel_id=channel_id,
        views_count=views,
        published_at=published,
        content_format=fmt,
    )


def test_focus_excluded_from_median() -> None:
    now = datetime.now(timezone.utc)
    focus = _pub("focus", views=1000, hours_ago=100)
    peers = [_pub(f"p{i}", views=100, hours_ago=100 + i * 0.01) for i in range(5)]
    catalog = peers + [focus]
    result = compute_focus_comparison(
        channel_id="UC1",
        focus=focus,
        catalog=catalog,
        now=now,
    )
    assert result.status == "ok"
    assert result.multiplier == 10.0
    assert result.peer_count == 5


def test_shorts_and_unknown_excluded() -> None:
    now = datetime.now(timezone.utc)
    focus = _pub("focus", views=500, hours_ago=80)
    peers = [_pub(f"p{i}", views=100, hours_ago=80) for i in range(4)]
    peers.append(_pub("short", views=9999, hours_ago=80, fmt=VideoFormat.SHORT))
    peers.append(_pub("unk", views=9999, hours_ago=80, fmt=VideoFormat.UNKNOWN))
    result = compute_focus_comparison(
        channel_id="UC1",
        focus=focus,
        catalog=peers + [focus],
        now=now,
    )
    assert result.status == "insufficient_peers"
    assert result.peer_count == 4


def test_focus_too_young() -> None:
    focus = _pub("focus", views=1000, hours_ago=10)
    result = compute_focus_comparison(
        channel_id="UC1",
        focus=focus,
        catalog=[focus],
    )
    assert result.status == "focus_too_young"
    assert result.multiplier is None


def test_channel_mismatch() -> None:
    focus = _pub("focus", views=100, hours_ago=100, channel_id="UC_OTHER")
    result = compute_focus_comparison(
        channel_id="UC1",
        focus=focus,
        catalog=[focus],
    )
    assert result.status == "focus_channel_mismatch"


def test_age_window() -> None:
    assert peer_age_in_window(100, 100) is True
    assert peer_age_in_window(74, 100) is False
    assert peer_age_in_window(76, 100) is True
    assert peer_age_in_window(126, 100) is False
    assert peer_age_in_window(124, 100) is True


def test_median_zero() -> None:
    now = datetime.now(timezone.utc)
    focus = _pub("focus", views=100, hours_ago=100)
    peers = [_pub(f"p{i}", views=0, hours_ago=100) for i in range(5)]
    # zero views excluded from peers
    result = compute_focus_comparison(
        channel_id="UC1",
        focus=focus,
        catalog=peers + [focus],
        now=now,
    )
    assert result.status == "insufficient_peers"


def test_insufficient_peers_includes_samples() -> None:
    now = datetime.now(timezone.utc)
    focus = _pub("focus", views=500, hours_ago=80)
    peer = _pub("only", views=100, hours_ago=80)
    result = compute_focus_comparison(
        channel_id="UC1",
        focus=focus,
        catalog=[peer, focus],
        now=now,
    )
    assert result.status == "insufficient_peers"
    assert result.peer_count == 1
    assert len(result.age_peer_matches) == 1
    assert result.searched_age_low_hours is not None


def test_views_rank_ties() -> None:
    now = datetime.now(timezone.utc)
    pubs = [
        ChannelSingleAnalysisPublication(
            video_id="a",
            views_count=100,
            published_at=now,
            kind="regular",
        ),
        ChannelSingleAnalysisPublication(
            video_id="focus",
            views_count=100,
            published_at=now,
            kind="regular",
        ),
        ChannelSingleAnalysisPublication(
            video_id="c",
            views_count=50,
            published_at=now,
            kind="regular",
        ),
    ]
    rank = compute_views_rank(focus_video_id="focus", publications=pubs)
    assert rank.rank == 1
    assert rank.group_size == 3


def test_compare_helper_matches_compute() -> None:
    now = datetime.now(timezone.utc)
    focus = _pub("focus", views=1000, hours_ago=100)
    peers = [_pub(f"p{i}", views=100, hours_ago=100 + i * 0.01) for i in range(5)]
    catalog = peers + [focus]
    direct = compute_focus_comparison(
        channel_id="UC1",
        focus=focus,
        catalog=catalog,
        now=now,
    )
    enriched = []
    for row in catalog:
        enriched.append(
            ChannelSingleAnalysisPublication(
                video_id=row.video_id,
                channel_id="UC1",
                title=row.video_id,
                views_count=row.views_count,
                published_at=row.published_at,
                kind="regular",
                in_feed=True,
            ),
        )
    via_http = _compute_comparison_result(
        channel_id="UC1",
        focus_id="focus",
        focus_pub=enriched[-1],
        enriched_publications=enriched[:-1],
        details_by_id={},
        enrichment_error=None,
    )
    assert via_http.status == direct.status
    assert via_http.multiplier == direct.multiplier


def main() -> None:
    test_insufficient_peers_includes_samples()
    test_views_rank_ties()
    test_compare_helper_matches_compute()
    test_focus_excluded_from_median()
    test_shorts_and_unknown_excluded()
    test_focus_too_young()
    test_channel_mismatch()
    test_age_window()
    test_median_zero()
    print("OK: channel single analysis tests")


if __name__ == "__main__":
    main()
