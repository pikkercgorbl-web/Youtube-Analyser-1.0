"""Manual search pipeline helpers — timing, filter gates, card-level enrichment."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from app.integrations.youtube.client import (
    ChannelDetailModel,
    EnrichedVideoModel,
    VideoSearchModel,
    calc_virality_coefficient,
)


@dataclass
class ManualSearchTiming:
    """Compact stage timings for POST /api/search (no secrets or payloads)."""

    innertube_search_pages: int = 0
    innertube_search_requests: int = 0
    innertube_search_wall_ms: float = 0.0
    html_fallback_used: bool = False
    html_fallback_wall_ms: float = 0.0
    player_backfill_requests: int = 0
    player_backfill_wall_ms: float = 0.0
    channel_browse_unique_channels: int = 0
    channel_browse_http_requests: int = 0
    channel_browse_wall_ms: float = 0.0
    channel_browse_work_ms: float = 0.0
    channel_cache_hits: int = 0
    filter_sort_wall_ms: float = 0.0
    serialize_wall_ms: float = 0.0
    db_wall_ms: float = 0.0
    total_wall_ms: float = 0.0
    result_count: int = 0
    channel_browse_skipped: bool = False

    def to_log_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v not in (0, 0.0, False, None)}


def has_known_subscriber_count(item: EnrichedVideoModel) -> bool:
    """True when search or browse already provided a positive subscriber count."""
    if item.channel.subscribers_count > 0:
        return True
    video_subs = getattr(item.video, "subscribers_count", 0) or 0
    return video_subs > 0


def subscribers_enrichment_needed(items: list[EnrichedVideoModel]) -> bool:
    """True when at least one result has channel_id but no subscriber count yet."""
    for item in items:
        channel_id = (item.video.channel_id or "").strip()
        if not channel_id:
            continue
        if not has_known_subscriber_count(item):
            return True
    return False


def channels_missing_subscriber_details(items: list[EnrichedVideoModel]) -> list[str]:
    """Unique channel ids that still need browse for subscriber counts."""
    channels_with_subs: set[str] = set()
    for item in items:
        channel_id = (item.video.channel_id or "").strip()
        if channel_id and has_known_subscriber_count(item):
            channels_with_subs.add(channel_id)
    missing: list[str] = []
    seen: set[str] = set()
    for item in items:
        channel_id = (item.video.channel_id or "").strip()
        if not channel_id or channel_id in channels_with_subs or channel_id in seen:
            continue
        seen.add(channel_id)
        missing.append(channel_id)
    return missing


def propagate_subscribers_within_batch(items: list[EnrichedVideoModel]) -> list[EnrichedVideoModel]:
    """Copy known subscriber counts to other videos from the same channel in one batch."""
    by_channel: dict[str, int] = {}
    for item in items:
        channel_id = (item.video.channel_id or "").strip()
        if not channel_id:
            continue
        for subs in (item.channel.subscribers_count, item.video.subscribers_count):
            if subs and subs > 0:
                by_channel[channel_id] = max(by_channel.get(channel_id, 0), subs)
    if not by_channel:
        return items

    merged: list[EnrichedVideoModel] = []
    for item in items:
        if has_known_subscriber_count(item):
            merged.append(item)
            continue
        channel_id = (item.video.channel_id or "").strip()
        fill = by_channel.get(channel_id, 0)
        if fill > 0:
            channel = item.channel.model_copy(update={"subscribers_count": fill})
            views = item.video.views_count if item.video.views_count > 0 else 0
            merged.append(
                EnrichedVideoModel(
                    video=item.video,
                    channel=channel,
                    virality_coefficient=calc_virality_coefficient(views, fill),
                ),
            )
        else:
            merged.append(item)
    return merged


def channel_browse_needed(filters_config: dict[str, Any], sort_by: str) -> bool:
    """True when filters/sort require InnerTube channel About/browse metadata."""
    for key in (
        "channel_views_min",
        "channel_views_max",
        "channel_videos_min",
        "channel_videos_max",
        "channel_age_min",
        "channel_age_max",
    ):
        if filters_config.get(key) not in (None, ""):
            return True
    return False


def enriched_models_from_search_cards(videos: list[VideoSearchModel]) -> list[EnrichedVideoModel]:
    """Build enriched rows from InnerTube search card fields (no channel browse)."""
    out: list[EnrichedVideoModel] = []
    for video in videos:
        subs = video.subscribers_count if video.subscribers_count > 0 else 0
        channel = ChannelDetailModel(
            subscribers_count=subs,
            channel_avatar_url=video.channel_avatar_url or "",
        )
        views = video.views_count if video.views_count > 0 else 0
        out.append(
            EnrichedVideoModel(
                video=video,
                channel=channel,
                virality_coefficient=calc_virality_coefficient(views, subs),
            ),
        )
    return out


def merge_channel_details(
    items: list[EnrichedVideoModel],
    channel_map: dict[str, ChannelDetailModel],
) -> list[EnrichedVideoModel]:
    merged: list[EnrichedVideoModel] = []
    for item in items:
        channel = channel_map.get(item.video.channel_id) or item.channel
        subs = channel.subscribers_count if channel.subscribers_count > 0 else 0
        views = item.video.views_count if item.video.views_count > 0 else 0
        merged.append(
            EnrichedVideoModel(
                video=item.video,
                channel=channel,
                virality_coefficient=calc_virality_coefficient(views, subs),
            ),
        )
    return merged


class StageTimer:
    def __init__(self, timing: ManualSearchTiming, field_name: str) -> None:
        self._timing = timing
        self._field = field_name
        self._start = 0.0

    def __enter__(self) -> StageTimer:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args: object) -> None:
        elapsed_ms = (time.perf_counter() - self._start) * 1000.0
        setattr(self._timing, self._field, getattr(self._timing, self._field) + elapsed_ms)
