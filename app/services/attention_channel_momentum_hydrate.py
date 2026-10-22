"""Hydrate channel momentum representative videos from DB (read path only).

Uses frozen measurements from the Attention snapshot when present; otherwise replays
age-aligned selection on VideoSnapshot rows captured no later than the Attention run.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import Video
from app.services.attention_engine_types import (
    ChannelMomentum,
    ChannelRepresentativeVideoEvidence,
    youtube_watch_url,
)
from app.services.channel_momentum_age_vph import select_age_aligned_measurement
from app.services.metrics import ensure_utc
from app.services.video_published_at import published_at_usable_for_momentum
from app.services.video_snapshot_storage import get_snapshots_for_videos

_IN_CHUNK = 400

MEASUREMENT_SOURCE_FROZEN = "attention_snapshot_frozen"
MEASUREMENT_SOURCE_REPLAY = "video_snapshot_replay_before_attention"


def _chunked(ids: list[str], chunk_size: int = _IN_CHUNK):
    for start in range(0, len(ids), chunk_size):
        yield ids[start : start + chunk_size]


def resolve_channel_representative_videos(
    session: Session,
    channels: list[ChannelMomentum] | tuple[ChannelMomentum, ...],
    *,
    attention_computed_at: datetime | None,
    max_videos_per_channel: int = 5,
) -> dict[str, list[dict]]:
    """Resolve representative video payloads keyed by channel_id."""
    channel_list = list(channels)
    if not channel_list:
        return {}

    all_ids: list[str] = []
    for row in channel_list:
        for vid in row.representative_video_ids[:max_videos_per_channel]:
            if vid and vid not in all_ids:
                all_ids.append(vid)

    videos = _load_videos(session, all_ids)
    cutoff = ensure_utc(attention_computed_at) if attention_computed_at is not None else None
    snaps_by_video = _load_snapshots_by_video(session, all_ids, captured_at_lte=cutoff)

    channels_needing_replay: list[ChannelMomentum] = []
    out: dict[str, list[dict]] = {}

    for channel in channel_list:
        if channel.representative_video_evidence:
            out[channel.channel_id] = _items_from_frozen(
                channel,
                videos,
                max_videos_per_channel=max_videos_per_channel,
            )
        else:
            channels_needing_replay.append(channel)

    for channel in channels_needing_replay:
        items: list[dict] = []
        prev_median = channel.previous_median_vph
        threshold = float(channel.improvement_ratio_threshold or 1.5)
        horizon = float(channel.momentum_horizon_hours or 24)
        tolerance = float(channel.momentum_horizon_tolerance_hours or 6.0)
        for video_id in channel.representative_video_ids[:max_videos_per_channel]:
            items.append(
                _hydrate_one(
                    video_id=video_id,
                    video=videos.get(video_id),
                    snapshots=snaps_by_video.get(video_id, []),
                    previous_median=prev_median,
                    threshold=threshold,
                    horizon_hours=horizon,
                    tolerance_hours=tolerance,
                    measurement_source=MEASUREMENT_SOURCE_REPLAY,
                    attention_computed_at=cutoff,
                ),
            )
        out[channel.channel_id] = items

    return out


def hydrate_channel_representative_videos(
    session: Session,
    channels: list[ChannelMomentum] | tuple[ChannelMomentum, ...],
    *,
    max_videos_per_channel: int = 5,
) -> dict[str, list[dict]]:
    """Backward-compatible entry: replay without cutoff (tests only)."""
    return resolve_channel_representative_videos(
        session,
        channels,
        attention_computed_at=None,
        max_videos_per_channel=max_videos_per_channel,
    )


def _load_videos(session: Session, video_ids: list[str]) -> dict[str, Video]:
    videos: dict[str, Video] = {}
    for chunk in _chunked(video_ids):
        if not chunk:
            continue
        for video in session.scalars(select(Video).where(Video.id.in_(chunk))).all():
            videos[video.id] = video
    return videos


def _load_snapshots_by_video(
    session: Session,
    video_ids: list[str],
    *,
    captured_at_lte: datetime | None,
) -> dict[str, list]:
    snaps_by_video: dict[str, list] = defaultdict(list)
    if not video_ids:
        return snaps_by_video
    for snap in get_snapshots_for_videos(session, video_ids, captured_at_lte=captured_at_lte):
        snaps_by_video[snap.video_id].append(snap)
    for vid in snaps_by_video:
        snaps_by_video[vid].sort(key=lambda s: s.captured_at)
    return snaps_by_video


def _items_from_frozen(
    channel: ChannelMomentum,
    videos: dict[str, Video],
    *,
    max_videos_per_channel: int,
) -> list[dict]:
    by_id = {item.video_id: item for item in channel.representative_video_evidence}
    items: list[dict] = []
    for video_id in channel.representative_video_ids[:max_videos_per_channel]:
        frozen = by_id.get(video_id)
        if frozen is None:
            continue
        video = videos.get(video_id)
        items.append(
            _frozen_to_dict(
                frozen,
                video,
                target_horizon_hours=float(channel.momentum_horizon_hours or 24),
            ),
        )
    return items


def _frozen_to_dict(
    frozen: ChannelRepresentativeVideoEvidence,
    video: Video | None,
    *,
    target_horizon_hours: float,
) -> dict:
    return {
        "video_id": frozen.video_id,
        "title": (video.title.strip() if video is not None and video.title else None),
        "youtube_url": youtube_watch_url(frozen.video_id),
        "horizon_vph": frozen.horizon_vph,
        "measured_at": frozen.measured_at,
        "actual_age_hours": frozen.actual_age_hours,
        "target_horizon_hours": target_horizon_hours,
        "vs_previous_median_ratio": frozen.vs_previous_median_ratio,
        "meets_improvement_threshold": frozen.meets_improvement_threshold,
        "snapshot_row_id": frozen.snapshot_row_id,
        "measurement_source": MEASUREMENT_SOURCE_FROZEN,
        "attention_computed_at": None,
        "unavailable_reason": None,
    }


def _hydrate_one(
    *,
    video_id: str,
    video: Video | None,
    snapshots: list,
    previous_median: float | None,
    threshold: float,
    horizon_hours: float,
    tolerance_hours: float,
    measurement_source: str,
    attention_computed_at: datetime | None,
) -> dict:
    base = {
        "video_id": video_id,
        "title": (video.title.strip() if video is not None and video.title else None),
        "youtube_url": youtube_watch_url(video_id),
        "horizon_vph": None,
        "measured_at": None,
        "actual_age_hours": None,
        "target_horizon_hours": horizon_hours,
        "vs_previous_median_ratio": None,
        "meets_improvement_threshold": None,
        "snapshot_row_id": None,
        "measurement_source": measurement_source,
        "attention_computed_at": attention_computed_at,
        "unavailable_reason": None,
    }
    if video is None:
        base["unavailable_reason"] = "video_not_in_db"
        return base
    if video.published_at is None or not published_at_usable_for_momentum(video):
        base["unavailable_reason"] = "published_at_unusable"
        return base
    if not snapshots:
        base["unavailable_reason"] = "no_snapshots_in_db"
        return base

    measurement = select_age_aligned_measurement(
        video_id=video_id,
        published_at=video.published_at,
        snapshots=snapshots,
        horizon_hours=horizon_hours,
        tolerance_hours=tolerance_hours,
    )
    if measurement is None:
        base["unavailable_reason"] = "no_snapshot_near_horizon"
        return base

    base["horizon_vph"] = measurement.vph
    base["measured_at"] = measurement.snapshot_captured_at
    base["actual_age_hours"] = measurement.actual_age_hours
    base["snapshot_row_id"] = measurement.snapshot_row_id
    if previous_median is not None and previous_median > 0:
        ratio = round(measurement.vph / previous_median, 4)
        base["vs_previous_median_ratio"] = ratio
        base["meets_improvement_threshold"] = measurement.vph >= threshold * previous_median
    return base
