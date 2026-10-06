"""Tests for extended anomaly search (mocked YouTube API)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.integrations.youtube.client import YouTubeChannelDetails, YouTubeSearchHit, YouTubeVideoDetails
from app.models.db import Base
from app.models.schemas import ExtendedSearchParams, UploadPeriod
from app.services.extended_search_service import ExtendedSearchService


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def main() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db: Session = sessionmaker(bind=engine)()

    now = _utc_now()
    mock_youtube = MagicMock()
    mock_youtube.search_videos.return_value = [
        YouTubeSearchHit(
            video_id="vid_anomaly",
            channel_id="ch_small",
            title="Viral horror story",
            published_at=now - timedelta(hours=6),
        ),
        YouTubeSearchHit(
            video_id="vid_normal",
            channel_id="ch_big",
            title="Regular history video",
            published_at=now - timedelta(days=2),
        ),
    ]
    mock_youtube.get_videos.return_value = [
        YouTubeVideoDetails(
            video_id="vid_anomaly",
            channel_id="ch_small",
            title="Viral horror story",
            published_at=now - timedelta(hours=6),
            views_count=50_000,
            likes_count=2_000,
            comments_count=300,
            duration_seconds=480,
        ),
        YouTubeVideoDetails(
            video_id="vid_normal",
            channel_id="ch_big",
            title="Regular history video",
            published_at=now - timedelta(days=2),
            views_count=10_000,
            likes_count=400,
            comments_count=50,
            duration_seconds=900,
        ),
    ]
    mock_youtube.get_channels.return_value = {
        "ch_small": YouTubeChannelDetails(
            channel_id="ch_small",
            title="Small Horror Channel",
            subscribers_count=100,
            subscribers_known=True,
        ),
        "ch_big": YouTubeChannelDetails(
            channel_id="ch_big",
            title="Big History Channel",
            subscribers_count=500_000,
            subscribers_known=True,
        ),
    }

    service = ExtendedSearchService(db, mock_youtube)
    params = ExtendedSearchParams(
        q="scary stories",
        period=UploadPeriod.WEEK,
        min_virality_percent=1000.0,
        duration_min=60,
        duration_max=1200,
    )

    first = service.search(params)
    assert first.cached is False
    assert first.total == 1
    assert first.items[0].video_id == "vid_anomaly"
    assert first.items[0].virality_percent == 50_000.0

    second = service.search(params)
    assert second.cached is True
    assert second.total == 1
    assert mock_youtube.search_videos.call_count == 1

    all_results = service.search(
        ExtendedSearchParams(q="scary stories", period=UploadPeriod.WEEK, min_virality_percent=1000.0),
    )
    assert all_results.total == 1

    print("Extended search checks passed.")


if __name__ == "__main__":
    main()
