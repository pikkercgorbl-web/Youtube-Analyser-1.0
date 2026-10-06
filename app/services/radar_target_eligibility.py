"""Unified Radar target eligibility (Stage 2): confirmed regular video, known subs ≤ cap."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from app.models.orm import Channel, Video, VideoFormat, VideoSnapshot

RADAR_MAX_CHANNEL_SUBSCRIBERS = 100_000

REJECTION_STREAM = "stream"
REJECTION_SHORT = "short"
REJECTION_UNKNOWN_FORMAT = "unknown_format"
REJECTION_OVER_SUBSCRIBER_LIMIT = "over_subscriber_limit"
REJECTION_UNKNOWN_SUBSCRIBERS = "unknown_subscribers"


def is_confirmed_regular_format(content_format: VideoFormat) -> bool:
    return content_format in (VideoFormat.MEDIUM, VideoFormat.LONG)


def resolve_known_subscribers(
    *,
    channel: Channel | None,
    latest_snapshot: VideoSnapshot | None,
) -> int | None:
    """
    channels.list API status wins over VideoSnapshot when the channel was checked.

    Unchecked Channel.subscribers_count alone is not trusted (legacy default/zero).
    """
    if channel is not None:
        status = channel.subscribers_api_status
        if status in ("hidden", "missing", "failed"):
            return None
        if status == "known":
            return int(channel.subscribers_count or 0)
    if latest_snapshot is not None and latest_snapshot.subscribers is not None:
        return int(latest_snapshot.subscribers)
    return None


def resolve_subscriber_provenance(
    *,
    channel: Channel | None,
    latest_snapshot: VideoSnapshot | None,
) -> tuple[int | None, str | None]:
    """Return (count, source) where source is channel_api | snapshot."""
    if channel is not None:
        status = channel.subscribers_api_status
        if status in ("hidden", "missing", "failed"):
            return None, None
        if status == "known":
            return int(channel.subscribers_count or 0), "channel_api"
    if latest_snapshot is not None and latest_snapshot.subscribers is not None:
        return int(latest_snapshot.subscribers), "snapshot"
    return None, None


def radar_target_rejection_reason(
    *,
    content_format: VideoFormat,
    channel: Channel | None,
    latest_snapshot: VideoSnapshot | None,
) -> str | None:
    if content_format == VideoFormat.LIVE:
        return REJECTION_STREAM
    if content_format == VideoFormat.SHORT:
        return REJECTION_SHORT
    if content_format == VideoFormat.UNKNOWN or not is_confirmed_regular_format(content_format):
        return REJECTION_UNKNOWN_FORMAT
    subscribers = resolve_known_subscribers(channel=channel, latest_snapshot=latest_snapshot)
    if subscribers is None:
        return REJECTION_UNKNOWN_SUBSCRIBERS
    if subscribers > RADAR_MAX_CHANNEL_SUBSCRIBERS:
        return REJECTION_OVER_SUBSCRIBER_LIMIT
    return None


def radar_target_eligible(
    *,
    video: Video,
    channel: Channel | None,
    latest_snapshot: VideoSnapshot | None,
) -> bool:
    return radar_target_rejection_reason(
        content_format=video.content_format,
        channel=channel,
        latest_snapshot=latest_snapshot,
    ) is None


@dataclass
class RadarEligibilityStats:
    eligible: int = 0
    rejections: Counter[str] = field(default_factory=Counter)
    rejection_video_ids: dict[str, set[str]] = field(default_factory=dict)

    def record(self, reason: str | None, *, video_id: str | None = None) -> None:
        if reason is None:
            self.eligible += 1
        else:
            self.rejections[reason] += 1
            if video_id:
                self.rejection_video_ids.setdefault(reason, set()).add(video_id)

    def to_dict(self) -> dict[str, int]:
        out = {key: int(count) for key, count in self.rejections.items()}
        out["eligible"] = self.eligible
        return out

    def unique_rejection_summary(self) -> dict[str, object]:
        return {
            reason: {
                "unique_videos": len(ids),
                "video_ids": sorted(ids),
            }
            for reason, ids in self.rejection_video_ids.items()
        }


def summarize_video_eligibility(
    items: list[tuple[Video, Channel | None, VideoSnapshot | None]],
) -> RadarEligibilityStats:
    stats = RadarEligibilityStats()
    for video, channel, snap in items:
        reason = radar_target_rejection_reason(
            content_format=video.content_format,
            channel=channel,
            latest_snapshot=snap,
        )
        stats.record(reason, video_id=video.id)
    return stats
