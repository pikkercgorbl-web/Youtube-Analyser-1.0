from __future__ import annotations

import enum
from datetime import datetime

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.orm import CompetitionLevel


class VideoSortField(str, enum.Enum):
    """Sortable fields for advanced video search."""

    PUBLISHED_AT = "published_at"
    VIEWS_COUNT = "views_count"
    VIRALITY = "virality"


class SortOrder(str, enum.Enum):
    ASC = "asc"
    DESC = "desc"


class UploadPeriod(str, enum.Enum):
    """Preset upload date windows for extended search."""

    HOURS_24 = "24h"
    WEEK = "week"
    MONTH = "month"


class ChannelBase(BaseModel):
    """Shared fields for channel schemas."""

    title: str = Field(..., min_length=1, max_length=255)
    subscribers_count: int = Field(default=0, ge=0)
    topic: str | None = Field(default=None, max_length=128)
    created_at: datetime


class ChannelCreate(ChannelBase):
    """Payload for creating a channel."""

    id: str = Field(..., min_length=1, max_length=64)


class ChannelUpdate(BaseModel):
    """Partial update payload for a channel."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    subscribers_count: int | None = Field(default=None, ge=0)
    topic: str | None = Field(default=None, max_length=128)


class ChannelRead(ChannelBase):
    """Channel representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    updated_at: datetime


class VideoBase(BaseModel):
    """Shared fields for video schemas."""

    title: str = Field(..., min_length=1, max_length=512)
    views_count: int = Field(default=0, ge=0)
    likes_count: int = Field(default=0, ge=0)
    comments_count: int = Field(default=0, ge=0)
    published_at: datetime
    duration_seconds: int = Field(default=0, ge=0)


class VideoCreate(VideoBase):
    """Payload for creating a video."""

    id: str = Field(..., min_length=1, max_length=64)
    channel_id: str = Field(..., min_length=1, max_length=64)


class VideoUpdate(BaseModel):
    """Partial update payload for a video."""

    title: str | None = Field(default=None, min_length=1, max_length=512)
    views_count: int | None = Field(default=None, ge=0)
    likes_count: int | None = Field(default=None, ge=0)
    comments_count: int | None = Field(default=None, ge=0)
    duration_seconds: int | None = Field(default=None, ge=0)


class VideoRead(VideoBase):
    """Video representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    channel_id: str
    updated_at: datetime


class VideoSearchParams(BaseModel):
    """Deep filters for advanced video search."""

    published_from: datetime | None = None
    published_to: datetime | None = None
    duration_min: int | None = Field(default=None, ge=0)
    duration_max: int | None = Field(default=None, ge=0)
    views_min: int | None = Field(default=None, ge=0)
    views_max: int | None = Field(default=None, ge=0)
    channel_id: str | None = Field(default=None, max_length=64)
    anomalies_only: bool = Field(
        default=False,
        description="Return only viral anomalies (views/subscribers above threshold)",
    )
    min_virality_percent: float = Field(
        default=1000.0,
        ge=0,
        description="Minimum virality %: (views / subscribers) × 100. 1000 = 10× subs.",
    )
    sort_by: VideoSortField = VideoSortField.PUBLISHED_AT
    sort_order: SortOrder = SortOrder.DESC
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_ranges(self) -> VideoSearchParams:
        if (
            self.published_from is not None
            and self.published_to is not None
            and self.published_from > self.published_to
        ):
            msg = "published_from must be earlier than or equal to published_to"
            raise ValueError(msg)
        if (
            self.duration_min is not None
            and self.duration_max is not None
            and self.duration_min > self.duration_max
        ):
            msg = "duration_min must be less than or equal to duration_max"
            raise ValueError(msg)
        if (
            self.views_min is not None
            and self.views_max is not None
            and self.views_min > self.views_max
        ):
            msg = "views_min must be less than or equal to views_max"
            raise ValueError(msg)
        return self


class VideoSearchItem(VideoRead):
    """Video search result with channel context and virality metric."""

    channel_title: str
    channel_subscribers_count: int
    virality_percent: float = Field(
        description="(views / max(subscribers, 1)) × 100",
    )


class VideoSearchResponse(BaseModel):
    """Paginated advanced video search response."""

    items: list[VideoSearchItem]
    total: int
    limit: int
    offset: int


class KeywordBase(BaseModel):
    """Shared fields for keyword schemas."""

    text: str = Field(..., min_length=1)
    search_volume: int = Field(default=0, ge=0)
    competition_level: CompetitionLevel = CompetitionLevel.MEDIUM


class KeywordCreate(KeywordBase):
    """Payload for creating a keyword."""


class KeywordUpdate(BaseModel):
    """Partial update payload for a keyword."""

    text: str | None = Field(default=None, min_length=1)
    search_volume: int | None = Field(default=None, ge=0)
    competition_level: CompetitionLevel | None = None


class KeywordRead(KeywordBase):
    """Keyword representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class MassAnalysisRequest(BaseModel):
    """Request payload for competitor mass analysis."""

    channel_refs: list[str] = Field(
        ...,
        min_length=3,
        max_length=20,
        description="3–20 YouTube channel IDs or URLs",
    )
    videos_per_channel: int = Field(default=30, ge=1, le=50)


class DimensionAggregate(BaseModel):
    """Aggregated stats for a format, topic, tag, or title keyword."""

    dimension_type: str = Field(description="format | topic | tag | title_keyword")
    dimension_value: str
    video_count: int = Field(ge=0)
    total_views: int = Field(ge=0)
    avg_views: float = Field(description="Mean views across videos in group")
    avg_vph: float = Field(description="Mean views per hour across videos in group")
    median_vph: float = Field(description="Median views per hour across videos in group")


class ChannelAnalysisSummary(BaseModel):
    """Per-channel rollup inside a mass analysis run."""

    channel_id: str
    channel_title: str
    videos_analyzed: int
    total_views: int
    avg_vph: float


class MassAnalysisResponse(BaseModel):
    """Aggregated competitor analysis across multiple channels."""

    channels_requested: int
    channels_found: int
    channels_not_found: list[str]
    total_videos_analyzed: int
    channels: list[ChannelAnalysisSummary]
    top_by_avg_views: list[DimensionAggregate]
    top_by_avg_vph: list[DimensionAggregate]
    top_by_total_views: list[DimensionAggregate]
    by_format: list[DimensionAggregate]
    by_topic: list[DimensionAggregate]
    by_tag: list[DimensionAggregate]
    by_title_keyword: list[DimensionAggregate]


class ChannelGrowthLeader(BaseModel):
    """Fastest-growing channel within the observation window."""

    channel_id: str
    channel_title: str
    topic: str | None
    current_subscribers: int
    current_total_views: int
    subscribers_growth_pct: float = Field(description="Subscriber growth % over window")
    views_growth_pct: float = Field(description="Total views growth % over window")
    growth_score: float = Field(description="Weighted composite trend score")
    snapshot_date: datetime = Field(description="Baseline snapshot used for comparison")


class YouTubeLeadersResponse(BaseModel):
    """Top fastest-growing channels (micro-trend watchlist)."""

    window_days: int
    leaders: list[ChannelGrowthLeader]
    channels_without_baseline: int = Field(
        description="Channels skipped due to missing snapshot before window start",
    )


class ExtendedSearchParams(BaseModel):
    """Deep filters for live YouTube extended anomaly search."""

    q: str = Field(..., min_length=1, max_length=256, description="Keyword or niche query")
    period: UploadPeriod = Field(default=UploadPeriod.WEEK, description="Upload date window")
    duration_min: int | None = Field(default=None, ge=0)
    duration_max: int | None = Field(default=None, ge=0)
    min_views: int | None = Field(default=None, ge=0)
    max_views: int | None = Field(default=None, ge=0)
    min_virality_percent: float | None = Field(
        default=None,
        ge=0,
        description="Minimum (views / subscribers) × 100",
    )
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_ranges(self) -> ExtendedSearchParams:
        if (
            self.duration_min is not None
            and self.duration_max is not None
            and self.duration_min > self.duration_max
        ):
            msg = "duration_min must be less than or equal to duration_max"
            raise ValueError(msg)
        if (
            self.min_views is not None
            and self.max_views is not None
            and self.min_views > self.max_views
        ):
            msg = "min_views must be less than or equal to max_views"
            raise ValueError(msg)
        return self


class ExtendedSearchVideoItem(BaseModel):
    """Anomaly-ranked video returned by extended search."""

    video_id: str
    title: str
    views_count: int
    likes_count: int
    comments_count: int
    published_at: datetime
    duration_seconds: int
    channel_id: str
    channel_title: str
    channel_subscribers_count: int
    virality_percent: float = Field(description="(views / max(subscribers, 1)) × 100")


class ExtendedSearchResponse(BaseModel):
    """Extended anomaly search response."""

    query: str
    period: UploadPeriod
    cached: bool
    cache_expires_at: datetime | None
    total: int
    limit: int
    offset: int
    items: list[ExtendedSearchVideoItem]


class KeywordTopResultItem(BaseModel):
    """Single video from the keyword SERP used for analysis."""

    rank: int = Field(ge=1, le=20)
    video_id: str
    title: str
    views_count: int = Field(ge=0)
    channel_id: str
    channel_title: str
    channel_subscribers: int = Field(ge=0)


class KeywordSimilarTag(BaseModel):
    """Co-occurring tag or title token in the analyzed SERP."""

    tag: str
    frequency: int = Field(ge=1)
    relevance: float = Field(ge=0, le=1, description="Share of analyzed videos mentioning the tag")


class KeywordVolumeMetrics(BaseModel):
    """Search volume estimation for a keyword."""

    total_views: int = Field(ge=0, description="Sum of views across top SERP videos")
    avg_views: float = Field(ge=0)
    median_views: int = Field(ge=0)
    tag_mention_rate: float = Field(ge=0, le=1, description="Fraction of videos whose tags contain the keyword")
    title_mention_rate: float = Field(ge=0, le=1, description="Fraction of titles mentioning keyword tokens")
    volume_score: float = Field(ge=0, le=100, description="Normalized search volume score")


class KeywordCompetitionMetrics(BaseModel):
    """Channel authority analysis for the keyword SERP."""

    avg_channel_subscribers: int = Field(ge=0)
    median_channel_subscribers: int = Field(ge=0)
    mega_channel_count: int = Field(ge=0, description="Channels with >= 1M subscribers")
    small_channel_count: int = Field(ge=0, description="Channels with < 50K subscribers")
    mega_channel_ratio: float = Field(ge=0, le=1)
    small_channel_ratio: float = Field(ge=0, le=1)
    competition_score: float = Field(ge=0, le=100, description="Higher = harder to rank")
    competition_level: CompetitionLevel


class KeywordAnalyzeResponse(BaseModel):
    """Evergreen keyword opportunity report."""

    keyword: str
    opportunity_score: int = Field(ge=1, le=100, description="1–100; high volume + low competition wins")
    volume: KeywordVolumeMetrics
    competition: KeywordCompetitionMetrics
    similar_tags: list[KeywordSimilarTag]
    top_results: list[KeywordTopResultItem]
    analyzed_videos: int = Field(ge=0, le=20)
    recommendation: str


class SearchFiltersModel(BaseModel):
    """Filters applied after InnerTube search enrichment (base + advanced)."""

    # Base filters (rendered directly on the search page).
    hide_shorts: bool = False
    hide_regular: bool = False
    hide_streams: bool = False
    published_within: str | None = Field(
        default=None,
        description="Upload window: hour | 24h | week | month | year",
    )
    duration: str | None = Field(
        default=None,
        description="Duration bucket: short (<3m) | medium (3-20m) | long (>20m)",
    )

    # Advanced filters (rendered inside the modal) — video tab.
    hide_hieroglyphs: bool = False
    virality_only_above_one: bool = False
    virality_min: float | None = Field(default=None, ge=0)
    virality_max: float | None = Field(default=None, ge=0)
    views_min: int | None = Field(default=None, ge=0)
    views_max: int | None = Field(default=None, ge=0)
    plus_words: list[str] = Field(default_factory=list)
    minus_words: list[str] = Field(default_factory=list)

    # Advanced filters (rendered inside the modal) — channel tab.
    hide_verified: bool = False
    hide_artist: bool = False
    hide_kids: bool = False
    subscribers_min: int | None = Field(default=None, ge=0)
    subscribers_max: int | None = Field(default=None, ge=0)
    channel_views_min: int | None = Field(default=None, ge=0)
    channel_views_max: int | None = Field(default=None, ge=0)
    channel_videos_min: int | None = Field(default=None, ge=0)
    channel_videos_max: int | None = Field(default=None, ge=0)
    channel_age_min: int | None = Field(default=None, ge=0)
    channel_age_max: int | None = Field(default=None, ge=0)


class SearchRequest(BaseModel):
    """InnerTube search request with optional filter settings."""

    query: str = Field(..., min_length=1, max_length=256)
    filters: SearchFiltersModel | None = None
    sort_by: str = Field(default="relevance")


class InnertubeSearchRequest(BaseModel):
    """InnerTube search request with optional local filters."""

    query: str = Field(..., min_length=1, max_length=256)
    filters: SearchFiltersModel = Field(default_factory=SearchFiltersModel)
    sort_by: str = Field(default="relevance")
    max_results: int = Field(default=50, ge=1, le=50)


class AnalyzeChannelRequest(BaseModel):
    """Analyze a YouTube channel or derive channel from a video URL."""

    url: str = Field(..., min_length=1, max_length=512)


class ChannelAnalysisVideoItem(BaseModel):
    """Single video parsed from a channel's Videos tab."""

    video_id: str
    title: str
    url: str
    thumbnail_url: str = ""
    views_count: int = Field(default=0, ge=0)
    published_text: str = ""
    duration_text: str = ""
    virality_coefficient: float = Field(default=0, ge=0)


class AnalyzeChannelResponse(BaseModel):
    """Channel analysis with recent uploads enriched by virality."""

    channel_id: str
    channel_title: str = ""
    subscribers_count: int = Field(default=0, ge=0)
    channel_avatar_url: str = ""
    videos: list[ChannelAnalysisVideoItem]
    total_videos: int = Field(ge=0)


class KeywordResearchVideoItem(BaseModel):
    """Top SERP video used for keyword research metrics."""

    rank: int = Field(ge=1, le=20)
    video_id: str
    title: str
    url: str
    thumbnail_url: str = ""
    views_count: int = Field(default=0, ge=0)
    channel_title: str = ""
    channel_subscribers: int = Field(default=0, ge=0)
    virality_coefficient: float = Field(default=0, ge=0)


class KeywordResearchItem(BaseModel):
    """SEO metrics for one keyword in keyword research response."""

    keyword: str
    volume: int = Field(ge=0, le=100)
    competition: int = Field(ge=0, le=100)
    score: float = Field(ge=0, le=100)


class KeywordResearchSuggestions(BaseModel):
    """Categorized autocomplete suggestions with SEO metrics."""

    similar: list[KeywordResearchItem]
    questions: list[KeywordResearchItem]
    related: list[KeywordResearchItem]


class KeywordResearchResponse(BaseModel):
    """SEO keyword research for a main query and categorized suggestions."""

    main_query: KeywordResearchItem
    suggestions: KeywordResearchSuggestions


class KeywordMetrics(BaseModel):
    """SEO scores for a single search query (without SERP videos)."""

    query: str
    volume: int = Field(ge=0, le=100)
    competition: int = Field(ge=0, le=100)
    score: float = Field(ge=0, le=100)


class ExplosiveChannelItem(BaseModel):
    """Explosive channel record returned by FR-5 API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    channel_id: str
    channel_name: str
    avatar_url: str = ""
    subscribers: int = Field(ge=0)
    channel_age_days: int = Field(ge=0)
    total_views: int = Field(ge=0)
    viral_coefficient: float = Field(ge=0)
    video_id: str = Field(default="", validation_alias="representative_video_id")
    representative_video_title: str = ""
    representative_video_thumbnail: str = ""
    representative_video_views: int = Field(ge=0)
    vph: float | None = Field(default=None, ge=0)
    updated_at: datetime


class TargetKeywordCreate(BaseModel):
    """Payload for adding a keyword to the radar scan queue."""

    keyword: str = Field(min_length=1, max_length=256)


class TargetKeywordItem(BaseModel):
    """Keyword queued for background explosive-channel scanning."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    keyword: str
    created_at: datetime


class ForceRadarScanResponse(BaseModel):
    """Result of a manual explosive-channels radar scan."""

    status: str = "ok"
    message: str = "Радар выполнил принудительный поиск"


class RadarStatusResponse(BaseModel):
    """Current explosive-channels radar loop state."""

    is_running: bool
    upload_period: str = "all"


class RadarToggleRequest(BaseModel):
    """Optional radar settings sent when toggling the loop."""

    upload_period: Literal["all", "month", "3_months", "6_months", "year"] | None = None
    search_query: str | None = Field(
        default=None,
        max_length=256,
        description="Manual one-shot keyword; empty means standard queue cycle",
    )
    blacklist_words: list[str] | None = Field(
        default=None,
        description="Minus-words: skip videos whose title contains any of these",
    )

    @field_validator("blacklist_words", mode="before")
    @classmethod
    def normalize_blacklist_words(cls, value: object) -> list[str] | None:
        if value is None:
            return None
        if isinstance(value, str):
            parts = [part.strip() for part in value.split(",") if part.strip()]
            return parts or None
        if isinstance(value, list):
            parts = [str(part).strip() for part in value if str(part).strip()]
            return parts or None
        return None


class RadarGenerateIdeasRequest(BaseModel):
    """Video titles used as context for Gemini title ideation."""

    video_titles: list[str] = Field(min_length=1, max_length=50)


class RadarGenerateIdeasResponse(BaseModel):
    """AI-generated clickable video title ideas."""

    ideas: list[str] = Field(default_factory=list)


class RadarSettingsUpdate(BaseModel):
    """Persist radar scan settings without toggling power state."""

    upload_period: Literal["all", "month", "3_months", "6_months", "year"]


class ClearExplosiveChannelsResponse(BaseModel):
    """Result of clearing the explosive channels database."""

    status: str = "ok"
    message: str = "База очищена"


class RadarStatsResponse(BaseModel):
    """Background radar keyword queue statistics."""

    total_keywords: int = Field(ge=0)
    checked_today: int = Field(ge=0)


class RadarResetResponse(BaseModel):
    """Result of resetting the radar keyword queue to the beginning."""

    status: str = "ok"
    message: str = (
        "Очередь радара сброшена — следующий цикл начнётся с первого ключевого слова"
    )
    total_keywords: int = Field(ge=0)


class SavedKeywordCreate(BaseModel):
    """Payload for saving or updating a keyword."""

    keyword: str = Field(min_length=1, max_length=256)
    volume: int = Field(ge=0, le=100)
    competition: int = Field(ge=0, le=100)
    score: float = Field(ge=0, le=100)
    category: str = Field(default="", max_length=128)


class SavedKeywordItem(BaseModel):
    """Persisted keyword with SEO scores."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    keyword: str
    volume: int = Field(ge=0, le=100)
    competition: int = Field(ge=0, le=100)
    score: float = Field(ge=0, le=100)
    category: str = ""

