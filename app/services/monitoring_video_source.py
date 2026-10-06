"""Load monitorable videos for automatic revisit cycles (Stage 1.13C)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import Channel, Video, VideoFormat, VideoSnapshot
from app.services.metrics import ensure_utc, utc_now
from app.services.monitoring_radar_eligibility import monitoring_video_eligible
from app.services.video_format_api_verification import load_api_format_confirmed_video_ids
from app.services.video_snapshot_storage import get_latest_snapshots_for_videos


@dataclass(frozen=True, slots=True)
class MonitoredVideoState:
    video_id: str
    channel_id: str
    published_at: datetime
    raw_vph: float | None
    age_hours: float | None
    content_format: str | None
    is_short: bool
    is_live: bool
    channel_velocity_baseline_status: str | None = None
    vph_vs_channel_median: float | None = None


def _format_flags(video_format: VideoFormat) -> tuple[str | None, bool, bool]:
    if video_format == VideoFormat.SHORT:
        return "short", True, False
    if video_format == VideoFormat.LIVE:
        return "live", False, True
    if video_format in (VideoFormat.MEDIUM, VideoFormat.LONG):
        return "regular", False, False
    return "unknown", False, False


def _derive_vph(*, views: int | None, age_hours: float | None, snapshot_vph: float | None) -> float | None:
    if snapshot_vph is not None:
        return float(snapshot_vph)
    if views is None or age_hours is None or age_hours <= 0:
        return None
    return round(float(views) / age_hours, 4)


def _state_from_video(
    video: Video,
    *,
    now: datetime,
    latest_snapshot: VideoSnapshot | None,
) -> MonitoredVideoState:
    published_at = ensure_utc(video.published_at)
    age_hours = max((ensure_utc(now) - published_at).total_seconds() / 3600.0, 0.0)
    content_format, is_short, is_live = _format_flags(video.content_format)
    views = latest_snapshot.views if latest_snapshot and latest_snapshot.views is not None else video.views_count
    snapshot_vph = latest_snapshot.vph if latest_snapshot else None
    return MonitoredVideoState(
        video_id=video.id,
        channel_id=video.channel_id,
        published_at=published_at,
        raw_vph=_derive_vph(views=views, age_hours=age_hours, snapshot_vph=snapshot_vph),
        age_hours=round(age_hours, 4),
        content_format=content_format,
        is_short=is_short,
        is_live=is_live,
    )


def load_monitored_video_states(
    session: Session,
    *,
    now: datetime | None = None,
    max_videos: int | None = None,
) -> list[MonitoredVideoState]:
    """
    Source of truth precedence for monitoring inputs:

    1. Latest VideoSnapshot (views/VPH when present)
    2. Video entity fields (published_at, channel_id, format, views_count)
    """
    reference = now or utc_now()
    stmt = select(Video).where(
        Video.content_format.not_in((VideoFormat.SHORT, VideoFormat.LIVE, VideoFormat.UNKNOWN)),
    ).order_by(Video.id.asc())
    if max_videos is not None:
        stmt = stmt.limit(max_videos)
    videos = list(session.scalars(stmt).all())
    video_ids = [video.id for video in videos]
    latest_by_video_id = get_latest_snapshots_for_videos(session, video_ids)
    channel_ids = list({video.channel_id for video in videos if video.channel_id})
    channels_by_id: dict[str, Channel] = {}
    if channel_ids:
        for chunk_start in range(0, len(channel_ids), 400):
            chunk = channel_ids[chunk_start : chunk_start + 400]
            for row in session.scalars(select(Channel).where(Channel.id.in_(chunk))).all():
                channels_by_id[row.id] = row

    confirmed = load_api_format_confirmed_video_ids(session, video_ids)
    states: list[MonitoredVideoState] = []
    for video in videos:
        latest = latest_by_video_id.get(video.id)
        channel = channels_by_id.get(video.channel_id)
        if not monitoring_video_eligible(
            video=video,
            channel=channel,
            latest_snapshot=latest,
            confirmed_regular_ids=confirmed,
        ):
            continue
        states.append(_state_from_video(video, now=reference, latest_snapshot=latest))
    return states
