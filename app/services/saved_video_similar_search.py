"""InnerTube search for SavedVideo similar-watch (no Discovery persist)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.integrations.youtube.client import VideoSearchModel, filter_radar_videos_by_format, iter_radar_search_pages
from app.services.explosive_channels_radar_worker import get_radar_content_filters
from app.services.saved_video_similar_watch_config import saved_video_similar_watch_settings

logger = logging.getLogger(__name__)


@dataclass
class SimilarQuerySearchResult:
    query: str
    videos: list[VideoSearchModel] = field(default_factory=list)
    pages_scanned: int = 0
    error: str | None = None


async def search_similar_videos_for_query(
    query: str,
    *,
    exclude_video_ids: frozenset[str],
    max_pages: int | None = None,
) -> SimilarQuerySearchResult:
    """Run InnerTube search; format filter only — no radar qualification thresholds."""
    cfg = saved_video_similar_watch_settings
    pages_limit = max(1, max_pages or cfg.max_pages_per_query)
    result = SimilarQuerySearchResult(query=query)
    content_filters = get_radar_content_filters()
    unique: dict[str, VideoSearchModel] = {}
    try:
        async for page_batch in iter_radar_search_pages(
            query,
            sort_by_upload_date=True,
            max_pages=pages_limit,
        ):
            result.pages_scanned += 1
            filtered = filter_radar_videos_by_format(page_batch.videos, content_filters)
            for video in filtered:
                if video.video_id in exclude_video_ids:
                    continue
                if video.video_id not in unique:
                    unique[video.video_id] = video
    except Exception as exc:
        logger.warning("similar_watch query=%r search failed: %s", query, exc)
        result.error = str(exc)
    result.videos = list(unique.values())
    return result


def video_search_to_payload(video: VideoSearchModel, *, matched_query: str) -> dict:
    return {
        "video_id": video.video_id,
        "title": video.title,
        "channel_id": video.channel_id,
        "channel_title": video.channel_title,
        "views_count": video.views_count,
        "published_text": video.published_text,
        "duration_text": video.duration_text,
        "thumbnail_url": video.thumbnail_url,
        "matched_query": matched_query,
        "is_short": video.is_short,
        "is_live": video.is_live,
    }
