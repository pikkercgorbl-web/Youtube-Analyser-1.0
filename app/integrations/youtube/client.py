"""YouTube Data API v3 and InnerTube HTTP client."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import enum
import json
import logging
import re
import time
from pathlib import Path
from typing import Any
from collections.abc import AsyncIterator
from urllib.parse import quote_plus

import httpx
from pydantic import BaseModel, Field, model_validator

from app.integrations.youtube.innertube_metrics import (
    NULL_INNERTUBE_METRICS,
    InnerTubeMetrics,
    innertube_endpoint_key,
)
from app.integrations.youtube.key_manager import YouTubeApiKeyManager
from app.utils.duration import parse_iso8601_duration

INNERTUBE_HL = "en"
INNERTUBE_GL = "US"
INNERTUBE_HL_RU = "ru"
INNERTUBE_GL_RU = "RU"
INNERTUBE_ABOUT_TAB_PARAMS = "EgVhYm91dA=="
CHANNEL_HOME_URL = "https://www.youtube.com/channel/{channel_id}"
YOUTUBE_SEARCH_RESULTS_URL = "https://www.youtube.com/results"
_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
RADAR_SUBSCRIBER_FETCH_DELAY_SECONDS = 1.0
RADAR_SUBSCRIBER_FETCH_CONCURRENCY = 3
_HIDDEN_SUBSCRIBER_NEEDLES = (
    "hidden subscriber",
    "subscribers hidden",
    "subscriber count hidden",
    "скрыт",
    "скрыто",
    "скрыты",
    "private",
)
_ZERO_SUBSCRIBER_NEEDLES = (
    "no subscribers",
    "0 subscribers",
    "без подписчиков",
    "нет подписчиков",
    "zero subscribers",
)
YOUTUBE_API_REGION_CODE = "US"
YOUTUBE_API_RELEVANCE_LANGUAGE = "en"
MAX_SEARCH_PAGES = 100
DEBUG_YT_RESPONSE_PATH = Path(__file__).resolve().parents[3] / "debug_yt_response.json"

SEARCH_VIDEO_RENDERER_KEYS = (
    "videoRenderer",
    "lockupViewModel",
    "compactVideoRenderer",
    "gridVideoRenderer",
    "richItemRenderer",
    "reelItemRenderer",
    "playlistVideoRenderer",
    "shortVideoRenderer",
    "shortsLockupViewModel",
)
SEARCH_CONTINUATION_KEYS = (
    "continuationItemRenderer",
    "continuationEndpoint",
)

logger = logging.getLogger(__name__)


class YouTubeApiError(RuntimeError):
    """Raised when the YouTube API returns an unrecoverable error."""


@dataclass(frozen=True, slots=True)
class YouTubeSearchHit:
    video_id: str
    channel_id: str
    title: str
    published_at: datetime


@dataclass(frozen=True, slots=True)
class YouTubeVideoDetails:
    video_id: str
    channel_id: str
    title: str
    published_at: datetime
    views_count: int | None
    likes_count: int
    comments_count: int
    duration_seconds: int
    tags: tuple[str, ...] = ()
    live_broadcast_content: str | None = None
    has_live_streaming_details: bool = False


@dataclass(frozen=True, slots=True)
class YouTubeChannelDetails:
    channel_id: str
    title: str
    subscribers_count: int | None
    subscribers_known: bool = False
    subscribers_hidden: bool = False


class ChannelDetailModel(BaseModel):
    """Detailed public channel metadata collected from InnerTube browse."""

    subscribers_count: int = Field(default=0, ge=0)
    total_videos: int = Field(default=0, ge=0)
    total_views: int = Field(default=0, ge=0)
    channel_age_days: int | None = Field(default=None, ge=0)
    # Legacy channel flags — no longer used in search filters; candidate for removal.
    is_verified: bool = False
    is_artist: bool = False
    is_kids: bool = False
    channel_avatar_url: str = ""


class LiveBroadcastStatus(str, enum.Enum):
    """Structured live-stream state from InnerTube search cards (not title heuristics)."""

    NONE = "none"
    UPCOMING = "upcoming"
    LIVE = "live"
    COMPLETED = "completed"
    UNKNOWN = "unknown"


class VideoSearchModel(BaseModel):
    """Single video item returned by InnerTube search."""

    video_id: str
    channel_id: str
    channel_title: str = ""
    title: str
    views_count: int = Field(default=0, ge=0)
    published_text: str = ""
    duration_text: str = ""
    thumbnail_url: str = ""
    channel_avatar_url: str = ""
    subscribers_count: int = Field(default=0, ge=0)
    is_short: bool = False
    is_live: bool = False
    live_broadcast_status: LiveBroadcastStatus = LiveBroadcastStatus.NONE
    content_renderer: str = "videoRenderer"

    @model_validator(mode="after")
    def _sync_live_fields(self) -> VideoSearchModel:
        status = self.live_broadcast_status
        if self.is_live and status == LiveBroadcastStatus.NONE:
            object.__setattr__(self, "live_broadcast_status", LiveBroadcastStatus.LIVE)
            status = LiveBroadcastStatus.LIVE
        if status in (LiveBroadcastStatus.UPCOMING, LiveBroadcastStatus.LIVE):
            object.__setattr__(self, "is_live", True)
        elif status == LiveBroadcastStatus.NONE:
            object.__setattr__(self, "is_live", False)
        return self


@dataclass(frozen=True, slots=True)
class SearchPageBatch:
    """One InnerTube search results page before client-side filtering."""

    videos: list[VideoSearchModel]
    renderer_counts: dict[str, int]
    parse_skipped: int = 0


class EnrichedVideoModel(BaseModel):
    """Video search result enriched with channel metadata and virality."""

    video: VideoSearchModel
    channel: ChannelDetailModel
    virality_coefficient: float = Field(ge=0)


class ChannelVideoBrowseModel(BaseModel):
    """Video item parsed from a channel browse Videos tab."""

    video_id: str
    title: str
    url: str
    thumbnail_url: str = ""
    views_count: int = Field(default=0, ge=0)
    published_text: str = ""
    duration_text: str = ""
    virality_coefficient: float = Field(default=0, ge=0)


class ChannelAnalysisModel(BaseModel):
    """Result of analyzing a channel's recent uploads."""

    channel_id: str
    channel_title: str = ""
    subscribers_count: int = Field(default=0, ge=0)
    channel_avatar_url: str = ""
    channel_age_days: int = Field(default=0, ge=0)
    total_views: int = Field(default=0, ge=0)
    videos: list[ChannelVideoBrowseModel] = Field(default_factory=list)


class YouTubeApiClient:
    """Thin wrapper around search.list, videos.list, and channels.list."""

    BASE_URL = "https://www.googleapis.com/youtube/v3"
    INNERTUBE_BROWSE_URL = "https://www.youtube.com/youtubei/v1/browse"
    INNERTUBE_SEARCH_URL = "https://www.youtube.com/youtubei/v1/search"
    INNERTUBE_PLAYER_URL = "https://www.youtube.com/youtubei/v1/player"
    INNERTUBE_RESOLVE_URL = "https://www.youtube.com/youtubei/v1/navigation/resolve_url"
    INNERTUBE_SEARCH_SUGGESTIONS_URL = (
        "https://www.youtube.com/youtubei/v1/music/get_search_suggestions"
    )
    GOOGLE_SUGGEST_URL = "https://clients1.google.com/complete/search"
    QUOTA_ERROR_REASONS = frozenset({"quotaExceeded", "dailyLimitExceeded", "keyInvalid"})
    _INNERTUBE_CHANNEL_CONCURRENCY = 5
    _INNERTUBE_CHANNEL_DELAY_SECONDS = 0.25
    _INNERTUBE_SUGGESTIONS_TIMEOUT = 8.0
    _SEARCH_SUGGESTIONS_LIMIT = 10

    def __init__(
        self,
        key_manager: YouTubeApiKeyManager,
        *,
        timeout: float = 20.0,
        innertube_metrics: InnerTubeMetrics | None = None,
    ) -> None:
        self._key_manager = key_manager
        self._timeout = timeout
        self._innertube_metrics = (
            innertube_metrics if innertube_metrics is not None else NULL_INNERTUBE_METRICS
        )

    def search_videos(
        self,
        query: str,
        *,
        published_after: datetime,
        max_results: int = 50,
    ) -> list[YouTubeSearchHit]:
        params: dict[str, str | int] = {
            "part": "snippet",
            "type": "video",
            "q": query,
            "order": "date",
            "publishedAfter": _format_rfc3339(published_after),
            "maxResults": min(max_results, 50),
            "regionCode": YOUTUBE_API_REGION_CODE,
            "relevanceLanguage": YOUTUBE_API_RELEVANCE_LANGUAGE,
        }
        payload = self._request("search", params)
        hits: list[YouTubeSearchHit] = []

        for item in payload.get("items", []):
            snippet = item.get("snippet", {})
            video_id = item.get("id", {}).get("videoId")
            channel_id = snippet.get("channelId")
            published_raw = snippet.get("publishedAt")
            title = snippet.get("title")
            if not video_id or not channel_id or not published_raw or not title:
                continue
            hits.append(
                YouTubeSearchHit(
                    video_id=video_id,
                    channel_id=channel_id,
                    title=title,
                    published_at=_parse_rfc3339(published_raw),
                ),
            )
        return hits

    def search_videos_relevance(
        self,
        query: str,
        *,
        max_results: int = 20,
    ) -> list[YouTubeSearchHit]:
        """Search videos by relevance (SERP order) without a publish date filter."""
        payload = self._request(
            "search",
            {
                "part": "snippet",
                "type": "video",
                "q": query,
                "order": "relevance",
                "maxResults": min(max_results, 50),
                "regionCode": YOUTUBE_API_REGION_CODE,
                "relevanceLanguage": YOUTUBE_API_RELEVANCE_LANGUAGE,
            },
        )
        hits: list[YouTubeSearchHit] = []

        for item in payload.get("items", []):
            snippet = item.get("snippet", {})
            video_id = item.get("id", {}).get("videoId")
            channel_id = snippet.get("channelId")
            published_raw = snippet.get("publishedAt")
            title = snippet.get("title")
            if not video_id or not channel_id or not published_raw or not title:
                continue
            hits.append(
                YouTubeSearchHit(
                    video_id=video_id,
                    channel_id=channel_id,
                    title=title,
                    published_at=_parse_rfc3339(published_raw),
                ),
            )
        return hits

    def get_videos(self, video_ids: list[str]) -> list[YouTubeVideoDetails]:
        if not video_ids:
            return []

        results: list[YouTubeVideoDetails] = []
        for chunk_start in range(0, len(video_ids), 50):
            chunk = video_ids[chunk_start : chunk_start + 50]
            payload = self._request(
                "videos",
                {
                    "part": "snippet,statistics,contentDetails,liveStreamingDetails",
                    "id": ",".join(chunk),
                    "maxResults": len(chunk),
                },
            )
            for item in payload.get("items", []):
                video_id = item.get("id")
                snippet = item.get("snippet", {})
                statistics = item.get("statistics", {})
                content_details = item.get("contentDetails", {})
                if not video_id:
                    continue
                lbc_raw = snippet.get("liveBroadcastContent")
                live_bc = str(lbc_raw).strip().lower() if lbc_raw is not None else None
                streaming = item.get("liveStreamingDetails")
                has_streaming = isinstance(streaming, dict) and bool(streaming)
                results.append(
                    YouTubeVideoDetails(
                        video_id=video_id,
                        channel_id=snippet.get("channelId", ""),
                        title=snippet.get("title", ""),
                        published_at=_parse_rfc3339(snippet.get("publishedAt", "")),
                        views_count=_statistics_view_count(statistics),
                        likes_count=_safe_int(statistics.get("likeCount")),
                        comments_count=_safe_int(statistics.get("commentCount")),
                        duration_seconds=parse_iso8601_duration(
                            content_details.get("duration", "PT0S"),
                        ),
                        tags=tuple(snippet.get("tags") or []),
                        live_broadcast_content=live_bc,
                        has_live_streaming_details=has_streaming,
                    ),
                )
        return results

    def resolve_channel_id(self, channel_key: str) -> str | None:
        """
        Resolve a normalized channel key to a YouTube channel ID.

        Accepts raw `UC...` IDs and `handle:<name>` keys produced by
        `parse_youtube_channel_ref`.
        """
        if channel_key.startswith("handle:"):
            handle = channel_key.removeprefix("handle:")
            payload = self._request(
                "channels",
                {"part": "id", "forHandle": handle},
            )
        else:
            payload = self._request(
                "channels",
                {"part": "id", "id": channel_key},
            )

        items = payload.get("items", [])
        if not items:
            return None
        return items[0].get("id")

    def get_channel_recent_videos(
        self,
        channel_id: str,
        *,
        max_results: int = 30,
    ) -> list[YouTubeVideoDetails]:
        """Fetch the most recent uploads for a channel ordered by publish date."""
        payload = self._request(
            "search",
            {
                "part": "snippet",
                "channelId": channel_id,
                "type": "video",
                "order": "date",
                "maxResults": min(max_results, 50),
            },
        )
        video_ids: list[str] = []
        for item in payload.get("items", []):
            video_id = item.get("id", {}).get("videoId")
            if video_id:
                video_ids.append(video_id)
        return self.get_videos(video_ids)

    async def search(
        self,
        query: str,
        *,
        max_results: int = 50,
        max_pages: int | None = None,
        sort_by_upload_date: bool = False,
    ) -> list[VideoSearchModel]:
        """Search videos through InnerTube and return parsed Pydantic models."""
        if not query.strip():
            return []

        if max_pages is not None:
            page_limit = max(1, min(max_pages, MAX_SEARCH_PAGES))
            result_limit = page_limit * 50
        else:
            page_limit = None
            result_limit = max(1, min(max_results, 50))

        context = _build_innertube_context(query)
        results: list[VideoSearchModel] = []
        seen_video_ids: set[str] = set()
        continuation: str | None = None
        pages_fetched = 0

        parse_skipped_total = 0

        while len(results) < result_limit:
            logger.info("Обработка страницы %s...", pages_fetched + 1)
            payload: dict[str, Any] = {"context": context}
            if continuation:
                payload["continuation"] = continuation
            else:
                payload["query"] = query
                if sort_by_upload_date:
                    payload["params"] = "EgQIAhAB"

            response = await self._innertube_request(
                payload,
                url=self.INNERTUBE_SEARCH_URL,
            )
            pages_fetched += 1
            page_videos, parse_skipped, renderer_counts = _parse_search_videos(response)
            parse_skipped_total += parse_skipped
            _log_search_page_renderer_counts(
                pages_fetched,
                renderer_counts,
                parsed_count=len(page_videos),
                parse_skipped=parse_skipped,
            )
            for video in page_videos:
                if video.video_id in seen_video_ids:
                    continue
                seen_video_ids.add(video.video_id)
                results.append(video)
                if len(results) >= result_limit:
                    break

            if page_limit is not None and pages_fetched >= page_limit:
                logger.info(
                    "Достигнут лимит страниц (%s), поиск остановлен",
                    page_limit,
                )
                break

            if len(results) >= result_limit:
                break

            continuation = _extract_search_continuation(response)
            if not continuation:
                logger.info("Токен следующей страницы не найден, поиск остановлен")
                break
            if not page_videos:
                logger.info(
                    "Страница %s не содержит видео, переход к следующей странице",
                    pages_fetched,
                )

        if parse_skipped_total:
            logger.info(
                "Поиск %r: всего пропущено видео из-за ошибок парсинга: %s",
                query,
                parse_skipped_total,
            )

        if not results and _contains_cyrillic(query):
            results = await self._fetch_search_via_html_page(query, limit=result_limit)

        return results[:result_limit]

    async def iter_search_pages(
        self,
        query: str,
        *,
        sort_by_upload_date: bool = False,
        max_pages: int = MAX_SEARCH_PAGES,
    ) -> AsyncIterator[SearchPageBatch]:
        """Yield deduplicated video batches page-by-page using InnerTube continuations."""
        if not query.strip():
            return

        context = _build_innertube_context(query)
        seen_video_ids: set[str] = set()
        continuation: str | None = None
        pages_fetched = 0
        page_limit = max(1, min(max_pages, MAX_SEARCH_PAGES))
        yielded_any = False
        yielded_count = 0
        parse_skipped_total = 0

        while pages_fetched < page_limit:
            logger.info("Обработка страницы %s...", pages_fetched + 1)
            payload: dict[str, Any] = {"context": context}
            if continuation:
                payload["continuation"] = continuation
            else:
                payload["query"] = query
                if sort_by_upload_date:
                    payload["params"] = "EgQIAhAB"

            response = await self._innertube_request(
                payload,
                url=self.INNERTUBE_SEARCH_URL,
            )
            pages_fetched += 1
            page_videos, parse_skipped, renderer_counts = _parse_search_videos(response)
            parse_skipped_total += parse_skipped
            _log_search_page_renderer_counts(
                pages_fetched,
                renderer_counts,
                parsed_count=len(page_videos),
                parse_skipped=parse_skipped,
            )

            deduped: list[VideoSearchModel] = []
            for video in page_videos:
                if video.video_id in seen_video_ids:
                    continue
                seen_video_ids.add(video.video_id)
                deduped.append(video)

            if deduped:
                yielded_any = True
                yielded_count += len(deduped)
            yield SearchPageBatch(
                videos=deduped,
                renderer_counts=renderer_counts,
                parse_skipped=parse_skipped,
            )

            if pages_fetched >= page_limit:
                logger.info(
                    "Достигнут лимит страниц (%s), поиск остановлен",
                    page_limit,
                )
                break

            continuation = _extract_search_continuation(response)
            if not continuation:
                logger.info("Токен следующей страницы не найден, поиск остановлен")
                break
            if not page_videos:
                logger.info(
                    "Страница %s не содержит видео, переход к следующей странице",
                    pages_fetched,
                )

        if parse_skipped_total:
            logger.info(
                "Поиск %r: всего пропущено видео из-за ошибок парсинга: %s",
                query,
                parse_skipped_total,
            )

        if _contains_cyrillic(query) and yielded_count < 5:
            html_results = await self._fetch_search_via_html_page(query, limit=50)
            fallback_videos = [
                video
                for video in html_results
                if video.video_id not in seen_video_ids
            ]
            if fallback_videos:
                logger.info(
                    "InnerTube вернул мало видео для %r (%s), использую HTML fallback: %s видео",
                    query,
                    yielded_count,
                    len(fallback_videos),
                )
                yield SearchPageBatch(
                    videos=fallback_videos,
                    renderer_counts={"htmlFallback": len(fallback_videos)},
                )

    async def get_search_suggestions(self, query: str) -> list[str]:
        """Return up to 10 autocomplete suggestions for a YouTube search query."""
        normalized_query = query.strip()
        if not normalized_query:
            return []

        response = await self._innertube_request(
            {
                "context": _build_innertube_suggestions_context(normalized_query),
                "input": normalized_query,
            },
            url=self.INNERTUBE_SEARCH_SUGGESTIONS_URL,
            timeout=self._INNERTUBE_SUGGESTIONS_TIMEOUT,
        )
        suggestions = _parse_search_suggestions(response)

        if len(suggestions) < self._SEARCH_SUGGESTIONS_LIMIT:
            suggestions = _merge_suggestion_lists(
                suggestions,
                await self._fetch_google_search_suggestions(normalized_query),
                limit=self._SEARCH_SUGGESTIONS_LIMIT,
            )

        return suggestions[: self._SEARCH_SUGGESTIONS_LIMIT]

    async def get_related_search_suggestions(
        self,
        query: str,
        *,
        max_suggestions: int = 7,
    ) -> list[str]:
        """Return the most relevant autocomplete suggestions excluding the query itself."""
        suggestions = await self.get_search_suggestions(query)
        return _filter_related_suggestions(query, suggestions, max_suggestions=max_suggestions)

    async def get_channel_details(self, channel_id: str) -> ChannelDetailModel:
        """Fetch detailed public channel metadata through InnerTube browse."""
        if not channel_id.strip():
            msg = "channel_id must not be empty"
            raise ValueError(msg)

        context = _build_innertube_context()
        initial_payload = {
            "context": context,
            "browseId": channel_id,
        }
        initial_response = await self._innertube_request(initial_payload)

        about_params = (
            _find_tab_params(initial_response, ("about", "о канале"))
            or INNERTUBE_ABOUT_TAB_PARAMS
        )
        about_response = await self._innertube_request(
            {
                "context": context,
                "browseId": channel_id,
                "params": about_params,
            },
        )

        responses = [initial_response, about_response]
        continuation_token = _extract_about_panel_continuation(initial_response)
        if continuation_token:
            try:
                about_panel_response = await self._innertube_request(
                    {
                        "context": context,
                        "continuation": continuation_token,
                    },
                )
            except YouTubeApiError:
                pass
            else:
                responses.append(about_panel_response)

        return _parse_channel_details(responses)

    async def get_enriched_search_results(
        self,
        query: str,
        max_results: int = 50,
        *,
        sort_by_upload_date: bool = False,
    ) -> list[EnrichedVideoModel]:
        """Search videos and enrich each result with InnerTube channel metadata."""
        videos = await self.search(
            query,
            max_results=max_results,
            sort_by_upload_date=sort_by_upload_date,
        )
        if not videos:
            return []

        videos = await self._fill_missing_channel_metadata(videos)

        unique_channel_ids = list(
            dict.fromkeys(video.channel_id for video in videos if video.channel_id),
        )
        semaphore = asyncio.Semaphore(self._INNERTUBE_CHANNEL_CONCURRENCY)

        async def fetch_channel(channel_id: str) -> tuple[str, ChannelDetailModel]:
            async with semaphore:
                await asyncio.sleep(self._INNERTUBE_CHANNEL_DELAY_SECONDS)
                try:
                    details = await self.get_channel_details(channel_id)
                except (YouTubeApiError, ValueError):
                    details = ChannelDetailModel()
                return channel_id, details

        channel_pairs = await asyncio.gather(
            *(fetch_channel(channel_id) for channel_id in unique_channel_ids),
        )
        channel_map = dict(channel_pairs)

        enriched: list[EnrichedVideoModel] = []
        for video in videos:
            channel = channel_map.get(video.channel_id, ChannelDetailModel())
            subscribers = max(channel.subscribers_count, 0)
            video_views = max(video.views_count, 0)
            enriched.append(
                EnrichedVideoModel(
                    video=video,
                    channel=channel,
                    virality_coefficient=calc_virality_coefficient(
                        video_views,
                        subscribers,
                    ),
                ),
            )
        return enriched

    async def fetch_video_channel_info(self, video_id: str) -> tuple[str, str]:
        """
        Resolve channel id/title for a video (including Shorts) via InnerTube player.

        Search shelf items often omit channel metadata; the player response includes
        ``videoDetails.channelId`` / ``author`` and microformat fallbacks.
        """
        if not video_id.strip():
            return "", ""

        response = await self._innertube_request(
            {
                "context": _build_innertube_context(),
                "videoId": video_id,
            },
            url=self.INNERTUBE_PLAYER_URL,
        )
        return _parse_player_channel_info(response)

    async def _fill_missing_channel_metadata(
        self,
        videos: list[VideoSearchModel],
    ) -> list[VideoSearchModel]:
        """Backfill channel id/title for Shorts that omit channel data in search JSON."""
        missing = [video for video in videos if not video.channel_id.strip()]
        if not missing:
            return videos

        semaphore = asyncio.Semaphore(self._INNERTUBE_CHANNEL_CONCURRENCY)

        async def resolve(video: VideoSearchModel) -> tuple[str, str, str]:
            async with semaphore:
                await asyncio.sleep(self._INNERTUBE_CHANNEL_DELAY_SECONDS)
                try:
                    channel_id, channel_title = await self.fetch_video_channel_info(
                        video.video_id,
                    )
                except YouTubeApiError:
                    channel_id, channel_title = "", video.channel_title
                return video.video_id, channel_id, channel_title

        resolved_pairs = await asyncio.gather(*(resolve(video) for video in missing))
        resolved_map = {
            video_id: (channel_id, channel_title)
            for video_id, channel_id, channel_title in resolved_pairs
            if channel_id
        }

        if not resolved_map:
            return videos

        updated: list[VideoSearchModel] = []
        for video in videos:
            if video.video_id in resolved_map:
                channel_id, channel_title = resolved_map[video.video_id]
                video = video.model_copy(
                    update={
                        "channel_id": channel_id,
                        "channel_title": channel_title or video.channel_title,
                    },
                )
            updated.append(video)
        return updated

    async def resolve_channel_id_from_url(self, url: str) -> tuple[str, str]:
        """
        Resolve a video or channel URL to ``(channel_id, channel_title_hint)``.

        Video links are resolved through InnerTube ``/player``.
        Channel links use direct ids, ``/channel/``, ``/@handle``, ``/c/`` via ``resolve_url``.
        """
        from app.utils.youtube import YouTubeUrlKind, classify_youtube_url, normalize_youtube_url

        kind, key = classify_youtube_url(url)
        if kind is YouTubeUrlKind.VIDEO:
            channel_id, channel_title = await self.fetch_video_channel_info(key)
            if not channel_id:
                msg = f"Cannot resolve channel for video URL: {url}"
                raise ValueError(msg)
            return channel_id, channel_title

        if _is_channel_id(key):
            return key, ""

        resolved = await self._resolve_url_to_channel_id(normalize_youtube_url(key))
        if not resolved:
            msg = f"Channel not found for URL: {url}"
            raise ValueError(msg)
        return resolved, ""

    async def resolve_channel_identifier(self, identifier: str) -> tuple[str, str]:
        """
        Resolve an extracted channel identifier to ``(channel_id, title_hint)``.

        Accepts ``UC...`` ids, ``@handle`` strings, and normalized channel URLs.
        """
        if _is_channel_id(identifier):
            return identifier.strip(), ""

        if identifier.startswith("@"):
            url = f"https://www.youtube.com/{identifier}"
            return await self.resolve_channel_id_from_url(url)

        if identifier.startswith("http://") or identifier.startswith("https://"):
            return await self.resolve_channel_id_from_url(identifier)

        msg = f"Unsupported channel identifier: {identifier!r}"
        raise ValueError(msg)

    async def iter_channel_videos_tab(
        self,
        channel_id: str,
        *,
        max_pages: int | None = None,
        request_timeout: float | None = None,
    ) -> AsyncIterator[list[ChannelVideoBrowseModel]]:
        """Yield one page of channel Videos tab uploads at a time (InnerTube browse)."""
        if not channel_id.strip():
            msg = "channel_id must not be empty"
            raise ValueError(msg)

        context = _build_innertube_context()
        initial_response = await self._innertube_request(
            {"context": context, "browseId": channel_id},
            timeout=request_timeout,
        )
        videos_params = _find_tab_params(initial_response, ("videos", "видео"))
        if not videos_params:
            msg = f"Videos tab not found for channel {channel_id}"
            raise YouTubeApiError(msg)

        seen_ids: set[str] = set()
        continuation: str | None = None
        first_page = True
        pages_fetched = 0

        while True:
            if max_pages is not None and pages_fetched >= max_pages:
                return

            if first_page:
                payload: dict[str, Any] = {
                    "context": context,
                    "browseId": channel_id,
                    "params": videos_params,
                }
                first_page = False
            else:
                payload = {"context": context, "continuation": continuation}

            response = await self._innertube_request(payload, timeout=request_timeout)
            page_videos = _parse_channel_browse_videos(response, channel_id=channel_id)
            pages_fetched += 1

            deduped_page: list[ChannelVideoBrowseModel] = []
            for video in page_videos:
                if video.video_id in seen_ids:
                    continue
                seen_ids.add(video.video_id)
                deduped_page.append(video)
            if deduped_page:
                yield deduped_page

            continuation = _extract_search_continuation(response)
            if not continuation or not page_videos:
                return

    async def get_channel_videos_tab(
        self,
        channel_id: str,
        *,
        max_results: int = 100,
        max_pages: int | None = None,
        request_timeout: float | None = None,
    ) -> tuple[str, list[ChannelVideoBrowseModel]]:
        """Fetch recent uploads from the channel Videos tab via InnerTube browse."""
        if not channel_id.strip():
            msg = "channel_id must not be empty"
            raise ValueError(msg)

        limit = max(1, min(max_results, 100))
        channel_title = ""
        videos: list[ChannelVideoBrowseModel] = []
        seen_ids: set[str] = set()
        pages_fetched = 0
        async for page_videos in self.iter_channel_videos_tab(
            channel_id,
            max_pages=max_pages,
            request_timeout=request_timeout,
        ):
            pages_fetched += 1
            for video in page_videos:
                if video.video_id in seen_ids:
                    continue
                seen_ids.add(video.video_id)
                videos.append(video)
                if len(videos) >= limit:
                    break
            if len(videos) >= limit:
                break
            if max_pages is not None and pages_fetched >= max_pages:
                break

        if not channel_title:
            channel_title = channel_id
        return channel_title, videos[:limit]

    async def analyze_channel(
        self,
        url: str,
        *,
        max_results: int = 100,
    ) -> ChannelAnalysisModel:
        """Analyze a channel (or channel behind a video URL) and enrich uploads."""
        channel_id, title_hint = await self.resolve_channel_id_from_url(url)

        channel_task = asyncio.create_task(self.get_channel_details(channel_id))
        videos_task = asyncio.create_task(
            self.get_channel_videos_tab(channel_id, max_results=max_results),
        )
        channel_details, (channel_title, videos) = await asyncio.gather(
            channel_task,
            videos_task,
        )

        resolved_title = channel_title or title_hint
        subscribers = channel_details.subscribers_count
        enriched_videos = [
            video.model_copy(
                update={
                    "virality_coefficient": calc_virality_coefficient(
                        video.views_count,
                        subscribers,
                    ),
                },
            )
            for video in videos
        ]

        return ChannelAnalysisModel(
            channel_id=channel_id,
            channel_title=resolved_title,
            subscribers_count=subscribers,
            channel_avatar_url=channel_details.channel_avatar_url,
            channel_age_days=channel_details.channel_age_days or 0,
            total_views=channel_details.total_views,
            videos=enriched_videos,
        )

    async def _resolve_url_to_channel_id(self, url: str) -> str:
        """Resolve a channel page URL to a ``UC...`` id via InnerTube ``resolve_url``."""
        response = await self._innertube_request(
            {"context": _build_innertube_context(), "url": url},
            url=self.INNERTUBE_RESOLVE_URL,
        )
        return _extract_browse_id_from_node(response)

    def get_channels(self, channel_ids: list[str]) -> dict[str, YouTubeChannelDetails]:
        if not channel_ids:
            return {}

        unique_ids = list(dict.fromkeys(channel_ids))
        channels: dict[str, YouTubeChannelDetails] = {}

        for chunk_start in range(0, len(unique_ids), 50):
            chunk = unique_ids[chunk_start : chunk_start + 50]
            payload = self._request(
                "channels",
                {
                    "part": "snippet,statistics",
                    "id": ",".join(chunk),
                    "maxResults": len(chunk),
                },
            )
            for item in payload.get("items", []):
                channel_id = item.get("id")
                if not channel_id:
                    continue
                snippet = item.get("snippet", {})
                statistics = item.get("statistics", {})
                hidden = statistics.get("hiddenSubscriberCount") is True
                raw_subs = statistics.get("subscriberCount")
                if hidden or raw_subs is None:
                    channels[channel_id] = YouTubeChannelDetails(
                        channel_id=channel_id,
                        title=snippet.get("title", ""),
                        subscribers_count=None,
                        subscribers_known=False,
                        subscribers_hidden=hidden,
                    )
                else:
                    channels[channel_id] = YouTubeChannelDetails(
                        channel_id=channel_id,
                        title=snippet.get("title", ""),
                        subscribers_count=_safe_int(raw_subs),
                        subscribers_known=True,
                        subscribers_hidden=False,
                    )
        return channels

    def _request(self, endpoint: str, params: dict[str, str | int]) -> dict[str, Any]:
        attempts = self._key_manager.key_count
        last_error: Exception | None = None

        for _ in range(attempts):
            api_key = self._key_manager.current_key()
            request_params = {**params, "key": api_key}
            try:
                response = httpx.get(
                    f"{self.BASE_URL}/{endpoint}",
                    params=request_params,
                    timeout=self._timeout,
                )
            except httpx.HTTPError as exc:
                last_error = exc
                self._key_manager.rotate()
                continue

            if response.status_code == 200:
                return response.json()

            if self._should_rotate_key(response):
                last_error = YouTubeApiError(
                    f"YouTube API quota/key error on {endpoint}: {response.text}",
                )
                self._key_manager.rotate()
                continue

            raise YouTubeApiError(
                f"YouTube API error {response.status_code} on {endpoint}: {response.text}",
            )

        msg = f"YouTube API request failed after trying all keys: {last_error}"
        raise YouTubeApiError(msg)

    async def _innertube_request(
        self,
        payload: dict[str, Any],
        *,
        url: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        endpoint = url or self.INNERTUBE_BROWSE_URL
        endpoint_key = innertube_endpoint_key(endpoint)
        request_timeout = self._timeout if timeout is None else timeout
        locale_text = _extract_innertube_locale_text(payload)
        hl, _gl = _innertube_locale_for_text(locale_text)
        accept_language = (
            "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
            if hl == INNERTUBE_HL_RU
            else "en-US,en;q=0.9"
        )
        headers = {
            "Accept": "application/json",
            "Accept-Language": accept_language,
            "Content-Type": "application/json; charset=utf-8",
            "Origin": "https://www.youtube.com",
            "Referer": "https://www.youtube.com/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        }
        started = time.perf_counter()
        status_code: int | None = None
        success = False
        error_kind: str | None = None
        try:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            async with httpx.AsyncClient(timeout=request_timeout, headers=headers) as client:
                response = await client.post(
                    endpoint,
                    params={"prettyPrint": "false"},
                    content=body,
                )
            status_code = response.status_code
            if response.status_code != 200:
                error_kind = "http_status"
                raise YouTubeApiError(
                    f"InnerTube request error {response.status_code} on {endpoint}: {response.text}",
                )
            data = response.json()
            _persist_innertube_debug_response(data)
            _warn_innertube_response_blockers(data, endpoint=endpoint)
            success = True
            return data
        except YouTubeApiError:
            raise
        except json.JSONDecodeError:
            error_kind = "json"
            raise
        except httpx.HTTPError:
            error_kind = "network"
            raise
        except Exception:
            error_kind = "other"
            raise
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            self._innertube_metrics.record_request(
                endpoint_key=endpoint_key,
                duration_ms=duration_ms,
                success=success,
                status_code=status_code,
                error_kind=error_kind,
            )

    async def _fetch_search_via_html_page(
        self,
        query: str,
        *,
        limit: int,
    ) -> list[VideoSearchModel]:
        """Fallback for Cyrillic queries when InnerTube POST search returns an empty shelf."""
        search_url = _build_youtube_search_page_url(query)
        headers = _youtube_page_headers(query)
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                headers=headers,
                follow_redirects=True,
            ) as client:
                response = await client.get(search_url)
        except httpx.HTTPError:
            return []

        if response.status_code != 200:
            return []

        initial_data = extract_yt_initial_data(response.text)
        if not initial_data:
            return []

        videos, _parse_skipped, _renderer_counts = _parse_search_videos(initial_data)
        return videos[:limit]

    async def _fetch_google_search_suggestions(self, query: str) -> list[str]:
        """Lightweight fallback used by the main YouTube search bar autocomplete."""
        hl, _gl = _innertube_locale_for_text(query)
        headers = {
            "Accept": "*/*",
            "Accept-Language": (
                "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
                if hl == INNERTUBE_HL_RU
                else "en-US,en;q=0.9"
            ),
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        }
        suggest_url = (
            f"{self.GOOGLE_SUGGEST_URL}?client=youtube&ds=yt&hl={hl}&q={quote_plus(query)}"
        )
        async with httpx.AsyncClient(
            timeout=self._INNERTUBE_SUGGESTIONS_TIMEOUT,
            headers=headers,
        ) as client:
            response = await client.get(suggest_url)
        if response.status_code != 200:
            return []
        return _parse_google_suggest_response(response.text)

    def _should_rotate_key(self, response: httpx.Response) -> bool:
        if response.status_code in {403, 400}:
            try:
                payload = response.json()
            except ValueError:
                return False
            for error in payload.get("error", {}).get("errors", []):
                if error.get("reason") in self.QUOTA_ERROR_REASONS:
                    return True
        return False


def _safe_int(value: str | None) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _statistics_view_count(statistics: dict) -> int | None:
    """None when viewCount absent; explicit 0 when API reports zero."""
    if "viewCount" not in statistics:
        return None
    raw = statistics.get("viewCount")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def calc_virality_coefficient(views_count: int, subscribers_count: int) -> float:
    """Return views / max(subscribers, 1), rounded to 2 decimal places."""
    denominator = max(subscribers_count, 1)
    return round(views_count / denominator, 2)


def parse_subscriber_count(text: str) -> int:
    """
    Parse a YouTube subscriber counter label into an integer.

    Examples: ``1,5 млн подписчиков``, ``234K``, ``10 тыс.``, ``850``.
    Returns ``0`` when the count is hidden, zero, or cannot be parsed.
    """
    raw = _text_from_node(text)
    if not raw:
        return 0

    normalized = (
        raw.replace("\xa0", " ")
        .replace("\u202f", " ")
        .replace("−", "-")
        .strip()
        .lower()
    )
    if not normalized:
        return 0

    if any(needle in normalized for needle in _HIDDEN_SUBSCRIBER_NEEDLES):
        return 0
    if any(needle in normalized for needle in _ZERO_SUBSCRIBER_NEEDLES):
        return 0

    cleaned = re.sub(
        r"\b(?:subscribers?|subscriber|подписчик\w*)\b",
        "",
        normalized,
        flags=re.IGNORECASE,
    ).strip(" .,")

    compact_match = re.search(
        r"(\d+(?:[.,]\d+)?)\s*([kmb]|tys\.?|тыс(?:\.|яч(?:а|ев)?)?|млн|млрд|million|billion|thousand)\b",
        cleaned,
        flags=re.IGNORECASE,
    )
    if compact_match:
        return _parse_counter_number(compact_match.group(1), compact_match.group(2))

    glued_match = re.search(
        r"(\d+(?:[.,]\d+)?)([kmb])\b",
        cleaned,
        flags=re.IGNORECASE,
    )
    if glued_match:
        return _parse_counter_number(glued_match.group(1), glued_match.group(2))

    plain_match = re.search(r"(\d[\d\s.,]*)", cleaned)
    if plain_match:
        return _parse_counter_number(plain_match.group(1), "")

    return 0


def _parse_counter_number(number_raw: str, suffix: str) -> int:
    multiplier = _counter_multiplier(suffix)
    token = number_raw.strip().replace("\xa0", " ").replace("\u202f", " ").replace(" ", "")

    if multiplier > 1:
        token = token.replace(",", ".")
        try:
            return int(float(token) * multiplier)
        except ValueError:
            return 0

    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", token):
        return int(re.sub(r"[.,]", "", token))

    if "," in token and "." not in token:
        parts = token.split(",")
        if len(parts) == 2 and 1 <= len(parts[1]) <= 2:
            try:
                return int(float(f"{parts[0]}.{parts[1]}"))
            except ValueError:
                return 0

    if "." in token:
        try:
            return int(float(token))
        except ValueError:
            return 0

    digits_only = re.sub(r"\D", "", token)
    return int(digits_only) if digits_only else 0


def parse_compact_int(value: Any) -> int:
    """
    Convert localized YouTube counters into integers.

    Examples: "1.2M subscribers", "450K views", "15 тыс. подписчиков",
    "3,5 млн просмотров".
    """
    text = _text_from_node(value).lower()
    if not text:
        return 0

    text = (
        text.replace("\xa0", " ")
        .replace("\u202f", " ")
        .replace("−", "-")
        .strip()
    )
    match = re.search(r"(\d+(?:[\s.,]\d+)*)\s*([a-zа-яё.]*)", text, flags=re.IGNORECASE)
    if not match:
        return 0

    number_raw = match.group(1).strip()
    suffix = match.group(2).strip(".")
    multiplier = _counter_multiplier(suffix)

    number_text = number_raw.replace(" ", "")
    if multiplier > 1:
        number_text = number_text.replace(",", ".")
    elif re.search(r"[,.]\d{3}(?:\D|$)", number_text):
        number_text = number_text.replace(",", "").replace(".", "")
    else:
        number_text = number_text.replace(",", ".")

    try:
        return int(float(number_text) * multiplier)
    except ValueError:
        digits_only = re.sub(r"\D", "", number_raw)
        return int(digits_only) if digits_only else 0


def _counter_multiplier(suffix: str) -> int:
    normalized = suffix.lower().strip(". ")
    if re.match(r"^(k|тыс|tys|thousand|тысяч)", normalized):
        return 1_000
    if re.match(r"^(m|млн|million)", normalized):
        return 1_000_000
    if re.match(r"^(b|млрд|billion)", normalized):
        return 1_000_000_000
    return 1


def parse_subscriber_count_text(value: Any) -> int | None:
    """
    Parse a YouTube subscriber counter label into an integer.

    Returns ``None`` when the count is hidden or cannot be parsed reliably.
    Returns ``0`` for explicit zero-subscriber labels like ``No subscribers``.
    """
    text = _text_from_node(value)
    if not text:
        return None

    normalized = (
        text.replace("\xa0", " ")
        .replace("\u202f", " ")
        .replace("−", "-")
        .strip()
        .lower()
    )
    if not normalized:
        return None

    if any(needle in normalized for needle in _HIDDEN_SUBSCRIBER_NEEDLES):
        return None

    parsed = parse_subscriber_count(text)
    if parsed > 0:
        return parsed
    if any(needle in normalized for needle in _ZERO_SUBSCRIBER_NEEDLES):
        return 0

    return None


def _youtube_page_headers(text: str = "") -> dict[str, str]:
    hl, _gl = _innertube_locale_for_text(text)
    accept_language = (
        "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
        if hl == INNERTUBE_HL_RU
        else "en-US,en;q=0.9"
    )
    return {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": accept_language,
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
    }


def _contains_cyrillic(text: str) -> bool:
    return bool(_CYRILLIC_RE.search(text))


def _innertube_locale_for_text(text: str = "") -> tuple[str, str]:
    if _contains_cyrillic(text):
        return INNERTUBE_HL_RU, INNERTUBE_GL_RU
    return INNERTUBE_HL, INNERTUBE_GL


def _extract_innertube_locale_text(payload: dict[str, Any]) -> str:
    for key in ("query", "input", "q", "url"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _build_youtube_search_page_url(query: str) -> str:
    hl, gl = _innertube_locale_for_text(query)
    return (
        f"{YOUTUBE_SEARCH_RESULTS_URL}?search_query={quote_plus(query)}"
        f"&hl={hl}&gl={gl}&persist_hl=1"
    )


def extract_yt_initial_data(html: str) -> dict[str, Any] | None:
    """Extract the ``ytInitialData`` JSON blob embedded in a YouTube HTML page."""
    markers = (
        "var ytInitialData = ",
        'window["ytInitialData"] = ',
        "ytInitialData = ",
    )
    for marker in markers:
        start = html.find(marker)
        if start == -1:
            continue
        json_start = start + len(marker)
        try:
            data, _ = json.JSONDecoder().raw_decode(html, json_start)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data

    regex_match = re.search(
        r'(?:var\s+ytInitialData\s*=|window\["ytInitialData"\]\s*=|ytInitialData\s*=)\s*(\{)',
        html,
    )
    if regex_match:
        try:
            data, _ = json.JSONDecoder().raw_decode(html, regex_match.start(1))
        except json.JSONDecodeError:
            return None
        if isinstance(data, dict):
            return data
    return None


def _iter_subscriber_count_text_nodes(node: Any) -> Any:
    if isinstance(node, dict):
        if "subscriberCountText" in node:
            yield node["subscriberCountText"]
        for value in node.values():
            yield from _iter_subscriber_count_text_nodes(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_subscriber_count_text_nodes(item)


def parse_subscribers_from_yt_initial_data(data: dict[str, Any]) -> int | None:
    """
    Read subscriber count from a channel home ``ytInitialData`` payload.

    Looks at header renderers only (no About tab).
    """
    header = (
        _find_renderer(data, "c4TabbedHeaderRenderer")
        or _find_renderer(data, "pageHeaderViewModel")
        or _find_renderer(data, "pageHeaderRenderer")
        or _find_renderer(data, "interactiveTabbedHeaderRenderer")
        or {}
    )

    for field in ("subscriberCountText", "subscriberCount"):
        if field in header:
            parsed = parse_subscriber_count_text(header.get(field))
            if parsed is not None:
                return parsed

    for renderer_name in (
        "c4TabbedHeaderRenderer",
        "pageHeaderRenderer",
        "interactiveTabbedHeaderRenderer",
    ):
        for renderer in _iter_renderers(data, renderer_name):
            parsed = parse_subscriber_count_text(renderer.get("subscriberCountText"))
            if parsed is not None:
                return parsed

    for renderer in _iter_renderers(data, "pageHeaderViewModel"):
        metadata = renderer.get("metadata", {})
        if not isinstance(metadata, dict):
            continue
        content_meta = metadata.get("contentMetadataViewModel", {})
        if not isinstance(content_meta, dict):
            continue
        rows = content_meta.get("metadataRows", [])
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            parts = row.get("metadataParts", [])
            if not isinstance(parts, list):
                continue
            for part in parts:
                if not isinstance(part, dict):
                    continue
                text = _text_from_node(part.get("text"))
                if not text:
                    label = part.get("accessibilityLabel")
                    if isinstance(label, str):
                        text = label.strip()
                lowered = text.lower()
                if any(
                    needle in lowered
                    for needle in ("subscriber", "subscribers", "подписчик")
                ):
                    parsed = parse_subscriber_count_text(text)
                    if parsed is not None and parsed > 0:
                        return parsed

    for renderer in _iter_renderers(data, "channelMetadataRenderer"):
        parsed = parse_subscriber_count_text(renderer.get("subscriberCountText"))
        if parsed is not None and parsed > 0:
            return parsed

    for node in _iter_subscriber_count_text_nodes(data):
        parsed = parse_subscriber_count_text(node)
        if parsed is not None and parsed > 0:
            return parsed

    return None


_SUBSCRIBER_CONTENT_HTML_RE = re.compile(
    r'"content"\s*:\s*"((?:\\.|[^"\\])*(?:subscribers|подписчик)(?:\\.|[^"\\])*)"',
    re.IGNORECASE,
)


def parse_subscribers_from_channel_html(html: str) -> int | None:
    """Parse subscriber count from channel home HTML via ytInitialData and RegEx fallback."""
    initial_data = extract_yt_initial_data(html)
    if initial_data is not None:
        parsed = parse_subscribers_from_yt_initial_data(initial_data)
        if parsed is not None and parsed > 0:
            return parsed

    for match in _SUBSCRIBER_CONTENT_HTML_RE.finditer(html):
        raw_value = match.group(1)
        try:
            text = json.loads(f'"{raw_value}"')
        except json.JSONDecodeError:
            text = raw_value.replace("\\u2068", "").replace("\\u2069", "").replace("\\u200e", "")
        parsed = parse_subscriber_count_text(text)
        if parsed is not None and parsed > 0:
            return parsed

    return None


def _channel_homepage_urls(channel_id: str, channel_name: str = "") -> list[str]:
    urls: list[str] = []
    normalized_id = channel_id.strip()
    if normalized_id:
        urls.append(CHANNEL_HOME_URL.format(channel_id=normalized_id))

    handle = channel_name.strip()
    if handle.startswith("@"):
        urls.append(f"https://www.youtube.com/{handle}")
    elif handle and not handle.startswith("UC"):
        urls.append(f"https://www.youtube.com/@{handle.lstrip('@')}")

    return list(dict.fromkeys(urls))


async def fetch_channel_subscribers_from_homepage(
    channel_id: str,
    *,
    channel_name: str = "",
) -> int | None:
    """Light GET of the channel home page; parse subscribers from ``ytInitialData``."""
    if not channel_id.strip() and not channel_name.strip():
        return None

    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            headers=_youtube_page_headers(channel_name or channel_id),
            follow_redirects=True,
        ) as client:
            for url in _channel_homepage_urls(channel_id, channel_name):
                try:
                    response = await client.get(url)
                except httpx.HTTPError:
                    continue
                if response.status_code != 200:
                    continue
                parsed = parse_subscribers_from_channel_html(response.text)
                if parsed is not None and parsed > 0:
                    return parsed
    except httpx.HTTPError:
        return None

    return None


def _parse_search_videos(
    payload: dict[str, Any],
) -> tuple[list[VideoSearchModel], int, dict[str, int]]:
    """
    Parse regular videos and Shorts from an InnerTube search response.

    Uses a deep walk of the JSON tree (no hard-coded ``contents[0]`` paths) to
    collect every supported renderer type regardless of nesting inside
    ``itemSectionRenderer``, ``shelfRenderer``, ``appendContinuationItemsAction``,
    etc.

    Returns ``(videos, parse_skipped, renderer_counts)``.
    """
    renderer_counts = _count_search_renderer_nodes(payload)
    videos: list[VideoSearchModel] = []
    seen: set[str] = set()
    parse_skipped = 0

    def _add(parsed: VideoSearchModel | None) -> None:
        if parsed is None or parsed.video_id in seen:
            return
        seen.add(parsed.video_id)
        videos.append(parsed)

    def _try_add(
        renderer: dict[str, Any],
        parser,
    ) -> None:
        nonlocal parse_skipped
        try:
            _add(parser(renderer))
        except Exception as exc:
            parse_skipped += 1
            logger.debug(
                "Пропуск видео: ошибка парсинга %s — %s",
                parser.__name__,
                exc,
            )

    for renderer in _iter_nodes_by_key(payload, "videoRenderer"):
        if isinstance(renderer, dict):
            _try_add(renderer, _parse_video_renderer)
    for renderer in _iter_nodes_by_key(payload, "compactVideoRenderer"):
        if isinstance(renderer, dict):
            _try_add(renderer, _parse_video_renderer)
    for renderer in _iter_nodes_by_key(payload, "gridVideoRenderer"):
        if isinstance(renderer, dict):
            _try_add(renderer, _parse_video_renderer)
    for renderer in _iter_nodes_by_key(payload, "lockupViewModel"):
        if isinstance(renderer, dict):
            _try_add(renderer, _parse_search_lockup_view_model)
    for renderer in _iter_nodes_by_key(payload, "reelItemRenderer"):
        if isinstance(renderer, dict):
            _try_add(renderer, _parse_reel_item_renderer)
    for renderer in _iter_nodes_by_key(payload, "shortVideoRenderer"):
        if isinstance(renderer, dict):
            _try_add(renderer, _parse_short_video_renderer)
    for renderer in _iter_nodes_by_key(payload, "shortsLockupViewModel"):
        if isinstance(renderer, dict):
            _try_add(renderer, _parse_shorts_lockup_view_model)
    for renderer in _iter_nodes_by_key(payload, "playlistVideoRenderer"):
        if isinstance(renderer, dict):
            _try_add(renderer, _parse_playlist_video_search_renderer)
    for renderer in _iter_nodes_by_key(payload, "richItemRenderer"):
        if isinstance(renderer, dict):
            _try_add(renderer, _parse_rich_item_search_renderer)

    return videos, parse_skipped, renderer_counts


def _persist_innertube_debug_response(payload: dict[str, Any]) -> None:
    """Temporary debug dump: overwrite raw InnerTube JSON on every request."""
    try:
        DEBUG_YT_RESPONSE_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.debug("InnerTube debug response saved to %s", DEBUG_YT_RESPONSE_PATH)
    except OSError as exc:
        logger.warning("Не удалось сохранить %s: %s", DEBUG_YT_RESPONSE_PATH, exc)


def _warn_innertube_response_blockers(payload: dict[str, Any], *, endpoint: str) -> None:
    """Log critical warnings when YouTube returns captcha/consent/error stubs."""
    serialized = json.dumps(payload, ensure_ascii=False).lower()

    if re.search(r"\bcaptcha\b", serialized) or "botguard" in serialized:
        logger.critical(
            "InnerTube ответ (%s) содержит captcha/botguard — возможна заглушка YouTube. "
            "Проверьте debug_yt_response.json",
            endpoint,
        )

    if re.search(r"\bconsent\b", serialized) or "consent.youtube" in serialized:
        logger.critical(
            "InnerTube ответ (%s) содержит consent — возможна заглушка YouTube. "
            "Проверьте debug_yt_response.json",
            endpoint,
        )

    if (
        re.search(r'"error"\s*:\s*\{', serialized)
        or re.search(r'"errorcode"\s*:', serialized)
        or re.search(r'"status"\s*:\s*"error"', serialized)
    ):
        logger.critical(
            "InnerTube ответ (%s) содержит error — возможна заглушка YouTube. "
            "Проверьте debug_yt_response.json",
            endpoint,
        )


def _count_search_renderer_nodes(payload: dict[str, Any]) -> dict[str, int]:
    counts = {
        key: sum(
            1
            for node in _iter_nodes_by_key(payload, key)
            if isinstance(node, dict)
        )
        for key in SEARCH_VIDEO_RENDERER_KEYS
    }
    counts["continuationItemRenderer"] = sum(
        1
        for node in _iter_nodes_by_key(payload, "continuationItemRenderer")
        if isinstance(node, dict)
    )
    return counts


def _log_search_page_renderer_counts(
    page_number: int,
    renderer_counts: dict[str, int],
    *,
    parsed_count: int,
    parse_skipped: int,
) -> None:
    logger.info(
        "Страница %s: найдено videoRenderer=%s, lockupViewModel=%s, "
        "richItemRenderer=%s, reelItemRenderer=%s, compactVideoRenderer=%s, "
        "playlistVideoRenderer=%s, continuationItemRenderer=%s; "
        "распознано видео: %s",
        page_number,
        renderer_counts.get("videoRenderer", 0),
        renderer_counts.get("lockupViewModel", 0),
        renderer_counts.get("richItemRenderer", 0),
        renderer_counts.get("reelItemRenderer", 0),
        renderer_counts.get("compactVideoRenderer", 0),
        renderer_counts.get("playlistVideoRenderer", 0),
        renderer_counts.get("continuationItemRenderer", 0),
        parsed_count,
    )
    if parse_skipped:
        logger.info(
            "Страница %s: пропущено видео из-за ошибок парсинга: %s",
            page_number,
            parse_skipped,
        )


def _parse_playlist_video_search_renderer(renderer: dict[str, Any]) -> VideoSearchModel | None:
    """Parse a ``playlistVideoRenderer`` entry from search results."""
    video_id = renderer.get("videoId")
    title = _text_from_node(renderer.get("title"))
    if not video_id or not title:
        return None

    channel_id, channel_title = _extract_channel_metadata_from_renderer(renderer)
    return _apply_live_broadcast_classification(
        VideoSearchModel(
            video_id=video_id,
            channel_id=channel_id,
            channel_title=channel_title,
            title=title,
            views_count=parse_compact_int(
                renderer.get("shortViewCountText") or renderer.get("viewCountText"),
            ),
            published_text=_extract_published_text_from_renderer(renderer),
            duration_text=_text_from_node(renderer.get("lengthText")),
            thumbnail_url=_extract_largest_thumbnail_url(renderer.get("thumbnail")),
            channel_avatar_url=_extract_video_channel_avatar_url(renderer),
            subscribers_count=_extract_subscribers_from_renderer(renderer),
            is_short=False,
            content_renderer="playlistVideoRenderer",
        ),
        renderer,
    )


def _parse_rich_item_search_renderer(rich_item: dict[str, Any]) -> VideoSearchModel | None:
    """Unwrap ``richItemRenderer.content`` and parse the nested video card."""
    content = rich_item.get("content")
    if not isinstance(content, dict):
        return None

    nested_parsers: tuple[tuple[str, Any], ...] = (
        ("videoRenderer", _parse_video_renderer),
        ("lockupViewModel", _parse_search_lockup_view_model),
        ("compactVideoRenderer", _parse_video_renderer),
        ("gridVideoRenderer", _parse_video_renderer),
        ("reelItemRenderer", _parse_reel_item_renderer),
        ("shortVideoRenderer", _parse_short_video_renderer),
        ("shortsLockupViewModel", _parse_shorts_lockup_view_model),
        ("playlistVideoRenderer", _parse_playlist_video_search_renderer),
    )
    for key, parser in nested_parsers:
        nested = content.get(key)
        if isinstance(nested, dict):
            parsed = parser(nested)
            if parsed is not None:
                return parsed.model_copy(update={"content_renderer": "richItemRenderer"})
    return None


_RELATIVE_TIME_HINTS = (
    "ago",
    "назад",
    "minute",
    "hour",
    "day",
    "week",
    "month",
    "year",
    "минут",
    "час",
    "день",
    "недел",
    "месяц",
    "год",
    "лет",
    "секунд",
    "just now",
    "только что",
)


def _looks_like_relative_time(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False
    return any(hint in lowered for hint in _RELATIVE_TIME_HINTS)


def _extract_published_text_from_renderer(renderer: dict[str, Any]) -> str:
    """Extract relative publish date from search card renderers, including Shorts."""
    for field in (
        "publishedTimeText",
        "publishedTime",
        "dateText",
        "uploadDateText",
    ):
        text = _text_from_node(renderer.get(field))
        if _looks_like_relative_time(text):
            return text

    accessibility_text = _text_from_node(renderer.get("accessibilityText"))
    if _looks_like_relative_time(accessibility_text):
        return accessibility_text

    overlay = renderer.get("overlayMetadata")
    if isinstance(overlay, dict):
        for field in ("primaryText", "secondaryText"):
            node = overlay.get(field)
            if isinstance(node, dict):
                text = _text_from_node(node.get("content") or node)
                if _looks_like_relative_time(text):
                    return text

    metadata_root = renderer.get("metadata", {})
    if isinstance(metadata_root, dict):
        metadata_root = metadata_root.get("lockupMetadataViewModel", metadata_root)
    if isinstance(metadata_root, dict):
        content_metadata = metadata_root.get("metadata", {})
        if isinstance(content_metadata, dict):
            content_metadata = content_metadata.get(
                "contentMetadataViewModel",
                content_metadata,
            )
        if isinstance(content_metadata, dict):
            for row in content_metadata.get("metadataRows") or []:
                if not isinstance(row, dict):
                    continue
                for part in row.get("metadataParts") or []:
                    if not isinstance(part, dict):
                        continue
                    text = _text_from_node(part.get("text", {}).get("content") or part.get("text"))
                    if _looks_like_relative_time(text):
                        return text

    for text in _iter_texts(renderer):
        if _looks_like_relative_time(text):
            return text

    return ""


def _parse_video_renderer(renderer: dict[str, Any]) -> VideoSearchModel | None:
    video_id = renderer.get("videoId")
    title = _text_from_node(renderer.get("title"))
    channel_id, channel_title = _extract_channel_metadata_from_renderer(renderer)
    if not video_id or not title:
        return None

    channel_title = channel_title or _text_from_node(
        renderer.get("ownerText")
        or renderer.get("longBylineText")
        or renderer.get("shortBylineText"),
    )
    duration_text = _text_from_node(renderer.get("lengthText"))
    is_short = _video_renderer_is_short(renderer) or "/shorts/" in _renderer_navigation_url(renderer)
    if is_short and not duration_text:
        duration_text = "0:00"

    return _apply_live_broadcast_classification(
        VideoSearchModel(
            video_id=video_id,
            channel_id=channel_id,
            channel_title=channel_title,
            title=title,
            views_count=parse_compact_int(renderer.get("viewCountText")),
            published_text=_extract_published_text_from_renderer(renderer),
            duration_text=duration_text,
            thumbnail_url=_extract_largest_thumbnail_url(renderer.get("thumbnail")),
            channel_avatar_url=_extract_video_channel_avatar_url(renderer),
            subscribers_count=_extract_subscribers_from_renderer(renderer),
            is_short=is_short,
            content_renderer="videoRenderer",
        ),
        renderer,
    )


def _video_renderer_is_short(renderer: dict[str, Any]) -> bool:
    """Detect a Short delivered inside a standard ``videoRenderer``."""
    navigation = renderer.get("navigationEndpoint")
    if isinstance(navigation, dict) and "reelWatchEndpoint" in navigation:
        return True

    for overlay in renderer.get("thumbnailOverlays") or []:
        if not isinstance(overlay, dict):
            continue
        style = (
            overlay.get("thumbnailOverlayTimeStatusRenderer", {}).get("style")
            if isinstance(overlay.get("thumbnailOverlayTimeStatusRenderer"), dict)
            else None
        )
        if isinstance(style, str) and style.upper() == "SHORTS":
            return True
    return False


def _renderer_navigation_url(renderer: dict[str, Any]) -> str:
    navigation = renderer.get("navigationEndpoint")
    if not isinstance(navigation, dict):
        return ""
    command_metadata = navigation.get("commandMetadata")
    if not isinstance(command_metadata, dict):
        return ""
    web_metadata = command_metadata.get("webCommandMetadata")
    if not isinstance(web_metadata, dict):
        return ""
    url = web_metadata.get("url")
    return url if isinstance(url, str) else ""


_LIVE_BADGE_LABELS_ACTIVE = frozenset(
    {
        "live",
        "live now",
        "в эфире",
        "на эфире",
    },
)
_LIVE_BADGE_LABELS_UPCOMING = frozenset(
    {
        "upcoming",
        "premiere",
        "premieres",
        "ожидается",
        "премьера",
    },
)
_LIVE_BADGE_LABELS_COMPLETED_PREFIXES = (
    "streamed live",
    "was live",
    "запись трансляции",
    "трансляция записана",
    "запись эфира",
)


def _normalize_badge_label(label: str) -> str:
    return " ".join(label.strip().lower().split())


def _badge_label_indicates_completed(label: str) -> bool:
    normalized = _normalize_badge_label(label)
    return any(normalized.startswith(prefix) for prefix in _LIVE_BADGE_LABELS_COMPLETED_PREFIXES)


def _classify_from_metadata_badge(metadata_badge: dict[str, Any]) -> LiveBroadcastStatus | None:
    label = _normalize_badge_label(_text_from_node(metadata_badge.get("label")))
    if not label:
        return None
    style = str(metadata_badge.get("style", "")).upper()
    if label in _LIVE_BADGE_LABELS_UPCOMING or "UPCOMING" in style or "PREMIERE" in style:
        return LiveBroadcastStatus.UPCOMING
    if _badge_label_indicates_completed(label):
        return LiveBroadcastStatus.COMPLETED
    if label in _LIVE_BADGE_LABELS_ACTIVE or "LIVE_NOW" in style or style == "LIVE":
        return LiveBroadcastStatus.LIVE
    return None


def _classify_from_time_status_overlay(time_status: dict[str, Any]) -> LiveBroadcastStatus | None:
    style = str(time_status.get("style", "")).upper()
    if style == "LIVE":
        return LiveBroadcastStatus.LIVE
    label = _normalize_badge_label(_text_from_node(time_status.get("text")))
    if label in _LIVE_BADGE_LABELS_ACTIVE:
        return LiveBroadcastStatus.LIVE
    return None


def _iter_metadata_badges(renderer: dict[str, Any]) -> list[dict[str, Any]]:
    badges: list[dict[str, Any]] = []
    for badge in renderer.get("badges") or []:
        if isinstance(badge, dict) and isinstance(badge.get("metadataBadgeRenderer"), dict):
            badges.append(badge["metadataBadgeRenderer"])

    metadata_root = renderer.get("metadata", {})
    if isinstance(metadata_root, dict):
        metadata_root = metadata_root.get("lockupMetadataViewModel", metadata_root)
    if isinstance(metadata_root, dict):
        for badge in metadata_root.get("badges") or []:
            if isinstance(badge, dict) and isinstance(badge.get("metadataBadgeRenderer"), dict):
                badges.append(badge["metadataBadgeRenderer"])
    return badges


def _renderer_exposes_live_metadata(renderer: dict[str, Any]) -> bool:
    if renderer.get("upcomingEventData"):
        return True
    if renderer.get("thumbnailOverlays") is not None:
        return True
    if renderer.get("badges"):
        return True
    metadata_root = renderer.get("metadata", {})
    if isinstance(metadata_root, dict):
        lockup_meta = metadata_root.get("lockupMetadataViewModel", metadata_root)
        if isinstance(lockup_meta, dict) and lockup_meta.get("badges"):
            return True
    return False


def classify_live_broadcast_from_renderer(renderer: dict[str, Any]) -> LiveBroadcastStatus:
    """
    Classify stream state from structured InnerTube fields only.

    Sufficient signals:
    - UPCOMING: ``upcomingEventData`` or premiere/upcoming badge labels/styles.
    - LIVE: ``thumbnailOverlayTimeStatusRenderer.style == LIVE`` or live-now badge.
    - COMPLETED: badge labels such as ``Streamed live`` (metadataBadgeRenderer only).
    - NONE: inspected card with no stream signals (treat as regular VOD).
    - UNKNOWN: sparse renderer without live metadata slots (e.g. some playlist cards).
    """
    if isinstance(renderer.get("upcomingEventData"), dict):
        return LiveBroadcastStatus.UPCOMING

    for overlay in renderer.get("thumbnailOverlays") or []:
        if not isinstance(overlay, dict):
            continue
        time_status = overlay.get("thumbnailOverlayTimeStatusRenderer")
        if isinstance(time_status, dict):
            found = _classify_from_time_status_overlay(time_status)
            if found is not None:
                return found

    for metadata_badge in _iter_metadata_badges(renderer):
        found = _classify_from_metadata_badge(metadata_badge)
        if found is not None:
            return found

    if not _renderer_exposes_live_metadata(renderer):
        return LiveBroadcastStatus.UNKNOWN
    return LiveBroadcastStatus.NONE


def _apply_live_broadcast_classification(
    video: VideoSearchModel,
    renderer: dict[str, Any],
) -> VideoSearchModel:
    status = classify_live_broadcast_from_renderer(renderer)
    is_active = status in (LiveBroadcastStatus.UPCOMING, LiveBroadcastStatus.LIVE)
    merged = video.model_dump()
    merged["live_broadcast_status"] = status
    merged["is_live"] = is_active
    return VideoSearchModel.model_validate(merged)


def video_is_stream_content(video: VideoSearchModel) -> bool:
    """True for upcoming, active, or completed broadcast recordings."""
    if video.live_broadcast_status in (
        LiveBroadcastStatus.UPCOMING,
        LiveBroadcastStatus.LIVE,
        LiveBroadcastStatus.COMPLETED,
    ):
        return True
    return bool(video.is_live)


def _parse_reel_item_renderer(renderer: dict[str, Any]) -> VideoSearchModel | None:
    """Parse a legacy Shorts item (``reelItemRenderer``)."""
    video_id = renderer.get("videoId")
    if not video_id:
        navigation = renderer.get("navigationEndpoint")
        if isinstance(navigation, dict):
            reel = navigation.get("reelWatchEndpoint")
            if isinstance(reel, dict) and isinstance(reel.get("videoId"), str):
                video_id = reel["videoId"]

    title = _text_from_node(renderer.get("headline") or renderer.get("title"))
    channel_id, channel_title = _extract_channel_metadata_from_renderer(renderer)
    if not video_id or not title:
        return None

    views_count = parse_compact_int(
        renderer.get("viewCountText") or renderer.get("accessibility"),
    )
    return VideoSearchModel(
        video_id=video_id,
        channel_id=channel_id,
        channel_title=channel_title,
        title=title,
        views_count=views_count,
        published_text=_extract_published_text_from_renderer(renderer),
        duration_text="0:00",
        thumbnail_url=_extract_largest_thumbnail_url(renderer.get("thumbnail")),
        channel_avatar_url=_extract_video_channel_avatar_url(renderer),
        subscribers_count=_extract_subscribers_from_renderer(renderer),
        is_short=True,
        is_live=False,
        content_renderer="reelItemRenderer",
    )


def _parse_short_video_renderer(renderer: dict[str, Any]) -> VideoSearchModel | None:
    """Parse Shorts delivered as ``shortVideoRenderer``."""
    video_id = renderer.get("videoId")
    title = _text_from_node(renderer.get("headline") or renderer.get("title"))
    channel_id, channel_title = _extract_channel_metadata_from_renderer(renderer)
    if not video_id or not title:
        return None

    return VideoSearchModel(
        video_id=video_id,
        channel_id=channel_id,
        channel_title=channel_title,
        title=title,
        views_count=parse_compact_int(renderer.get("viewCountText")),
        published_text=_extract_published_text_from_renderer(renderer),
        duration_text="0:00",
        thumbnail_url=_extract_largest_thumbnail_url(renderer.get("thumbnail")),
        channel_avatar_url=_extract_video_channel_avatar_url(renderer),
        subscribers_count=_extract_subscribers_from_renderer(renderer),
        is_short=True,
        is_live=False,
        content_renderer="shortVideoRenderer",
    )


def _parse_search_lockup_view_model(lockup: dict[str, Any]) -> VideoSearchModel | None:
    """Parse a search-result ``lockupViewModel`` (regular video or Short)."""
    video_id = lockup.get("contentId")
    if not isinstance(video_id, str) or not _VIDEO_ID_PATTERN.match(video_id):
        video_id = _extract_lockup_video_id(lockup)
    if not video_id:
        return None

    metadata_root = lockup.get("metadata", {})
    if isinstance(metadata_root, dict):
        metadata_root = metadata_root.get("lockupMetadataViewModel", metadata_root)

    title = ""
    views_text = ""
    published_text = ""
    if isinstance(metadata_root, dict):
        title = _text_from_node(
            metadata_root.get("title", {}).get("content")
            if isinstance(metadata_root.get("title"), dict)
            else metadata_root.get("title"),
        )
        content_metadata = metadata_root.get("metadata", {})
        if isinstance(content_metadata, dict):
            content_metadata = content_metadata.get(
                "contentMetadataViewModel",
                content_metadata,
            )
        if isinstance(content_metadata, dict):
            for row in content_metadata.get("metadataRows") or []:
                if not isinstance(row, dict):
                    continue
                for part in row.get("metadataParts") or []:
                    if not isinstance(part, dict):
                        continue
                    text = _text_from_node(part.get("text", {}).get("content") or part.get("text"))
                    if not text:
                        continue
                    lowered = text.lower()
                    if any(
                        token in lowered
                        for token in ("view", "просмотр", "watching", "зрител")
                    ):
                        views_text = text
                    elif any(
                        token in lowered
                        for token in (
                            "ago",
                            "назад",
                            "hour",
                            "day",
                            "week",
                            "month",
                            "year",
                            "minute",
                        )
                    ):
                        published_text = text

    if not title:
        title = _text_from_node(lockup.get("accessibilityText")) or "Untitled video"

    if not published_text:
        published_text = _extract_published_text_from_renderer(lockup)

    channel_id, channel_title = _extract_channel_metadata_from_renderer(lockup)
    is_short = _lockup_view_model_is_short(lockup)
    duration_text = _extract_lockup_duration_text(lockup)
    if is_short and not duration_text:
        duration_text = "0:00"

    thumbnail_url = ""
    content_image = lockup.get("contentImage")
    if isinstance(content_image, dict):
        thumbnail_view = content_image.get("thumbnailViewModel", {}).get("image", {})
        if isinstance(thumbnail_view, dict):
            thumbnail_url = _extract_largest_image_url_from_sources(thumbnail_view.get("sources"))
        if not thumbnail_url:
            thumbnail_url = _extract_largest_thumbnail_url(content_image)

    return _apply_live_broadcast_classification(
        VideoSearchModel(
            video_id=video_id,
            channel_id=channel_id,
            channel_title=channel_title,
            title=title,
            views_count=parse_compact_int(views_text),
            published_text=published_text,
            duration_text=duration_text,
            thumbnail_url=thumbnail_url or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            channel_avatar_url=_extract_video_channel_avatar_url(lockup),
            subscribers_count=_extract_subscribers_from_renderer(lockup),
            is_short=is_short,
            content_renderer="lockupViewModel",
        ),
        lockup,
    )


def _lockup_view_model_is_short(lockup: dict[str, Any]) -> bool:
    on_tap = lockup.get("onTap")
    if isinstance(on_tap, dict):
        endpoint = on_tap.get("innertubeCommand") or on_tap
        if isinstance(endpoint, dict) and "reelWatchEndpoint" in endpoint:
            return True

    entity_id = lockup.get("entityId")
    if isinstance(entity_id, str) and "shorts" in entity_id.lower():
        return True

    return "/shorts/" in _renderer_navigation_url(lockup)


def _parse_shorts_lockup_view_model(renderer: dict[str, Any]) -> VideoSearchModel | None:
    """Parse a current Shorts item (``shortsLockupViewModel``)."""
    video_id = _extract_lockup_video_id(renderer)
    if not video_id:
        return None

    overlay = renderer.get("overlayMetadata")
    title = ""
    views_text = ""
    if isinstance(overlay, dict):
        primary = overlay.get("primaryText")
        secondary = overlay.get("secondaryText")
        if isinstance(primary, dict):
            title = _text_from_node(primary.get("content") or primary)
        if isinstance(secondary, dict):
            views_text = _text_from_node(secondary.get("content") or secondary)

    if not title:
        title = _text_from_node(renderer.get("accessibilityText")) or "Short"

    channel_id, channel_title = _extract_channel_metadata_from_renderer(renderer)

    thumbnail = renderer.get("thumbnail")
    thumbnail_url = ""
    if isinstance(thumbnail, dict):
        thumbnail_url = _extract_largest_image_url_from_sources(thumbnail.get("sources"))
        if not thumbnail_url:
            thumbnail_url = _extract_largest_thumbnail_url(thumbnail)

    return VideoSearchModel(
        video_id=video_id,
        channel_id=channel_id,
        channel_title=channel_title,
        title=title,
        views_count=parse_compact_int(views_text),
        published_text=_extract_published_text_from_renderer(renderer),
        duration_text="0:00",
        thumbnail_url=thumbnail_url or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        channel_avatar_url=_extract_video_channel_avatar_url(renderer),
        subscribers_count=_extract_subscribers_from_renderer(renderer),
        is_short=True,
        is_live=False,
        content_renderer="shortsLockupViewModel",
    )


def _extract_subscribers_from_renderer(renderer: dict[str, Any]) -> int:
    """Parse subscriber count from search card metadata when YouTube exposes it."""
    for text in _iter_texts(renderer):
        lowered = text.lower()
        if any(
            needle in lowered
            for needle in ("subscriber", "subscribers", "подписчик", "подписчиков", "подписчика")
        ):
            parsed = parse_subscriber_count(text)
            if parsed > 0:
                return parsed
    return 0


def _extract_lockup_video_id(renderer: dict[str, Any]) -> str:
    on_tap = renderer.get("onTap")
    if isinstance(on_tap, dict):
        endpoint = on_tap.get("innertubeCommand") or on_tap
        if isinstance(endpoint, dict):
            reel = endpoint.get("reelWatchEndpoint")
            if isinstance(reel, dict) and isinstance(reel.get("videoId"), str):
                return reel["videoId"]
            watch = endpoint.get("watchEndpoint")
            if isinstance(watch, dict) and isinstance(watch.get("videoId"), str):
                return watch["videoId"]

    entity_id = renderer.get("entityId")
    if isinstance(entity_id, str) and entity_id:
        match = re.search(r"([0-9A-Za-z_-]{11})$", entity_id)
        if match:
            return match.group(1)
    return ""


def _extract_largest_thumbnail_url(node: Any) -> str:
    """Return the widest thumbnail URL from an InnerTube thumbnails object."""
    if not isinstance(node, dict):
        return ""

    thumbnails = node.get("thumbnails")
    return _extract_largest_image_url_from_sources(thumbnails)


def _extract_largest_image_url_from_sources(sources: Any) -> str:
    if not isinstance(sources, list):
        return ""

    best_url = ""
    best_width = -1
    for source in sources:
        if not isinstance(source, dict):
            continue
        url = source.get("url")
        if not isinstance(url, str) or not url.strip():
            continue
        width = source.get("width")
        numeric_width = width if isinstance(width, int) else 0
        if numeric_width >= best_width:
            best_width = numeric_width
            best_url = url.strip()
    return best_url


def _extract_video_channel_avatar_url(renderer: dict[str, Any]) -> str:
    avatar = renderer.get("avatar")
    if isinstance(avatar, dict):
        sources = (
            avatar.get("decoratedAvatarViewModel", {})
            .get("avatar", {})
            .get("avatarViewModel", {})
            .get("image", {})
            .get("sources")
        )
        url = _extract_largest_image_url_from_sources(sources)
        if url:
            return url

    for item in renderer.get("channelThumbnailSupportedRenderers") or []:
        if not isinstance(item, dict):
            continue
        for nested in item.values():
            if isinstance(nested, dict):
                url = _extract_largest_thumbnail_url(nested.get("thumbnail", nested))
                if url:
                    return url
    return ""


def _extract_channel_avatar_url(header: dict[str, Any]) -> str:
    image = header.get("image")
    if isinstance(image, dict):
        sources = (
            image.get("decoratedAvatarViewModel", {})
            .get("avatar", {})
            .get("avatarViewModel", {})
            .get("image", {})
            .get("sources")
        )
        url = _extract_largest_image_url_from_sources(sources)
        if url:
            return url

        for key in ("banner", "content", "avatar"):
            nested = image.get(key)
            if isinstance(nested, dict):
                url = _extract_largest_thumbnail_url(nested)
                if url:
                    return url

    avatar = header.get("avatar")
    if isinstance(avatar, dict):
        for thumbnails_key in ("thumbnails", "sources"):
            url = _extract_largest_image_url_from_sources(avatar.get(thumbnails_key))
            if url:
                return url

    return ""


def _extract_channel_id(renderer: dict[str, Any]) -> str:
    """Extract channel id from standard text runs (``ownerText``, bylines)."""
    for field_name in ("ownerText", "longBylineText", "shortBylineText"):
        runs = (renderer.get(field_name) or {}).get("runs") or []
        for run in runs:
            browse_id = (
                run.get("navigationEndpoint", {})
                .get("browseEndpoint", {})
                .get("browseId")
            )
            if isinstance(browse_id, str) and _is_channel_id(browse_id):
                return browse_id

    navigation = renderer.get("navigationEndpoint")
    if isinstance(navigation, dict):
        browse_id = navigation.get("browseEndpoint", {}).get("browseId")
        if isinstance(browse_id, str) and _is_channel_id(browse_id):
            return browse_id

    on_tap = renderer.get("onTap")
    if isinstance(on_tap, dict):
        command = on_tap.get("innertubeCommand") or on_tap
        browse_id = _extract_browse_id_from_node(command, max_depth=6)
        if browse_id:
            return browse_id

    return _extract_browse_id_from_node(renderer, max_depth=8)


def _extract_channel_metadata_from_renderer(renderer: dict[str, Any]) -> tuple[str, str]:
    """Extract channel id and title from any InnerTube search renderer (incl. Shorts)."""
    channel_id = _extract_channel_id(renderer)
    channel_title = _text_from_node(
        renderer.get("ownerText")
        or renderer.get("longBylineText")
        or renderer.get("shortBylineText")
        or renderer.get("channelTitle")
    )
    if not channel_title:
        channel_title = _extract_owner_channel_name_from_node(renderer, max_depth=8)
    return channel_id, channel_title


def _parse_player_channel_info(payload: dict[str, Any]) -> tuple[str, str]:
    """Parse channel metadata from an InnerTube ``/player`` response."""
    details = payload.get("videoDetails") or {}
    channel_id = details.get("channelId") if isinstance(details.get("channelId"), str) else ""
    channel_title = details.get("author") if isinstance(details.get("author"), str) else ""

    microformat = payload.get("microformat", {}).get("playerMicroformatRenderer", {})
    if isinstance(microformat, dict):
        if not channel_id:
            external_id = microformat.get("externalChannelId")
            if isinstance(external_id, str) and _is_channel_id(external_id):
                channel_id = external_id
        if not channel_title:
            owner_name = microformat.get("ownerChannelName")
            if isinstance(owner_name, str) and owner_name.strip():
                channel_title = owner_name.strip()

    return channel_id, channel_title


_CHANNEL_ID_PATTERN = re.compile(r"^UC[\w-]{22}$")


def _is_channel_id(value: str) -> bool:
    return bool(_CHANNEL_ID_PATTERN.match(value.strip()))


def _extract_browse_id_from_node(node: Any, *, max_depth: int = 10, depth: int = 0) -> str:
    if depth > max_depth:
        return ""

    if isinstance(node, dict):
        browse = node.get("browseEndpoint")
        if isinstance(browse, dict):
            browse_id = browse.get("browseId")
            if isinstance(browse_id, str) and _is_channel_id(browse_id):
                return browse_id

        for key in ("channelId", "externalChannelId", "browseId"):
            value = node.get(key)
            if isinstance(value, str) and _is_channel_id(value):
                return value

        for value in node.values():
            found = _extract_browse_id_from_node(value, max_depth=max_depth, depth=depth + 1)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _extract_browse_id_from_node(item, max_depth=max_depth, depth=depth + 1)
            if found:
                return found

    return ""


def _extract_owner_channel_name_from_node(
    node: Any,
    *,
    max_depth: int = 10,
    depth: int = 0,
) -> str:
    if depth > max_depth:
        return ""

    if isinstance(node, dict):
        for key in ("ownerChannelName", "author", "channelName"):
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        for value in node.values():
            found = _extract_owner_channel_name_from_node(
                value,
                max_depth=max_depth,
                depth=depth + 1,
            )
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _extract_owner_channel_name_from_node(
                item,
                max_depth=max_depth,
                depth=depth + 1,
            )
            if found:
                return found

    return ""


def _extract_continuation_token_from_node(node: Any) -> str | None:
    if not isinstance(node, dict):
        return None

    continuation_command = node.get("continuationCommand")
    if isinstance(continuation_command, dict):
        token = continuation_command.get("token")
        if isinstance(token, str) and token.strip():
            return token.strip()

    token = (
        node.get("continuationEndpoint", {})
        .get("continuationCommand", {})
        .get("token")
        if isinstance(node.get("continuationEndpoint"), dict)
        else None
    )
    if isinstance(token, str) and token.strip():
        return token.strip()

    continuation = node.get("continuation")
    if isinstance(continuation, str) and continuation.strip():
        return continuation.strip()

    return None


def _extract_continuation_token_from_item(item: Any) -> str | None:
    if not isinstance(item, dict):
        return None

    renderer = item.get("continuationItemRenderer")
    if isinstance(renderer, dict):
        token = _extract_continuation_token_from_node(renderer)
        if token:
            return token

    return _extract_continuation_token_from_node(item)


def _extract_search_continuation(payload: dict[str, Any]) -> str | None:
    """
    Find the next-page continuation token anywhere in an InnerTube search payload.

    YouTube may place the token inside ``continuationItemRenderer`` at the end of
    ``sectionListRenderer.contents`` or inside ``appendContinuationItemsAction`` on
    continuation pages. Intentionally avoid arbitrary ``continuationEndpoint``
    matches because topbar/service commands can contain non-search continuations.
    """
    for action in _iter_nodes_by_key(payload, "appendContinuationItemsAction"):
        if not isinstance(action, dict):
            continue
        continuation_items = action.get("continuationItems")
        if not isinstance(continuation_items, list):
            continue
        for item in continuation_items:
            token = _extract_continuation_token_from_item(item)
            if token:
                return token

    for renderer in _iter_nodes_by_key(payload, "continuationItemRenderer"):
        if not isinstance(renderer, dict):
            continue
        token = _extract_continuation_token_from_node(renderer)
        if token:
            return token

    return None


def _extract_about_panel_continuation(payload: dict[str, Any]) -> str | None:
    """Return continuation token for the channel About engagement panel."""
    for panel in _iter_renderers(payload, "engagementPanelSectionListRenderer"):
        token = _extract_search_continuation(panel)
        if token:
            return token
    return None


def _find_tab_params(payload: dict[str, Any], titles: tuple[str, ...]) -> str | None:
    """Find InnerTube browse ``params`` for a channel tab by localized title."""
    normalized_titles = {title.lower() for title in titles}
    for renderer in _iter_renderers(payload, "tabRenderer"):
        title = _text_from_node(renderer.get("title")).lower()
        if title not in normalized_titles:
            continue
        endpoint = renderer.get("endpoint", {}).get("browseEndpoint", {})
        params = endpoint.get("params")
        if isinstance(params, str) and params:
            return params

    for renderer in _iter_renderers(payload, "expandableTabRenderer"):
        title = _text_from_node(renderer.get("title")).lower()
        if title not in normalized_titles:
            continue
        endpoint = renderer.get("endpoint", {}).get("browseEndpoint", {})
        params = endpoint.get("params")
        if isinstance(params, str) and params:
            return params
    return None


def _extract_channel_title_from_browse(payload: dict[str, Any]) -> str:
    header = (
        _find_renderer(payload, "c4TabbedHeaderRenderer")
        or _find_renderer(payload, "pageHeaderViewModel")
        or _find_renderer(payload, "pageHeaderRenderer")
        or {}
    )
    title = _text_from_node(
        header.get("title")
        or header.get("pageTitle")
        or header.get("channelName"),
    )
    if title:
        return title

    texts = list(_iter_texts(header))
    return texts[0] if texts else ""


def _parse_channel_browse_videos(
    payload: dict[str, Any],
    *,
    channel_id: str,
) -> list[ChannelVideoBrowseModel]:
    """Parse uploads from a channel Videos tab browse payload."""
    videos: list[ChannelVideoBrowseModel] = []
    seen: set[str] = set()

    def _add(parsed: ChannelVideoBrowseModel | None) -> None:
        if parsed is None or parsed.video_id in seen:
            return
        seen.add(parsed.video_id)
        videos.append(parsed)

    for renderer in _iter_renderers(payload, "richItemRenderer"):
        content = renderer.get("content")
        if isinstance(content, dict):
            lockup = content.get("lockupViewModel")
            if isinstance(lockup, dict):
                _add(_parse_lockup_view_model_video(lockup))
            video_renderer = content.get("videoRenderer")
            if isinstance(video_renderer, dict):
                _add(_parse_channel_video_renderer(video_renderer, channel_id=channel_id))

    for renderer in _iter_renderers(payload, "gridVideoRenderer"):
        _add(_parse_channel_grid_video_renderer(renderer, channel_id=channel_id))

    for renderer in _iter_renderers(payload, "videoRenderer"):
        _add(_parse_channel_video_renderer(renderer, channel_id=channel_id))

    for renderer in _iter_renderers(payload, "playlistVideoRenderer"):
        _add(_parse_playlist_video_renderer(renderer, channel_id=channel_id))

    return videos


def _parse_lockup_view_model_video(lockup: dict[str, Any]) -> ChannelVideoBrowseModel | None:
    video_id = lockup.get("contentId")
    if not isinstance(video_id, str) or not _VIDEO_ID_PATTERN.match(video_id):
        video_id = _extract_lockup_video_id(lockup)
    if not video_id:
        return None

    metadata_root = lockup.get("metadata", {})
    if isinstance(metadata_root, dict):
        metadata_root = metadata_root.get("lockupMetadataViewModel", metadata_root)

    title = ""
    views_text = ""
    published_text = ""
    if isinstance(metadata_root, dict):
        title = _text_from_node(
            metadata_root.get("title", {}).get("content")
            if isinstance(metadata_root.get("title"), dict)
            else metadata_root.get("title"),
        )
        content_metadata = metadata_root.get("metadata", {})
        if isinstance(content_metadata, dict):
            content_metadata = content_metadata.get(
                "contentMetadataViewModel",
                content_metadata,
            )
        if isinstance(content_metadata, dict):
            for row in content_metadata.get("metadataRows") or []:
                if not isinstance(row, dict):
                    continue
                for part in row.get("metadataParts") or []:
                    if not isinstance(part, dict):
                        continue
                    text = _text_from_node(part.get("text", {}).get("content") or part.get("text"))
                    if not text:
                        continue
                    lowered = text.lower()
                    if any(token in lowered for token in ("view", "просмотр", "watching", "зрител")):
                        views_text = text
                    elif any(
                        token in lowered
                        for token in ("ago", "назад", "hour", "day", "week", "month", "year", "minute")
                    ):
                        published_text = text

    if not title:
        title = _text_from_node(lockup.get("accessibilityText")) or "Untitled video"

    thumbnail_url = ""
    content_image = lockup.get("contentImage")
    if isinstance(content_image, dict):
        thumbnail_view = content_image.get("thumbnailViewModel", {}).get("image", {})
        if isinstance(thumbnail_view, dict):
            thumbnail_url = _extract_largest_image_url_from_sources(thumbnail_view.get("sources"))
        if not thumbnail_url:
            thumbnail_url = _extract_largest_thumbnail_url(content_image)

    duration_text = _extract_lockup_duration_text(lockup)

    return ChannelVideoBrowseModel(
        video_id=video_id,
        title=title,
        url=f"https://www.youtube.com/watch?v={video_id}",
        thumbnail_url=thumbnail_url or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        views_count=parse_compact_int(views_text),
        published_text=published_text,
        duration_text=duration_text,
    )


def _extract_lockup_duration_text(lockup: dict[str, Any]) -> str:
    content_image = lockup.get("contentImage")
    if not isinstance(content_image, dict):
        return ""

    thumbnail_view = content_image.get("thumbnailViewModel")
    if not isinstance(thumbnail_view, dict):
        return ""

    for overlay in thumbnail_view.get("overlays") or []:
        if not isinstance(overlay, dict):
            continue
        badge_renderer = overlay.get("thumbnailBottomOverlayViewModel", {})
        if not isinstance(badge_renderer, dict):
            continue
        for badge in badge_renderer.get("badges") or []:
            if not isinstance(badge, dict):
                continue
            badge_model = badge.get("thumbnailBadgeViewModel", {})
            if isinstance(badge_model, dict):
                text = _text_from_node(badge_model.get("text"))
                if text and ":" in text:
                    return text
    return ""


def _parse_channel_video_renderer(
    renderer: dict[str, Any],
    *,
    channel_id: str,
) -> ChannelVideoBrowseModel | None:
    parsed = _parse_video_renderer(renderer)
    if parsed is None:
        return None
    return ChannelVideoBrowseModel(
        video_id=parsed.video_id,
        title=parsed.title,
        url=f"https://www.youtube.com/watch?v={parsed.video_id}",
        thumbnail_url=parsed.thumbnail_url or f"https://i.ytimg.com/vi/{parsed.video_id}/hqdefault.jpg",
        views_count=parsed.views_count,
        published_text=parsed.published_text,
        duration_text=parsed.duration_text,
    )


def _parse_channel_grid_video_renderer(
    renderer: dict[str, Any],
    *,
    channel_id: str,
) -> ChannelVideoBrowseModel | None:
    return _parse_channel_video_renderer(renderer, channel_id=channel_id)


def _parse_playlist_video_renderer(
    renderer: dict[str, Any],
    *,
    channel_id: str,
) -> ChannelVideoBrowseModel | None:
    video_id = renderer.get("videoId")
    title = _text_from_node(renderer.get("title"))
    if not video_id or not title:
        return None

    return ChannelVideoBrowseModel(
        video_id=video_id,
        title=title,
        url=f"https://www.youtube.com/watch?v={video_id}",
        thumbnail_url=_extract_largest_thumbnail_url(renderer.get("thumbnail"))
        or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        views_count=parse_compact_int(renderer.get("shortViewCountText") or renderer.get("viewCountText")),
        published_text=_extract_published_text_from_renderer(renderer),
        duration_text=_text_from_node(renderer.get("lengthText")),
    )


_VIDEO_ID_PATTERN = re.compile(r"^[\w-]{11}$")


def _build_innertube_context(text: str = "") -> dict[str, Any]:
    hl, gl = _innertube_locale_for_text(text)
    return {
        "client": {
            "clientName": "WEB",
            "clientVersion": "2.20240613.01.00",
            "hl": hl,
            "gl": gl,
        },
    }


def _build_innertube_suggestions_context(text: str = "") -> dict[str, Any]:
    """InnerTube context required by ``music/get_search_suggestions``."""
    hl, gl = _innertube_locale_for_text(text)
    return {
        "client": {
            "clientName": "WEB_REMIX",
            "clientVersion": "1.20240613.01.00",
            "hl": hl,
            "gl": gl,
        },
    }


def _parse_search_suggestions(payload: dict[str, Any]) -> list[str]:
    """Extract plain-text suggestions from InnerTube autocomplete response."""
    suggestions: list[str] = []
    seen: set[str] = set()

    for section in payload.get("contents", []):
        section_renderer = section.get("searchSuggestionsSectionRenderer")
        if not isinstance(section_renderer, dict):
            continue
        for item in section_renderer.get("contents", []):
            suggestion_renderer = item.get("searchSuggestionRenderer")
            if not isinstance(suggestion_renderer, dict):
                continue
            text = _extract_suggestion_text(suggestion_renderer)
            if not text or text in seen:
                continue
            seen.add(text)
            suggestions.append(text)

    if suggestions:
        return suggestions

    for suggestion_renderer in _iter_renderers(payload, "searchSuggestionRenderer"):
        text = _extract_suggestion_text(suggestion_renderer)
        if not text or text in seen:
            continue
        seen.add(text)
        suggestions.append(text)

    return suggestions


def _filter_related_suggestions(
    main_query: str,
    suggestions: list[str],
    *,
    max_suggestions: int = 7,
) -> list[str]:
    """Pick unique related suggestions, excluding the main query."""
    normalized_main = re.sub(r"\s+", " ", main_query.strip().lower())
    filtered: list[str] = []
    seen: set[str] = {normalized_main} if normalized_main else set()

    for suggestion in suggestions:
        cleaned = suggestion.strip()
        normalized = re.sub(r"\s+", " ", cleaned.lower())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        filtered.append(cleaned)
        if len(filtered) >= max_suggestions:
            break

    return filtered


def _extract_suggestion_text(renderer: dict[str, Any]) -> str:
    query = (
        renderer.get("navigationEndpoint", {})
        .get("searchEndpoint", {})
        .get("query")
    )
    if isinstance(query, str) and query.strip():
        return query.strip()
    return _text_from_node(renderer.get("suggestion")).strip()


def _parse_google_suggest_response(raw_text: str) -> list[str]:
    start = raw_text.find("[")
    end = raw_text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []

    try:
        payload = json.loads(raw_text[start : end + 1])
    except json.JSONDecodeError:
        return []

    suggestion_rows = payload[1] if len(payload) > 1 else []
    suggestions: list[str] = []
    for row in suggestion_rows:
        if not isinstance(row, list) or not row:
            continue
        text = row[0]
        if isinstance(text, str) and text.strip():
            suggestions.append(text.strip())
    return suggestions


def _merge_suggestion_lists(
    primary: list[str],
    secondary: list[str],
    *,
    limit: int,
) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()

    for suggestion in [*primary, *secondary]:
        if suggestion in seen:
            continue
        seen.add(suggestion)
        merged.append(suggestion)
        if len(merged) >= limit:
            break
    return merged


def _parse_channel_details(responses: list[dict[str, Any]]) -> ChannelDetailModel:
    header = (
        _find_renderer(responses[0], "c4TabbedHeaderRenderer")
        or _find_renderer(responses[0], "pageHeaderViewModel")
        or _find_renderer(responses[0], "pageHeaderRenderer")
        or {}
    )
    about_nodes = [
        renderer
        for response in responses
        for renderer_name in (
            "aboutChannelRenderer",
            "channelAboutFullMetadataRenderer",
            "metadataRowContainerRenderer",
            "aboutChannelViewModel",
        )
        for renderer in _iter_renderers(response, renderer_name)
    ]
    header_texts = list(_iter_texts(header))
    about_texts = [text for node in about_nodes for text in _iter_texts(node)]
    all_texts = header_texts + about_texts

    subscribers_count = _extract_subscribers_count(responses, header_texts, all_texts)
    total_videos = _first_counter(
        header_texts,
        ("videos", "video", "видео", "ролик", "роликов", "ролика"),
    ) or _first_counter(
        all_texts,
        ("videos", "video", "видео", "ролик", "роликов", "ролика"),
    )
    total_views = _first_counter(
        about_texts,
        ("views", "view", "просмотр", "просмотров", "просмотра"),
    ) or _extract_total_views_from_about(responses)

    joined_text = _extract_joined_date_text(responses, all_texts)
    channel_age_days = _channel_age_days(joined_text) if joined_text else None

    return ChannelDetailModel(
        subscribers_count=subscribers_count,
        total_videos=total_videos,
        total_views=total_views,
        channel_age_days=channel_age_days,
        is_verified=_has_badge(header, ("verified", "подтвержден")),
        is_artist=_has_badge(header, ("artist", "артист", "исполнитель")),
        channel_avatar_url=_extract_channel_avatar_url(header),
    )


def _extract_subscribers_count(
    responses: list[dict[str, Any]],
    header_texts: list[str],
    all_texts: list[str],
) -> int:
    for response in responses:
        for renderer in _iter_renderers(response, "aboutChannelViewModel"):
            for field in ("subscriberCountText", "subscriberCount"):
                text = _text_from_node(renderer.get(field))
                if text:
                    parsed = parse_subscriber_count(text)
                    if parsed:
                        return parsed

        for renderer in _iter_renderers(response, "pageHeaderViewModel"):
            metadata = renderer.get("metadata", {})
            if not isinstance(metadata, dict):
                continue
            content_meta = metadata.get("contentMetadataViewModel", {})
            if not isinstance(content_meta, dict):
                continue
            rows = content_meta.get("metadataRows", [])
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                parts = row.get("metadataParts", [])
                if not isinstance(parts, list):
                    continue
                for part in parts:
                    if not isinstance(part, dict):
                        continue
                    text = _text_from_node(part.get("text"))
                    lowered = text.lower()
                    if any(
                        needle in lowered
                        for needle in ("subscriber", "subscribers", "подписчик")
                    ):
                        value = parse_subscriber_count(text)
                        if value:
                            return value

    return _first_subscriber_count(
        header_texts,
        ("subscriber", "subscribers", "подписчик", "подписчиков", "подписчика"),
    ) or _first_subscriber_count(
        all_texts,
        ("subscriber", "subscribers", "подписчик", "подписчиков", "подписчика"),
    )


def _extract_total_views_from_about(responses: list[dict[str, Any]]) -> int:
    for response in responses:
        for renderer in _iter_renderers(response, "channelAboutFullMetadataRenderer"):
            text = _text_from_node(renderer.get("viewCountText"))
            value = parse_compact_int(text)
            if value:
                return value
    return 0


def _extract_joined_date_text(
    responses: list[dict[str, Any]],
    all_texts: list[str],
) -> str:
    joined_field_names = (
        "joinedDateText",
        "joinedDate",
        "onJoinedDate",
        "signUpDate",
    )
    joined_title_needles = (
        "joined",
        "присоедин",
        "регистрац",
        "создан",
        "date joined",
    )

    for response in responses:
        for renderer in _iter_renderers(response, "aboutChannelViewModel"):
            for field in joined_field_names:
                text = _text_from_node(renderer.get(field))
                if text:
                    return text

        for renderer_name in (
            "channelAboutFullMetadataRenderer",
            "aboutChannelRenderer",
            "sectionListRenderer",
        ):
            for renderer in _iter_renderers(response, renderer_name):
                for field in joined_field_names:
                    text = _text_from_node(renderer.get(field))
                    if text:
                        return text

        for renderer in _iter_renderers(response, "metadataRowContainerRenderer"):
            title = _text_from_node(renderer.get("title")).lower()
            if any(needle in title for needle in joined_title_needles):
                content = _text_from_node(renderer.get("contents"))
                if content:
                    return content

        for renderer_name in ("aboutChannelViewModel", "pageHeaderViewModel"):
            for renderer in _iter_renderers(response, renderer_name):
                metadata_rows = renderer.get("metadataRows")
                if not isinstance(metadata_rows, list):
                    nested = renderer.get("aboutChannelViewModel", {})
                    if isinstance(nested, dict):
                        metadata_rows = nested.get("metadataRows")
                if not isinstance(metadata_rows, list):
                    metadata = renderer.get("metadata", {})
                    if isinstance(metadata, dict):
                        content_meta = metadata.get("contentMetadataViewModel", {})
                        if isinstance(content_meta, dict):
                            metadata_rows = content_meta.get("metadataRows")
                if not isinstance(metadata_rows, list):
                    continue
                for row in metadata_rows:
                    if not isinstance(row, dict):
                        continue
                    parts = row.get("metadataParts", [])
                    if isinstance(parts, list):
                        part_text = " ".join(
                            _text_from_node(part.get("text"))
                            for part in parts
                            if isinstance(part, dict)
                        ).strip()
                        if part_text and any(
                            needle in part_text.lower() for needle in joined_title_needles
                        ):
                            return part_text
                    row_text = _text_from_node(row)
                    if row_text and any(
                        needle in row_text.lower() for needle in joined_title_needles
                    ):
                        return row_text

        microformat = _find_renderer(response, "microformatDataRenderer")
        if isinstance(microformat, dict):
            for field in joined_field_names:
                text = _text_from_node(microformat.get(field))
                if text:
                    return text

    for text in all_texts:
        lowered = text.lower()
        if any(needle in lowered for needle in joined_title_needles) and re.search(
            r"\d{4}",
            text,
        ):
            return text

    return _first_text_with_any(
        all_texts,
        ("joined", "дата регистрации", "зарегистрирован", "присоединился"),
    )


def _first_counter(texts: list[str], needles: tuple[str, ...]) -> int:
    for text in texts:
        lowered = text.lower()
        if any(needle in lowered for needle in needles):
            value = parse_compact_int(text)
            if value:
                return value
    return 0


def _first_subscriber_count(texts: list[str], needles: tuple[str, ...]) -> int:
    for text in texts:
        lowered = text.lower()
        if any(needle in lowered for needle in needles):
            value = parse_subscriber_count(text)
            if value:
                return value
    return 0


def _first_text_with_any(texts: list[str], needles: tuple[str, ...]) -> str:
    for text in texts:
        lowered = text.lower()
        if any(needle in lowered for needle in needles):
            return text
    return ""


def _has_badge(node: Any, needles: tuple[str, ...]) -> bool:
    for text in _iter_texts(node):
        lowered = text.lower()
        if any(needle in lowered for needle in needles):
            return True
    for value in _iter_values(node):
        if isinstance(value, str):
            lowered = value.lower()
            if any(needle in lowered for needle in needles):
                return True
    return False


def _find_about_tab_params(payload: dict[str, Any]) -> str | None:
    return _find_tab_params(payload, ("about", "о канале"))


def _find_renderer(node: Any, renderer_name: str) -> dict[str, Any] | None:
    if isinstance(node, dict):
        value = node.get(renderer_name)
        if isinstance(value, dict):
            return value
        for item in node.values():
            found = _find_renderer(item, renderer_name)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_renderer(item, renderer_name)
            if found is not None:
                return found
    return None


def _iter_nodes_by_key(node: Any, key: str) -> Any:
    """Yield every value stored under ``key`` at any nesting depth."""
    if isinstance(node, dict):
        if key in node:
            yield node[key]
        for value in node.values():
            yield from _iter_nodes_by_key(value, key)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_nodes_by_key(item, key)


def _iter_renderers(node: Any, renderer_name: str) -> Any:
    if isinstance(node, dict):
        value = node.get(renderer_name)
        if isinstance(value, dict):
            yield value
        for item in node.values():
            yield from _iter_renderers(item, renderer_name)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_renderers(item, renderer_name)


def _iter_values(node: Any) -> Any:
    if isinstance(node, dict):
        for value in node.values():
            yield value
            yield from _iter_values(value)
    elif isinstance(node, list):
        for value in node:
            yield value
            yield from _iter_values(value)


def _iter_texts(node: Any) -> Any:
    text = _text_from_node(node)
    if text:
        yield text
    if isinstance(node, dict):
        for value in node.values():
            yield from _iter_texts(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_texts(item)


def _text_from_node(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        content = value.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        simple_text = value.get("simpleText")
        if isinstance(simple_text, str):
            return simple_text.strip()
        runs = value.get("runs")
        if isinstance(runs, list):
            return "".join(_text_from_node(run.get("text", "")) for run in runs).strip()
        accessibility = value.get("accessibilityData")
        if isinstance(accessibility, dict):
            label = accessibility.get("label")
            if isinstance(label, str):
                return label.strip()
    return ""


def _channel_age_days(text: str) -> int:
    joined_at = _parse_joined_date(text)
    if joined_at is None:
        return 0
    return max((datetime.now(timezone.utc).date() - joined_at.date()).days, 0)


def _parse_joined_date(text: str) -> datetime | None:
    if not text:
        return None

    normalized = text.lower().replace("\xa0", " ").replace("\u202f", " ")
    normalized = re.sub(
        r"\b(joined|joined on|date joined|дата регистрации|зарегистрирован|присоединился)\b[:\s]*",
        "",
        normalized,
        flags=re.IGNORECASE,
    ).strip()
    normalized = re.sub(r"\s*г\.?\s*$", "", normalized).strip(" .,")

    date_formats = (
        "%b %d, %Y",
        "%B %d, %Y",
        "%d %b %Y",
        "%d %B %Y",
        "%d.%m.%Y",
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%d/%m/%Y",
    )
    for fmt in date_formats:
        try:
            return datetime.strptime(normalized.title(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    for fmt in date_formats:
        try:
            return datetime.strptime(normalized, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    match = re.search(r"(\d{1,2})\s+([a-zа-яё.]+)\s+(\d{4})", normalized)
    if match:
        day = int(match.group(1))
        month = _month_number(match.group(2).strip("."))
        year = int(match.group(3))
        if month:
            return datetime(year, month, day, tzinfo=timezone.utc)

    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", normalized)
    if match:
        return datetime(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            tzinfo=timezone.utc,
        )

    return None


def _month_number(value: str) -> int:
    months = {
        "jan": 1,
        "january": 1,
        "янв": 1,
        "января": 1,
        "feb": 2,
        "february": 2,
        "фев": 2,
        "февраля": 2,
        "mar": 3,
        "march": 3,
        "мар": 3,
        "марта": 3,
        "apr": 4,
        "april": 4,
        "апр": 4,
        "апреля": 4,
        "may": 5,
        "май": 5,
        "мая": 5,
        "jun": 6,
        "june": 6,
        "июн": 6,
        "июня": 6,
        "jul": 7,
        "july": 7,
        "июл": 7,
        "июля": 7,
        "aug": 8,
        "august": 8,
        "авг": 8,
        "августа": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "сен": 9,
        "сент": 9,
        "сентября": 9,
        "oct": 10,
        "october": 10,
        "окт": 10,
        "октября": 10,
        "nov": 11,
        "november": 11,
        "ноя": 11,
        "ноября": 11,
        "dec": 12,
        "december": 12,
        "дек": 12,
        "декабря": 12,
    }
    return months.get(value, 0)


def _format_rfc3339(value: datetime) -> str:
    if value.tzinfo is None:
        return value.isoformat() + "Z"
    return value.isoformat().replace("+00:00", "Z")


def _parse_rfc3339(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


async def get_enriched_search_results(
    query: str,
    max_results: int = 50,
    *,
    sort_by_upload_date: bool = False,
    save_to_db: bool = False,
) -> list[EnrichedVideoModel]:
    """Run InnerTube search and enrich each video with channel metadata."""
    client = _get_innertube_client()
    results = await client.get_enriched_search_results(
        query,
        max_results=max_results,
        sort_by_upload_date=sort_by_upload_date,
    )
    if save_to_db and results:
        from app.services.explosive_channels_service import ExplosiveChannelsService

        ExplosiveChannelsService.track_enriched_videos(results)
    return results


@dataclass(frozen=True, slots=True)
class RadarContentFormatFilters:
    exclude_streams: bool = False
    exclude_shorts: bool = False
    exclude_videos: bool = False


SHORT_RENDERER_TYPES = frozenset(
    {"reelItemRenderer", "shortVideoRenderer", "shortsLockupViewModel"},
)


def video_is_short_item(video: VideoSearchModel) -> bool:
    if video.is_short:
        return True
    if video.content_renderer in SHORT_RENDERER_TYPES:
        return True
    return False


def video_is_regular_item(video: VideoSearchModel) -> bool:
    if video_is_short_item(video):
        return False
    if video_is_stream_content(video):
        return False
    if video.live_broadcast_status == LiveBroadcastStatus.UNKNOWN:
        return False
    return True


def should_exclude_radar_video(
    video: VideoSearchModel,
    filters: RadarContentFormatFilters,
) -> bool:
    if filters.exclude_shorts and video_is_short_item(video):
        return True
    if filters.exclude_streams and video_is_stream_content(video):
        return True
    if filters.exclude_videos and video_is_regular_item(video):
        return True
    return False


def filter_radar_videos_by_format(
    videos: list[VideoSearchModel],
    filters: RadarContentFormatFilters,
) -> list[VideoSearchModel]:
    if not any((filters.exclude_streams, filters.exclude_shorts, filters.exclude_videos)):
        return videos
    return [
        video
        for video in videos
        if not should_exclude_radar_video(video, filters)
    ]


async def iter_radar_search_pages(
    query: str,
    *,
    sort_by_upload_date: bool = False,
    max_pages: int = MAX_SEARCH_PAGES,
    innertube_metrics: InnerTubeMetrics | None = None,
) -> AsyncIterator[SearchPageBatch]:
    """Paginated InnerTube search for radar with per-page channel metadata fill."""
    client = _get_innertube_client(innertube_metrics=innertube_metrics)
    async for page in client.iter_search_pages(
        query,
        sort_by_upload_date=sort_by_upload_date,
        max_pages=max_pages,
    ):
        if not page.videos and not page.renderer_counts:
            continue
        filled_videos = (
            await client._fill_missing_channel_metadata(page.videos)
            if page.videos
            else []
        )
        yield SearchPageBatch(
            videos=filled_videos,
            renderer_counts=page.renderer_counts,
            parse_skipped=page.parse_skipped,
        )


async def get_radar_search_results(
    query: str,
    max_results: int = 50,
    *,
    max_pages: int | None = None,
    sort_by_upload_date: bool = False,
) -> list[VideoSearchModel]:
    """InnerTube search for radar: video shelf only, no bulk channel enrichment."""
    client = _get_innertube_client()
    videos = await client.search(
        query,
        max_results=max_results,
        max_pages=max_pages,
        sort_by_upload_date=sort_by_upload_date,
    )
    if not videos:
        return []
    return await client._fill_missing_channel_metadata(videos)


async def fetch_channel_details(channel_id: str) -> ChannelDetailModel:
    """Fetch full channel metadata (including joined date) via InnerTube browse."""
    client = _get_innertube_client()
    return await client.get_channel_details(channel_id)


async def get_search_suggestions(query: str) -> list[str]:
    """Return YouTube autocomplete suggestions for a partial query."""
    client = _get_innertube_client()
    return await client.get_search_suggestions(query)


async def get_related_search_suggestions(
    query: str,
    *,
    max_suggestions: int = 7,
) -> list[str]:
    """Return filtered autocomplete suggestions for niche analysis."""
    client = _get_innertube_client()
    return await client.get_related_search_suggestions(
        query,
        max_suggestions=max_suggestions,
    )


async def analyze_channel_from_url(
    url: str,
    *,
    max_results: int = 100,
) -> ChannelAnalysisModel:
    """Analyze a YouTube channel (or channel derived from a video URL)."""
    client = _get_innertube_client()
    return await client.analyze_channel(url, max_results=max_results)


def _get_innertube_client(
    *,
    innertube_metrics: InnerTubeMetrics | None = None,
) -> YouTubeApiClient:
    return YouTubeApiClient(
        YouTubeApiKeyManager(["unused-for-innertube"]),
        innertube_metrics=innertube_metrics,
    )


async def _demo_enriched_search() -> None:
    results = await get_enriched_search_results("python tutorial", max_results=5)
    for item in results:
        print(item.model_dump_json(indent=2))
        print("---")


if __name__ == "__main__":
    asyncio.run(_demo_enriched_search())
