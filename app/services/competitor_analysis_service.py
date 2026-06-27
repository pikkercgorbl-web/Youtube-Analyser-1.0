"""Competitor aggregation: mass analysis and YouTube leaders."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.integrations.youtube.client import ChannelVideoBrowseModel, YouTubeApiClient, YouTubeVideoDetails
from app.models.orm import Channel, ChannelSnapshot, Video, VideoFormat
from app.models.schemas import (
    ChannelAnalysisSummary,
    ChannelGrowthLeader,
    DimensionAggregate,
    MassAnalysisResponse,
    MassAnalysisVideoItem,
    YouTubeLeadersResponse,
)
from app.services.metrics import (
    calc_growth_rate,
    calc_growth_score,
    calc_vph,
    safe_median,
    utc_now,
)
from app.services.video_filter_service import parse_duration_text, parse_relative_published_date
from app.utils.text import extract_title_keywords
from app.utils.youtube import extract_channel_identifier, handle_from_key, is_handle_key


@dataclass(frozen=True, slots=True)
class AnalyzedVideo:
    """Normalized video row used by aggregation helpers."""

    video_id: str
    title: str
    views_count: int
    published_at: datetime
    duration_seconds: int
    content_format: VideoFormat
    topic: str | None
    tags: list[str]


@dataclass(frozen=True, slots=True)
class VideoMetricRow:
    video: AnalyzedVideo
    vph: float


def infer_video_format(*, duration_seconds: int, content_format: VideoFormat | None = None) -> VideoFormat:
    """Resolve format from explicit metadata or duration heuristics."""
    if content_format is not None and content_format != VideoFormat.UNKNOWN:
        return content_format
    if duration_seconds <= 60:
        return VideoFormat.SHORT
    if duration_seconds <= 1200:
        return VideoFormat.MEDIUM
    return VideoFormat.LONG


def _normalize_tag(tag: str) -> str:
    return tag.strip().lower()


def _aggregate_dimension(
    rows: list[VideoMetricRow],
    *,
    dimension_type: str,
    keys_for_video,
) -> list[DimensionAggregate]:
    groups: dict[str, list[VideoMetricRow]] = defaultdict(list)

    for row in rows:
        keys = keys_for_video(row.video)
        if isinstance(keys, str):
            keys = [keys]
        for key in keys:
            if key:
                groups[key].append(row)

    aggregates: list[DimensionAggregate] = []
    for value, group_rows in groups.items():
        vph_values = [item.vph for item in group_rows]
        view_values = [item.video.views_count for item in group_rows]
        aggregates.append(
            DimensionAggregate(
                dimension_type=dimension_type,
                dimension_value=value,
                video_count=len(group_rows),
                total_views=sum(view_values),
                avg_views=sum(view_values) / len(view_values),
                avg_vph=sum(vph_values) / len(vph_values),
                median_vph=safe_median(vph_values),
            ),
        )

    return aggregates


def _average_views(values: Iterable[int]) -> int:
    view_counts = [max(value, 0) for value in values]
    if not view_counts:
        return 0
    return round(sum(view_counts) / len(view_counts))


def _outlier_score(views_count: int, average_views: int) -> float:
    if average_views <= 0:
        return 0.0
    return round(max(views_count, 0) / average_views, 1)


class CompetitorAnalysisService:
    """Mass competitor analysis and channel growth trend detection."""

    def __init__(self, db: Session, youtube_client: YouTubeApiClient | None = None) -> None:
        self._db = db
        self._youtube = youtube_client

    def mass_analyze(
        self,
        channel_refs: list[str],
        *,
        videos_per_channel: int = 30,
    ) -> MassAnalysisResponse:
        """
        Aggregate the last N videos across 3–20 competitor channels.

        Fetches live data from YouTube when a client is configured; otherwise
        falls back to the local database (useful for tests).

        Metrics:
        - avg_views — mean views grouped by format/topic/tag/title keyword
        - VPH (Views Per Hour) = views / hours_since_publish
        """
        if self._youtube is None:
            return self._mass_analyze_from_db(channel_refs, videos_per_channel=videos_per_channel)
        raise RuntimeError("Use mass_analyze_async when a YouTube client is configured")

    async def mass_analyze_async(
        self,
        channel_refs: list[str],
        *,
        videos_per_channel: int = 30,
    ) -> MassAnalysisResponse:
        """Async mass analysis via InnerTube (used by the HTTP API)."""
        if self._youtube is None:
            return self._mass_analyze_from_db(channel_refs, videos_per_channel=videos_per_channel)
        return await self._mass_analyze_from_innertube(
            channel_refs,
            videos_per_channel=videos_per_channel,
        )

    def get_youtube_leaders(
        self,
        *,
        window_days: int = 7,
        limit: int = 10,
    ) -> YouTubeLeadersResponse:
        """
        Rank channels by growth velocity over the last N days.

        Growth % = ((current - baseline) / max(baseline, 1)) × 100
        Baseline = closest snapshot at or before (now - window_days).
        Current  = live channel.subscribers_count + sum(video.views_count).
        growth_score = 0.4 × subs_growth + 0.6 × views_growth
        """
        if window_days < 3 or window_days > 7:
            msg = "window_days must be between 3 and 7"
            raise ValueError(msg)

        cutoff = utc_now() - timedelta(days=window_days)
        channels = list(self._db.scalars(select(Channel)).all())

        leaders: list[ChannelGrowthLeader] = []
        skipped = 0

        for channel in channels:
            baseline = self._get_baseline_snapshot(channel.id, cutoff)
            if baseline is None:
                skipped += 1
                continue

            current_views = self._channel_total_views(channel.id)
            current_subscribers = channel.subscribers_count

            subs_growth = calc_growth_rate(current_subscribers, baseline.subscribers_count)
            views_growth = calc_growth_rate(current_views, baseline.total_views)
            score = calc_growth_score(subs_growth, views_growth)

            leaders.append(
                ChannelGrowthLeader(
                    channel_id=channel.id,
                    channel_title=channel.title,
                    topic=channel.topic,
                    current_subscribers=current_subscribers,
                    current_total_views=current_views,
                    subscribers_growth_pct=round(subs_growth, 2),
                    views_growth_pct=round(views_growth, 2),
                    growth_score=round(score, 2),
                    snapshot_date=baseline.recorded_at,
                ),
            )

        leaders.sort(key=lambda item: item.growth_score, reverse=True)

        return YouTubeLeadersResponse(
            window_days=window_days,
            leaders=leaders[:limit],
            channels_without_baseline=skipped,
        )

    def record_channel_snapshot(self, channel_id: str, *, recorded_at: datetime | None = None) -> ChannelSnapshot:
        """Persist a point-in-time snapshot for future growth calculations."""
        channel = self._db.get(Channel, channel_id)
        if channel is None:
            msg = f"Channel not found: {channel_id}"
            raise ValueError(msg)

        videos = list(
            self._db.scalars(select(Video).where(Video.channel_id == channel_id)).all(),
        )
        snapshot = ChannelSnapshot(
            channel_id=channel_id,
            subscribers_count=channel.subscribers_count,
            total_views=sum(video.views_count for video in videos),
            video_count=len(videos),
            recorded_at=recorded_at or utc_now(),
        )
        self._db.add(snapshot)
        self._db.commit()
        self._db.refresh(snapshot)
        return snapshot

    async def _mass_analyze_from_innertube(
        self,
        channel_refs: list[str],
        *,
        videos_per_channel: int,
    ) -> MassAnalysisResponse:
        assert self._youtube is not None
        outlier_videos: list[MassAnalysisVideoItem] = []
        failed_channels: list[str] = []

        for ref in channel_refs:
            print(f"📥 Входная строка: [{ref}]")

            try:
                identifier = extract_channel_identifier(ref)
            except ValueError as exc:
                print(f"❌ Ошибка загрузки канала [{ref}]: [{exc}]")
                failed_channels.append(ref)
                continue

            print(f"✂️ Извлеченный ID: [{identifier}]")

            try:
                channel_id, title_hint = await self._youtube.resolve_channel_identifier(identifier)
                channel_details = await self._youtube.get_channel_details(channel_id)
                channel_title, browse_videos = await self._youtube.get_channel_videos_tab(
                    channel_id,
                    max_results=videos_per_channel,
                )
                resolved_title = channel_title or title_hint or channel_id
                channel_url = f"https://www.youtube.com/channel/{channel_id}"

                self._upsert_channel_innertube(
                    channel_id,
                    resolved_title,
                    channel_details.subscribers_count,
                )

                analyzed_videos = [self._from_browse_video(video) for video in browse_videos]
                self._upsert_browse_videos(channel_id, analyzed_videos)
                average_views = _average_views(video.views_count for video in analyzed_videos)

                outlier_videos.extend(
                    MassAnalysisVideoItem(
                        channel_name=resolved_title,
                        channel_url=channel_url,
                        channel_avatar=channel_details.channel_avatar_url,
                        video_title=video.title,
                        video_url=f"https://www.youtube.com/watch?v={video.video_id}",
                        views=video.views_count,
                        channel_average_views=average_views,
                        outlier_score=_outlier_score(video.views_count, average_views),
                        published_at=browse_video.published_text or video.published_at.isoformat(),
                    )
                    for video, browse_video in zip(analyzed_videos, browse_videos, strict=False)
                )
            except Exception as exc:
                print(f"❌ Ошибка загрузки канала [{identifier}]: [{exc}]")
                failed_channels.append(ref)

        self._db.commit()
        return MassAnalysisResponse(
            channels_requested=len(channel_refs),
            channels_found=len(channel_refs) - len(failed_channels),
            channels_not_found=failed_channels,
            total_videos_analyzed=len(outlier_videos),
            videos=sorted(outlier_videos, key=lambda item: item.outlier_score, reverse=True),
        )

    def _mass_analyze_from_db(
        self,
        channel_refs: list[str],
        *,
        videos_per_channel: int,
    ) -> MassAnalysisResponse:
        outlier_videos: list[MassAnalysisVideoItem] = []
        failed_channels: list[str] = []

        for ref in channel_refs:
            try:
                identifier = extract_channel_identifier(ref)
                channel_key = (
                    f"handle:{identifier[1:]}"
                    if identifier.startswith("@")
                    else identifier
                )
            except ValueError:
                failed_channels.append(ref)
                continue

            channel = self._resolve_channel(channel_key)
            if channel is None:
                failed_channels.append(ref)
                continue

            videos = self._fetch_recent_videos(channel.id, limit=videos_per_channel)
            average_views = _average_views(video.views_count for video in videos)
            outlier_videos.extend(
                MassAnalysisVideoItem(
                    channel_name=channel.title,
                    channel_url=f"https://www.youtube.com/channel/{channel.id}",
                    channel_avatar="",
                    video_title=video.title,
                    video_url=f"https://www.youtube.com/watch?v={video.id}",
                    views=video.views_count,
                    channel_average_views=average_views,
                    outlier_score=_outlier_score(video.views_count, average_views),
                    published_at=video.published_at.isoformat(),
                )
                for video in videos
            )

        return MassAnalysisResponse(
            channels_requested=len(channel_refs),
            channels_found=len(channel_refs) - len(failed_channels),
            channels_not_found=failed_channels,
            total_videos_analyzed=len(outlier_videos),
            videos=sorted(outlier_videos, key=lambda item: item.outlier_score, reverse=True),
        )

    def _build_mass_response(
        self,
        *,
        channel_refs: list[str],
        channel_rows: list[tuple[str, str, list[VideoMetricRow]]],
        not_found: list[str],
    ) -> MassAnalysisResponse:
        outlier_videos: list[MassAnalysisVideoItem] = []
        for channel_id, channel_title, rows in channel_rows:
            average_views = _average_views(row.video.views_count for row in rows)
            outlier_videos.extend(
                MassAnalysisVideoItem(
                    channel_name=channel_title,
                    channel_url=f"https://www.youtube.com/channel/{channel_id}",
                    channel_avatar="",
                    video_title=row.video.title,
                    video_url=f"https://www.youtube.com/watch?v={row.video.video_id}",
                    views=row.video.views_count,
                    channel_average_views=average_views,
                    outlier_score=_outlier_score(row.video.views_count, average_views),
                    published_at=row.video.published_at.isoformat(),
                )
                for row in rows
            )
        return MassAnalysisResponse(
            channels_requested=len(channel_refs),
            channels_found=len(channel_rows),
            channels_not_found=not_found,
            total_videos_analyzed=len(outlier_videos),
            videos=sorted(outlier_videos, key=lambda item: item.outlier_score, reverse=True),
        )

    def _upsert_channel(self, channel_details) -> None:
        channel = self._db.get(Channel, channel_details.channel_id)
        if channel is None:
            channel = Channel(
                id=channel_details.channel_id,
                title=channel_details.title,
                subscribers_count=channel_details.subscribers_count,
                topic=None,
                created_at=utc_now(),
            )
            self._db.add(channel)
        else:
            channel.title = channel_details.title
            channel.subscribers_count = channel_details.subscribers_count

    def _upsert_videos(self, channel_id: str, videos: list[YouTubeVideoDetails]) -> None:
        for video in videos:
            existing = self._db.get(Video, video.video_id)
            content_format = infer_video_format(duration_seconds=video.duration_seconds)
            if existing is None:
                self._db.add(
                    Video(
                        id=video.video_id,
                        title=video.title,
                        views_count=video.views_count,
                        likes_count=video.likes_count,
                        comments_count=video.comments_count,
                        published_at=video.published_at,
                        duration_seconds=video.duration_seconds,
                        content_format=content_format,
                        topic=None,
                        tags=[],
                        channel_id=channel_id,
                    ),
                )
            else:
                existing.title = video.title
                existing.views_count = video.views_count
                existing.likes_count = video.likes_count
                existing.comments_count = video.comments_count
                existing.duration_seconds = video.duration_seconds
                existing.content_format = content_format

    def _upsert_channel_innertube(
        self,
        channel_id: str,
        title: str,
        subscribers_count: int,
    ) -> None:
        channel = self._db.get(Channel, channel_id)
        if channel is None:
            channel = Channel(
                id=channel_id,
                title=title,
                subscribers_count=subscribers_count,
                topic=None,
                created_at=utc_now(),
            )
            self._db.add(channel)
        else:
            channel.title = title
            channel.subscribers_count = subscribers_count

    def _upsert_browse_videos(self, channel_id: str, videos: list[AnalyzedVideo]) -> None:
        for video in videos:
            existing = self._db.get(Video, video.video_id)
            content_format = infer_video_format(duration_seconds=video.duration_seconds)
            if existing is None:
                self._db.add(
                    Video(
                        id=video.video_id,
                        title=video.title,
                        views_count=video.views_count,
                        likes_count=0,
                        comments_count=0,
                        published_at=video.published_at,
                        duration_seconds=video.duration_seconds,
                        content_format=content_format,
                        topic=None,
                        tags=[],
                        channel_id=channel_id,
                    ),
                )
            else:
                existing.title = video.title
                existing.views_count = video.views_count
                existing.duration_seconds = video.duration_seconds
                existing.content_format = content_format

    def _from_browse_video(self, video: ChannelVideoBrowseModel) -> AnalyzedVideo:
        duration_seconds = parse_duration_text(video.duration_text)
        published_at = parse_relative_published_date(video.published_text)
        return AnalyzedVideo(
            video_id=video.video_id,
            title=video.title,
            views_count=video.views_count,
            published_at=published_at,
            duration_seconds=duration_seconds,
            content_format=infer_video_format(duration_seconds=duration_seconds),
            topic=None,
            tags=[],
        )

    def _from_youtube_video(self, video: YouTubeVideoDetails) -> AnalyzedVideo:
        return AnalyzedVideo(
            video_id=video.video_id,
            title=video.title,
            views_count=video.views_count,
            published_at=video.published_at,
            duration_seconds=video.duration_seconds,
            content_format=infer_video_format(duration_seconds=video.duration_seconds),
            topic=None,
            tags=[],
        )

    def _from_db_video(self, video: Video) -> AnalyzedVideo:
        return AnalyzedVideo(
            video_id=video.id,
            title=video.title,
            views_count=video.views_count,
            published_at=video.published_at,
            duration_seconds=video.duration_seconds,
            content_format=infer_video_format(
                duration_seconds=video.duration_seconds,
                content_format=video.content_format,
            ),
            topic=video.topic,
            tags=video.tags or [],
        )

    def _resolve_channel(self, key: str) -> Channel | None:
        if is_handle_key(key):
            handle = handle_from_key(key)
            stmt = select(Channel).where(func.lower(Channel.custom_url) == handle.lower())
            return self._db.scalar(stmt)
        return self._db.get(Channel, key)

    def _fetch_recent_videos(self, channel_id: str, *, limit: int) -> list[Video]:
        stmt = (
            select(Video)
            .where(Video.channel_id == channel_id)
            .order_by(Video.published_at.desc())
            .limit(limit)
        )
        return list(self._db.scalars(stmt).all())

    def _channel_total_views(self, channel_id: str) -> int:
        total = self._db.scalar(
            select(func.coalesce(func.sum(Video.views_count), 0)).where(Video.channel_id == channel_id),
        )
        return int(total or 0)

    def _get_baseline_snapshot(self, channel_id: str, cutoff: datetime) -> ChannelSnapshot | None:
        stmt = (
            select(ChannelSnapshot)
            .where(
                ChannelSnapshot.channel_id == channel_id,
                ChannelSnapshot.recorded_at <= cutoff,
            )
            .order_by(ChannelSnapshot.recorded_at.desc())
            .limit(1)
        )
        return self._db.scalar(stmt)
