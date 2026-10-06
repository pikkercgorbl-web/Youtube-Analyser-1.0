"""Map YouTube Data API videos.list items to VideoFormat (Stage 2)."""

from __future__ import annotations

from typing import Any

from app.integrations.youtube.client import YouTubeVideoDetails
from app.models.orm import VideoFormat
from app.services.radar_candidate_enrichment import SHORT_DURATION_SECONDS

_LBC_LIVE = frozenset({"live"})
_LBC_UPCOMING = frozenset({"upcoming"})
_LBC_NONE = frozenset({"none", ""})


def live_fields_from_videos_list_item(item: dict[str, Any]) -> tuple[str | None, bool]:
    snippet = item.get("snippet") or {}
    lbc = snippet.get("liveBroadcastContent")
    live_bc = str(lbc).strip().lower() if lbc is not None else None
    streaming = item.get("liveStreamingDetails")
    has_streaming = isinstance(streaming, dict) and bool(streaming)
    return live_bc, has_streaming


def infer_video_format_from_videos_list_item(item: dict[str, Any]) -> VideoFormat | None:
    """None when the response is insufficient to leave UNKNOWN unchanged."""
    from app.utils.duration import parse_iso8601_duration

    content_details = item.get("contentDetails") or {}
    duration_raw = content_details.get("duration")
    duration_seconds: int | None = None
    if isinstance(duration_raw, str) and duration_raw:
        duration_seconds = parse_iso8601_duration(duration_raw)

    live_bc, has_streaming = live_fields_from_videos_list_item(item)
    if live_bc in _LBC_LIVE or live_bc in _LBC_UPCOMING:
        return VideoFormat.LIVE
    if has_streaming:
        return VideoFormat.LIVE
    if live_bc not in _LBC_NONE and live_bc is not None:
        return None
    if duration_seconds is None:
        return None
    if duration_seconds <= 0:
        return None
    if duration_seconds < SHORT_DURATION_SECONDS:
        return VideoFormat.SHORT
    return VideoFormat.MEDIUM


def infer_video_format_from_details(details: YouTubeVideoDetails) -> VideoFormat | None:
    live_bc = (details.live_broadcast_content or "").strip().lower() or None
    if live_bc in _LBC_LIVE or live_bc in _LBC_UPCOMING:
        return VideoFormat.LIVE
    if details.has_live_streaming_details:
        return VideoFormat.LIVE
    if live_bc not in _LBC_NONE and live_bc is not None:
        return None
    duration = details.duration_seconds
    if duration is None or duration <= 0:
        return None
    if duration < SHORT_DURATION_SECONDS:
        return VideoFormat.SHORT
    return VideoFormat.MEDIUM


def merge_api_content_format(existing: VideoFormat, inferred: VideoFormat | None) -> VideoFormat:
    if inferred is None:
        return existing
    if inferred == VideoFormat.SHORT:
        return VideoFormat.SHORT
    if existing == VideoFormat.LIVE and inferred in (
        VideoFormat.MEDIUM,
        VideoFormat.LONG,
        VideoFormat.UNKNOWN,
    ):
        return VideoFormat.LIVE
    if inferred == VideoFormat.UNKNOWN and existing != VideoFormat.UNKNOWN:
        return existing
    return inferred


def snapshot_format_flags_from_details(
    details: YouTubeVideoDetails,
) -> tuple[str | None, bool, bool]:
    """Map API details to snapshot ``content_format`` / short / live flags."""
    fmt = infer_video_format_from_details(details)
    if fmt == VideoFormat.SHORT:
        return "short", True, False
    if fmt == VideoFormat.LIVE:
        return "live", False, True
    if fmt in (VideoFormat.MEDIUM, VideoFormat.LONG):
        return "regular", False, False
    return None, False, False


def chunk_video_ids(video_ids: list[str], *, batch_size: int = 50) -> list[list[str]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    return [video_ids[i : i + batch_size] for i in range(0, len(video_ids), batch_size)]
