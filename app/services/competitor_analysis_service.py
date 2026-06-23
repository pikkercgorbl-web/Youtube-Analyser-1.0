"""Competitor aggregation: mass analysis and YouTube leaders."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.integrations.youtube.client import ChannelVideoBrowseModel, YouTubeApiClient, YouTubeVideoDetails
from app.models.orm import Channel, ChannelSnapshot, Video, VideoFormat
from app.models.schemas import (
    ChannelAnalysisSummary,
    ChannelGrowthLeader,
    DimensionAggregate,
    MassAnalysisResponse,
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
        now = utc_now()
        channel_rows: list[tuple[str, str, list[VideoMetricRow]]] = []
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

                self._upsert_channel_innertube(
                    channel_id,
                    resolved_title,
                    channel_details.subscribers_count,
                )

                analyzed_videos = [self._from_browse_video(video) for video in browse_videos]
                self._upsert_browse_videos(channel_id, analyzed_videos)

                metric_rows = [
                    VideoMetricRow(
                        video=video,
                        vph=calc_vph(video.views_count, video.published_at, now=now),
                    )
                    for video in analyzed_videos
                ]
                channel_rows.append((channel_id, resolved_title, metric_rows))
            except Exception as exc:
                print(f"❌ Ошибка загрузки канала [{identifier}]: [{exc}]")
                failed_channels.append(ref)

        self._db.commit()
        return self._build_mass_response(
            channel_refs=channel_refs,
            channel_rows=channel_rows,
            not_found=failed_channels,
        )

    def _mass_analyze_from_db(
        self,
        channel_refs: list[str],
        *,
        videos_per_channel: int,
    ) -> MassAnalysisResponse:
        now = utc_now()
        channel_rows: list[tuple[str, str, list[VideoMetricRow]]] = []
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
            metric_rows = [
                VideoMetricRow(
                    video=self._from_db_video(video),
                    vph=calc_vph(video.views_count, video.published_at, now=now),
                )
                for video in videos
            ]
            channel_rows.append((channel.id, channel.title, metric_rows))

        return self._build_mass_response(
            channel_refs=channel_refs,
            channel_rows=channel_rows,
            not_found=failed_channels,
        )

    def _build_mass_response(
        self,
        *,
        channel_refs: list[str],
        channel_rows: list[tuple[str, str, list[VideoMetricRow]]],
        not_found: list[str],
    ) -> MassAnalysisResponse:
        all_rows = [row for _, _, rows in channel_rows for row in rows]

        by_format = _aggregate_dimension(
            all_rows,
            dimension_type="format",
            keys_for_video=lambda video: infer_video_format(
                duration_seconds=video.duration_seconds,
                content_format=video.content_format,
            ).value,
        )
        by_topic = _aggregate_dimension(
            all_rows,
            dimension_type="topic",
            keys_for_video=lambda video: video.topic or "unknown",
        )
        by_tag = _aggregate_dimension(
            all_rows,
            dimension_type="tag",
            keys_for_video=lambda video: [_normalize_tag(tag) for tag in video.tags] or ["untagged"],
        )
        by_title_keyword = _aggregate_dimension(
            all_rows,
            dimension_type="title_keyword",
            keys_for_video=lambda video: extract_title_keywords(video.title) or ["untitled"],
        )

        all_dimensions = by_format + by_topic + by_tag + by_title_keyword
        top_by_avg_views = sorted(all_dimensions, key=lambda item: item.avg_views, reverse=True)[:15]
        top_by_avg_vph = sorted(all_dimensions, key=lambda item: item.avg_vph, reverse=True)[:15]
        top_by_total_views = sorted(all_dimensions, key=lambda item: item.total_views, reverse=True)[:15]

        channel_summaries = [
            ChannelAnalysisSummary(
                channel_id=channel_id,
                channel_title=channel_title,
                videos_analyzed=len(rows),
                total_views=sum(row.video.views_count for row in rows),
                avg_vph=(sum(row.vph for row in rows) / len(rows)) if rows else 0.0,
            )
            for channel_id, channel_title, rows in channel_rows
        ]

        return MassAnalysisResponse(
            channels_requested=len(channel_refs),
            channels_found=len(channel_rows),
            channels_not_found=not_found,
            total_videos_analyzed=len(all_rows),
            channels=sorted(channel_summaries, key=lambda item: item.avg_vph, reverse=True),
            top_by_avg_views=top_by_avg_views,
            top_by_avg_vph=top_by_avg_vph,
            top_by_total_views=top_by_total_views,
            by_format=sorted(by_format, key=lambda item: item.avg_views, reverse=True),
            by_topic=sorted(by_topic, key=lambda item: item.avg_views, reverse=True),
            by_tag=sorted(by_tag, key=lambda item: item.avg_views, reverse=True),
            by_title_keyword=sorted(by_title_keyword, key=lambda item: item.avg_views, reverse=True),
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
