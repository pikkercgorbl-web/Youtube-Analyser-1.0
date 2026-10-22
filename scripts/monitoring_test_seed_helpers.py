"""Shared DB seed helpers for offline monitoring tests (Stage 2.3 eligibility)."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.orm import Channel, Video, VideoFormat, VideoFormatEnrichmentAttempt, VideoSnapshot
from app.services.channel_subscriber_backfill import SUBSCRIBERS_API_KNOWN
from app.services.historical_video_format_verification import OUTCOME_CONFIRMED_REGULAR


def ensure_monitoring_eligible_channel(
    session: Session,
    channel_id: str,
    *,
    published_at: datetime,
    subscribers_count: int = 1000,
    title: str = "Channel",
) -> None:
    if session.get(Channel, channel_id) is not None:
        row = session.get(Channel, channel_id)
        assert row is not None
        row.subscribers_api_status = SUBSCRIBERS_API_KNOWN
        row.subscribers_api_checked_at = published_at
        return
    session.add(
        Channel(
            id=channel_id,
            title=title,
            subscribers_count=subscribers_count,
            subscribers_api_status=SUBSCRIBERS_API_KNOWN,
            subscribers_api_checked_at=published_at,
            created_at=published_at,
        ),
    )


def ensure_monitoring_eligible_video(
    session: Session,
    video_id: str,
    *,
    channel_id: str,
    published_at: datetime,
    views: int,
    title: str = "Video",
    content_format: VideoFormat = VideoFormat.MEDIUM,
) -> None:
    ensure_monitoring_eligible_channel(session, channel_id, published_at=published_at)
    session.add(
        Video(
            id=video_id,
            title=title,
            views_count=views,
            likes_count=0,
            comments_count=0,
            published_at=published_at,
            published_at_source="api_snippet",
            duration_seconds=600,
            content_format=content_format,
            channel_id=channel_id,
        ),
    )
    if content_format in (VideoFormat.MEDIUM, VideoFormat.LONG):
        session.add(
            VideoFormatEnrichmentAttempt(
                video_id=video_id,
                last_attempt_at=published_at,
                last_outcome=OUTCOME_CONFIRMED_REGULAR,
            ),
        )
        captured_at = published_at + timedelta(hours=6)
        session.add(
            VideoSnapshot(
                video_id=video_id,
                channel_id=channel_id,
                captured_at=captured_at,
                published_at=published_at,
                age_hours=max(1.0, (captured_at - published_at).total_seconds() / 3600),
                views=views,
                source="test_seed",
                run_id="seed",
                fetch_status="refreshed",
            ),
        )
