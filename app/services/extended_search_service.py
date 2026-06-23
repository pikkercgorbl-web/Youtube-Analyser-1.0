"""Extended anomaly search via YouTube API with DB caching."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.integrations.youtube.client import YouTubeApiClient, YouTubeVideoDetails
from app.models.orm import Channel, ExtendedSearchCache, Video, VideoFormat
from app.models.schemas import (
    ExtendedSearchParams,
    ExtendedSearchResponse,
    ExtendedSearchVideoItem,
    UploadPeriod,
)
from app.services.metrics import ensure_utc, utc_now
from app.services.video_service import calc_virality_percent


class ExtendedSearchService:
    """Live YouTube extended search with virality ranking and 1-hour cache."""

    CACHE_TTL = timedelta(hours=1)

    def __init__(self, db: Session, youtube_client: YouTubeApiClient) -> None:
        self._db = db
        self._youtube = youtube_client

    def search(self, params: ExtendedSearchParams) -> ExtendedSearchResponse:
        cache_key = self._build_cache_key(params)
        cached_entry = self._get_valid_cache(cache_key)

        if cached_entry is not None:
            all_items = self._deserialize_items(cached_entry.payload["items"])
            page_items, total = self._paginate(all_items, params.limit, params.offset)
            return ExtendedSearchResponse(
                query=params.q,
                period=params.period,
                cached=True,
                cache_expires_at=cached_entry.expires_at,
                total=total,
                limit=params.limit,
                offset=params.offset,
                items=page_items,
            )

        published_after = self._period_to_datetime(params.period)
        search_hits = self._youtube.search_videos(
            params.q,
            published_after=published_after,
            max_results=50,
        )
        video_ids = [hit.video_id for hit in search_hits]

        video_details = self._youtube.get_videos(video_ids)
        channel_ids = [video.channel_id for video in video_details if video.channel_id]
        channels = self._youtube.get_channels(channel_ids)

        ranked_items = self._build_ranked_items(
            video_details,
            channels,
            params=params,
            published_after=published_after,
        )
        ranked_items.sort(key=lambda item: item.virality_percent, reverse=True)

        self._persist_entities(ranked_items)
        self._store_cache(cache_key, ranked_items)

        page_items, total = self._paginate(ranked_items, params.limit, params.offset)
        expires_at = utc_now() + self.CACHE_TTL

        return ExtendedSearchResponse(
            query=params.q,
            period=params.period,
            cached=False,
            cache_expires_at=expires_at,
            total=total,
            limit=params.limit,
            offset=params.offset,
            items=page_items,
        )

    def _build_ranked_items(
        self,
        videos: list[YouTubeVideoDetails],
        channels: dict,
        *,
        params: ExtendedSearchParams,
        published_after: datetime,
    ) -> list[ExtendedSearchVideoItem]:
        items: list[ExtendedSearchVideoItem] = []

        for video in videos:
            if video.published_at < published_after:
                continue
            if params.duration_min is not None and video.duration_seconds < params.duration_min:
                continue
            if params.duration_max is not None and video.duration_seconds > params.duration_max:
                continue
            if params.min_views is not None and video.views_count < params.min_views:
                continue
            if params.max_views is not None and video.views_count > params.max_views:
                continue

            channel = channels.get(video.channel_id)
            channel_title = channel.title if channel else "Unknown"
            subscribers = channel.subscribers_count if channel else 0
            virality = calc_virality_percent(video.views_count, subscribers)

            if params.min_virality_percent is not None and virality < params.min_virality_percent:
                continue

            items.append(
                ExtendedSearchVideoItem(
                    video_id=video.video_id,
                    title=video.title,
                    views_count=video.views_count,
                    likes_count=video.likes_count,
                    comments_count=video.comments_count,
                    published_at=video.published_at,
                    duration_seconds=video.duration_seconds,
                    channel_id=video.channel_id,
                    channel_title=channel_title,
                    channel_subscribers_count=subscribers,
                    virality_percent=round(virality, 2),
                ),
            )

        return items

    def _persist_entities(self, items: list[ExtendedSearchVideoItem]) -> None:
        now = utc_now()
        seen_channels: set[str] = set()

        for item in items:
            if item.channel_id not in seen_channels:
                channel = self._db.get(Channel, item.channel_id)
                if channel is None:
                    channel = Channel(
                        id=item.channel_id,
                        title=item.channel_title,
                        subscribers_count=item.channel_subscribers_count,
                        topic=None,
                        created_at=now,
                    )
                    self._db.add(channel)
                else:
                    channel.title = item.channel_title
                    channel.subscribers_count = item.channel_subscribers_count
                seen_channels.add(item.channel_id)

            video = self._db.get(Video, item.video_id)
            if video is None:
                video = Video(
                    id=item.video_id,
                    title=item.title,
                    views_count=item.views_count,
                    likes_count=item.likes_count,
                    comments_count=item.comments_count,
                    published_at=item.published_at,
                    duration_seconds=item.duration_seconds,
                    content_format=self._infer_format(item.duration_seconds),
                    topic=None,
                    tags=[],
                    channel_id=item.channel_id,
                )
                self._db.add(video)
            else:
                video.title = item.title
                video.views_count = item.views_count
                video.likes_count = item.likes_count
                video.comments_count = item.comments_count
                video.published_at = item.published_at
                video.duration_seconds = item.duration_seconds
                video.channel_id = item.channel_id

        self._db.commit()

    def _build_cache_key(self, params: ExtendedSearchParams) -> str:
        cache_payload = {
            "q": params.q.strip().lower(),
            "period": params.period.value,
            "duration_min": params.duration_min,
            "duration_max": params.duration_max,
            "min_views": params.min_views,
            "max_views": params.max_views,
            "min_virality_percent": params.min_virality_percent,
        }
        raw = json.dumps(cache_payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _get_valid_cache(self, cache_key: str) -> ExtendedSearchCache | None:
        now = utc_now()
        entry = self._db.get(ExtendedSearchCache, cache_key)
        if entry is None or ensure_utc(entry.expires_at) <= now:
            if entry is not None:
                self._db.execute(delete(ExtendedSearchCache).where(ExtendedSearchCache.cache_key == cache_key))
                self._db.commit()
            return None
        return entry

    def _store_cache(self, cache_key: str, items: list[ExtendedSearchVideoItem]) -> None:
        now = utc_now()
        expires_at = now + self.CACHE_TTL
        payload = {"items": [item.model_dump(mode="json") for item in items]}

        existing = self._db.get(ExtendedSearchCache, cache_key)
        if existing is None:
            self._db.add(
                ExtendedSearchCache(
                    cache_key=cache_key,
                    payload=payload,
                    created_at=now,
                    expires_at=expires_at,
                ),
            )
        else:
            existing.payload = payload
            existing.created_at = now
            existing.expires_at = expires_at

        self._db.commit()

    @staticmethod
    def _deserialize_items(raw_items: list[dict]) -> list[ExtendedSearchVideoItem]:
        return [ExtendedSearchVideoItem.model_validate(item) for item in raw_items]

    @staticmethod
    def _paginate(
        items: list[ExtendedSearchVideoItem],
        limit: int,
        offset: int,
    ) -> tuple[list[ExtendedSearchVideoItem], int]:
        total = len(items)
        return items[offset : offset + limit], total

    @staticmethod
    def _period_to_datetime(period: UploadPeriod) -> datetime:
        now = utc_now()
        if period == UploadPeriod.HOURS_24:
            return now - timedelta(hours=24)
        if period == UploadPeriod.WEEK:
            return now - timedelta(days=7)
        return now - timedelta(days=30)

    @staticmethod
    def _infer_format(duration_seconds: int) -> VideoFormat:
        if duration_seconds <= 60:
            return VideoFormat.SHORT
        if duration_seconds <= 1200:
            return VideoFormat.MEDIUM
        return VideoFormat.LONG
