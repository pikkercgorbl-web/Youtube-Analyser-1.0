"""Radar target eligibility for monitoring load and queue read models (Stage 2.1)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import Channel, Video, VideoSnapshot
from app.models.orm import VideoFormat
from app.services.radar_target_eligibility import radar_target_eligible
from app.services.video_format_api_verification import (
    load_api_format_confirmed_video_ids,
    video_format_publishable,
)
from app.services.video_snapshot_storage import get_latest_snapshots_for_videos


def monitoring_video_eligible(
    *,
    video: Video,
    channel: Channel | None,
    latest_snapshot: VideoSnapshot | None,
    confirmed_regular_ids: frozenset[str] | None = None,
) -> bool:
    if not radar_target_eligible(
        video=video,
        channel=channel,
        latest_snapshot=latest_snapshot,
    ):
        return False
    if video.content_format in (VideoFormat.SHORT, VideoFormat.LIVE, VideoFormat.UNKNOWN):
        return False
    if video.content_format in (VideoFormat.MEDIUM, VideoFormat.LONG):
        confirmed = confirmed_regular_ids if confirmed_regular_ids is not None else frozenset()
        return video_format_publishable(
            content_format=video.content_format,
            video_id=video.id,
            confirmed_ids=confirmed,
        )
    return False


def filter_monitoring_videos(
    session: Session,
    videos: list[Video],
    *,
    latest_by_video_id: dict[str, VideoSnapshot] | None = None,
) -> list[Video]:
    if not videos:
        return []
    channel_ids = list({v.channel_id for v in videos if v.channel_id})
    channels = {
        row.id: row
        for row in session.scalars(select(Channel).where(Channel.id.in_(channel_ids))).all()
    }
    latest = latest_by_video_id
    if latest is None:
        latest = get_latest_snapshots_for_videos(session, [v.id for v in videos])
    confirmed = load_api_format_confirmed_video_ids(session, [v.id for v in videos])
    return [
        video
        for video in videos
        if monitoring_video_eligible(
            video=video,
            channel=channels.get(video.channel_id),
            latest_snapshot=latest.get(video.id),
            confirmed_regular_ids=confirmed,
        )
    ]
