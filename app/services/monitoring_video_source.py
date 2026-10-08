"""Load monitorable videos for automatic revisit cycles (Stage 1.13C)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session

from app.models.orm import (
    Channel,
    KeywordDiscoveryHit,
    Video,
    VideoFormat,
    VideoFormatEnrichmentAttempt,
    VideoSnapshot,
)
from app.services.channel_subscriber_backfill import SUBSCRIBERS_API_KNOWN
from app.services.historical_video_format_verification import OUTCOME_CONFIRMED_REGULAR
from app.services.metrics import ensure_utc, utc_now
from app.services.monitoring_radar_eligibility import monitoring_video_eligible
from app.services.radar_target_eligibility import RADAR_MAX_CHANNEL_SUBSCRIBERS
from app.services.video_format_api_verification import load_api_format_confirmed_video_ids
from app.services.snapshot_measurement import (
    current_video_age_hours,
    derive_latest_measurement,
)
from app.services.video_snapshot_storage import get_latest_snapshots_for_videos

_MONITORING_CANDIDATE_PAGE = 400


def _confirmed_regular_exists():
    return exists().where(
        and_(
            VideoFormatEnrichmentAttempt.video_id == Video.id,
            VideoFormatEnrichmentAttempt.last_outcome == OUTCOME_CONFIRMED_REGULAR,
        ),
    )


def iter_monitoring_candidate_videos(
    session: Session,
    *,
    page_size: int = _MONITORING_CANDIDATE_PAGE,
) -> Iterator[list[Video]]:
    """
    Keyset pages of videos that may enter monitoring (SQL prefilter).

    Includes MEDIUM/LONG with persisted confirmed_regular and channels that either
    have known subs within cap or need snapshot-based subscriber resolution.
    """
    channel_ok = and_(
        Channel.subscribers_api_status == SUBSCRIBERS_API_KNOWN,
        Channel.subscribers_count <= RADAR_MAX_CHANNEL_SUBSCRIBERS,
    )
    channel_snapshot_fallback = Channel.subscribers_api_status != SUBSCRIBERS_API_KNOWN

    last_id: str | None = None
    while True:
        stmt = (
            select(Video)
            .join(Channel, Video.channel_id == Channel.id)
            .where(
                Video.content_format.in_((VideoFormat.MEDIUM, VideoFormat.LONG)),
                _confirmed_regular_exists(),
                or_(channel_ok, channel_snapshot_fallback),
            )
            .order_by(Video.id.asc())
            .limit(page_size)
        )
        if last_id is not None:
            stmt = stmt.where(Video.id > last_id)
        page = list(session.scalars(stmt).all())
        if not page:
            break
        yield page
        last_id = page[-1].id


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


def _load_discovery_hits_by_video_id(
    session: Session,
    video_ids: Sequence[str],
) -> dict[str, list[KeywordDiscoveryHit]]:
    """Earliest-first hits per video for discovery-time VPH bootstrap."""
    if not video_ids:
        return {}
    grouped: dict[str, list[KeywordDiscoveryHit]] = defaultdict(list)
    chunk_size = _MONITORING_CANDIDATE_PAGE
    for start in range(0, len(video_ids), chunk_size):
        chunk = list(video_ids[start : start + chunk_size])
        rows = session.scalars(
            select(KeywordDiscoveryHit)
            .where(KeywordDiscoveryHit.video_id.in_(chunk))
            .order_by(KeywordDiscoveryHit.video_id.asc(), KeywordDiscoveryHit.discovered_at.asc()),
        ).all()
        for row in rows:
            grouped[row.video_id].append(row)
    return dict(grouped)


def _state_from_video(
    video: Video,
    *,
    now: datetime,
    latest_snapshot: VideoSnapshot | None,
    discovery_hits: list | None = None,
) -> MonitoredVideoState:
    published_at = ensure_utc(video.published_at)
    content_format, is_short, is_live = _format_flags(video.content_format)
    measurement = derive_latest_measurement(
        video=video,
        latest_snapshot=latest_snapshot,
        discovery_hits=discovery_hits or (),
        compute_before=now,
    )
    age_now = current_video_age_hours(video=video, now=now)
    return MonitoredVideoState(
        video_id=video.id,
        channel_id=video.channel_id,
        published_at=published_at,
        raw_vph=measurement.average_vph,
        age_hours=round(age_now, 4) if age_now is not None else None,
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
    2. Earliest valid KeywordDiscoveryHit (views_at_discovery at discovered_at after API publish)
    3. Otherwise VPH unavailable (Video.views_count is not used for tier)
    """
    reference = now or utc_now()
    states: list[MonitoredVideoState] = []

    for page in iter_monitoring_candidate_videos(session):
        if max_videos is not None and len(states) >= max_videos:
            break
        videos = page
        video_ids = [video.id for video in videos]
        hits_by_video_id = _load_discovery_hits_by_video_id(session, video_ids)
        latest_by_video_id = get_latest_snapshots_for_videos(
            session,
            video_ids,
            compute_before=reference,
        )
        channel_ids = list({video.channel_id for video in videos if video.channel_id})
        channels_by_id: dict[str, Channel] = {}
        if channel_ids:
            for chunk_start in range(0, len(channel_ids), _MONITORING_CANDIDATE_PAGE):
                chunk = channel_ids[chunk_start : chunk_start + _MONITORING_CANDIDATE_PAGE]
                for row in session.scalars(select(Channel).where(Channel.id.in_(chunk))).all():
                    channels_by_id[row.id] = row

        confirmed = load_api_format_confirmed_video_ids(session, video_ids)
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
            states.append(
                _state_from_video(
                    video,
                    now=reference,
                    latest_snapshot=latest,
                    discovery_hits=hits_by_video_id.get(video.id),
                ),
            )
            if max_videos is not None and len(states) >= max_videos:
                return states
    return states
