#!/usr/bin/env python3
"""Live broadcast classification and discovery persistence (InnerTube search cards)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.integrations.youtube.client import (
    LiveBroadcastStatus,
    VideoSearchModel,
    _parse_playlist_video_search_renderer,
    _parse_search_lockup_view_model,
    _parse_video_renderer,
    classify_live_broadcast_from_renderer,
    video_is_regular_item,
    video_is_short_item,
    video_is_stream_content,
)
from app.models.db import Base
from app.models.orm import Channel, Video, VideoFormat
from app.services.discovered_video_persistence import persist_discovered_video


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _session():
    return sessionmaker(bind=_engine())()


def _base_renderer(**updates) -> dict:
    base = {
        "videoId": "vid1",
        "title": {"simpleText": "Regular title"},
        "viewCountText": {"simpleText": "1,000 views"},
        "lengthText": {"simpleText": "10:00"},
        "publishedTimeText": {"simpleText": "2 days ago"},
        "ownerText": {"simpleText": "Channel"},
        "thumbnailOverlays": [],
        "badges": [],
    }
    base.update(updates)
    return base


def test_live_overlay_style() -> None:
    renderer = _base_renderer(
        thumbnailOverlays=[
            {
                "thumbnailOverlayTimeStatusRenderer": {
                    "style": "LIVE",
                    "text": {"simpleText": "LIVE"},
                },
            },
        ],
    )
    assert classify_live_broadcast_from_renderer(renderer) == LiveBroadcastStatus.LIVE
    parsed = _parse_video_renderer(renderer)
    assert parsed is not None
    assert parsed.live_broadcast_status == LiveBroadcastStatus.LIVE
    assert parsed.is_live is True


def test_upcoming_event_data() -> None:
    renderer = _base_renderer(upcomingEventData={"startTime": "2026-10-07T12:00:00Z"})
    assert classify_live_broadcast_from_renderer(renderer) == LiveBroadcastStatus.UPCOMING
    parsed = _parse_video_renderer(renderer)
    assert parsed is not None
    assert parsed.is_live is True


def test_completed_stream_badge() -> None:
    renderer = _base_renderer(
        badges=[
            {
                "metadataBadgeRenderer": {
                    "style": "BADGE_STYLE_TYPE_SIMPLE",
                    "label": "Streamed live",
                },
            },
        ],
    )
    assert classify_live_broadcast_from_renderer(renderer) == LiveBroadcastStatus.COMPLETED
    parsed = _parse_video_renderer(renderer)
    assert parsed is not None
    assert parsed.is_live is False
    assert video_is_stream_content(parsed)


def test_regular_video_with_metadata_slots() -> None:
    renderer = _base_renderer(title={"simpleText": "My live gameplay highlights"})
    assert classify_live_broadcast_from_renderer(renderer) == LiveBroadcastStatus.NONE
    parsed = _parse_video_renderer(renderer)
    assert parsed is not None
    assert parsed.live_broadcast_status == LiveBroadcastStatus.NONE
    assert video_is_regular_item(parsed)


def test_title_live_word_does_not_classify() -> None:
    renderer = _base_renderer(title={"simpleText": "Stay live on camera tips"})
    assert classify_live_broadcast_from_renderer(renderer) == LiveBroadcastStatus.NONE


def test_playlist_renderer_sparse_unknown() -> None:
    renderer = {
        "videoId": "pl1",
        "title": {"simpleText": "Stream archive"},
        "lengthText": {"simpleText": "1:00:00"},
        "shortViewCountText": {"simpleText": "500 views"},
    }
    parsed = _parse_playlist_video_search_renderer(renderer)
    assert parsed is not None
    assert parsed.live_broadcast_status == LiveBroadcastStatus.UNKNOWN


def test_lockup_completed_badge() -> None:
    lockup = {
        "contentId": "abc12345678",
        "metadata": {
            "lockupMetadataViewModel": {
                "title": {"content": "Past stream"},
                "badges": [
                    {
                        "metadataBadgeRenderer": {
                            "label": "Streamed live",
                            "style": "BADGE_STYLE_TYPE_SIMPLE",
                        },
                    },
                ],
                "metadata": {
                    "contentMetadataViewModel": {
                        "metadataRows": [
                            {
                                "metadataParts": [
                                    {"text": {"content": "1,000 views"}},
                                    {"text": {"content": "3 days ago"}},
                                ],
                            },
                        ],
                    },
                },
            },
        },
        "contentImage": {},
    }
    parsed = _parse_search_lockup_view_model(lockup)
    assert parsed is not None
    assert parsed.live_broadcast_status == LiveBroadcastStatus.COMPLETED


def test_persist_skips_active_and_completed_streams() -> None:
    session = _session()
    for vid, status in (
        ("live1", LiveBroadcastStatus.LIVE),
        ("up1", LiveBroadcastStatus.UPCOMING),
        ("done1", LiveBroadcastStatus.COMPLETED),
    ):
        video = VideoSearchModel(
            video_id=vid,
            channel_id="ch1",
            title="t",
            published_text="1 day ago",
            duration_text="1:00:00",
            live_broadcast_status=status,
        )
        assert persist_discovered_video(session, video, discovery_keyword="k").outcome == "skipped_live"


def test_persist_unknown_not_as_medium() -> None:
    session = _session()
    video = VideoSearchModel(
        video_id="u1",
        channel_id="ch1",
        title="Ambiguous card",
        published_text="2 days ago",
        duration_text="15:00",
        live_broadcast_status=LiveBroadcastStatus.UNKNOWN,
    )
    result = persist_discovered_video(session, video, discovery_keyword="k")
    session.commit()
    assert result.outcome == "inserted"
    row = session.get(Video, "u1")
    assert row is not None
    assert row.content_format == VideoFormat.UNKNOWN


def test_persist_does_not_downgrade_live_format() -> None:
    session = _session()
    session.add(
        Channel(id="ch1", title="C", subscribers_count=0, created_at=datetime.now(timezone.utc)),
    )
    session.add(
        Video(
            id="v1",
            title="Old",
            views_count=1,
            likes_count=0,
            comments_count=0,
            published_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            duration_seconds=3600,
            content_format=VideoFormat.LIVE,
            channel_id="ch1",
        ),
    )
    session.commit()
    sparse = VideoSearchModel(
        video_id="v1",
        channel_id="ch1",
        title="Replay",
        published_text="3 days ago",
        duration_text="1:00:00",
        live_broadcast_status=LiveBroadcastStatus.UNKNOWN,
    )
    persist_discovered_video(session, sparse, discovery_keyword="k")
    session.commit()
    row = session.get(Video, "v1")
    assert row.content_format == VideoFormat.LIVE


def test_shorts_filter_unchanged() -> None:
    parsed = _parse_video_renderer(
        {
            **_base_renderer(),
            "videoId": "shortvid001",
            "channelId": "UCshort12345678901234567",
            "ownerText": {"simpleText": "Ch"},
            "navigationEndpoint": {"reelWatchEndpoint": {"videoId": "shortvid001"}},
            "thumbnailOverlays": [
                {"thumbnailOverlayTimeStatusRenderer": {"style": "SHORTS"}},
            ],
        },
    )
    assert parsed is not None
    assert parsed.is_short is True
    assert video_is_short_item(parsed)
    session = _session()
    assert persist_discovered_video(session, parsed, discovery_keyword="k").outcome == "skipped_short"


def main() -> None:
    tests = [
        test_live_overlay_style,
        test_upcoming_event_data,
        test_completed_stream_badge,
        test_regular_video_with_metadata_slots,
        test_title_live_word_does_not_classify,
        test_playlist_renderer_sparse_unknown,
        test_lockup_completed_badge,
        test_persist_skips_active_and_completed_streams,
        test_persist_unknown_not_as_medium,
        test_persist_does_not_downgrade_live_format,
        test_shorts_filter_unchanged,
    ]
    for fn in tests:
        fn()
        print(f"OK {fn.__name__}")
    print(f"All {len(tests)} passed")


if __name__ == "__main__":
    main()
