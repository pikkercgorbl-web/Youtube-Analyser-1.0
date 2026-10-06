"""Apply YouTube Data API videos.list classification to persisted Video rows (Stage 2.1)."""

from __future__ import annotations

from app.integrations.youtube.client import YouTubeVideoDetails
from app.models.orm import Video, VideoFormat
from app.services.video_format_from_api import infer_video_format_from_details, merge_api_content_format
from app.services.video_published_at import apply_api_published_at


def apply_api_details_to_video_content_format(
    video: Video,
    details: YouTubeVideoDetails,
) -> tuple[VideoFormat, VideoFormat]:
    """
    Update ``Video.content_format`` from API details when inference is conclusive.

    Missing/ambiguous API data leaves the row unchanged (does not confirm regular).
    Confirmed LIVE is never downgraded by a weaker later response.
    """
    previous = video.content_format
    inferred = infer_video_format_from_details(details)
    merged = merge_api_content_format(previous, inferred)
    if merged != previous:
        video.content_format = merged
    apply_api_published_at(video, details.published_at)
    return previous, video.content_format
