export type UploadPeriod = "24h" | "week" | "month";

export interface ExtendedSearchVideoItem {
  video_id: string;
  title: string;
  views_count: number;
  likes_count: number;
  comments_count: number;
  published_at: string;
  duration_seconds: number;
  channel_id: string;
  channel_title: string;
  channel_subscribers_count: number;
  virality_percent: number;
}

export interface ExtendedSearchResponse {
  query: string;
  period: UploadPeriod;
  cached: boolean;
  cache_expires_at: string | null;
  total: number;
  limit: number;
  offset: number;
  items: ExtendedSearchVideoItem[];
}

export interface DimensionAggregate {
  dimension_type: string;
  dimension_value: string;
  video_count: number;
  total_views: number;
  avg_views: number;
  avg_vph: number;
  median_vph: number;
}

export interface MassAnalysisResponse {
  channels_requested: number;
  channels_found: number;
  channels_not_found: string[];
  total_videos_analyzed: number;
  channels: {
    channel_id: string;
    channel_title: string;
    videos_analyzed: number;
    total_views: number;
    avg_vph: number;
  }[];
  top_by_avg_views: DimensionAggregate[];
  top_by_avg_vph: DimensionAggregate[];
  top_by_total_views: DimensionAggregate[];
  by_format: DimensionAggregate[];
  by_topic: DimensionAggregate[];
  by_tag: DimensionAggregate[];
  by_title_keyword: DimensionAggregate[];
}

export type CompetitionLevel = "low" | "medium" | "high";

export interface KeywordAnalyzeResponse {
  keyword: string;
  opportunity_score: number;
  volume: {
    total_views: number;
    avg_views: number;
    median_views: number;
    tag_mention_rate: number;
    title_mention_rate: number;
    volume_score: number;
  };
  competition: {
    avg_channel_subscribers: number;
    median_channel_subscribers: number;
    mega_channel_count: number;
    small_channel_count: number;
    mega_channel_ratio: number;
    small_channel_ratio: number;
    competition_score: number;
    competition_level: CompetitionLevel;
  };
  similar_tags: { tag: string; frequency: number; relevance: number }[];
  top_results: {
    rank: number;
    video_id: string;
    title: string;
    views_count: number;
    channel_id: string;
    channel_title: string;
    channel_subscribers: number;
  }[];
  analyzed_videos: number;
  recommendation: string;
}

export interface YouTubeLeadersResponse {
  window_days: number;
  leaders: {
    channel_id: string;
    channel_title: string;
    topic: string | null;
    current_subscribers: number;
    current_total_views: number;
    subscribers_growth_pct: number;
    views_growth_pct: number;
    growth_score: number;
    snapshot_date: string;
  }[];
  channels_without_baseline: number;
}

export interface KeywordResearchVideoItem {
  rank: number;
  video_id: string;
  title: string;
  url: string;
  thumbnail_url: string;
  views_count: number;
  channel_title: string;
  channel_subscribers: number;
  virality_coefficient: number;
}

export interface KeywordResearchItem {
  keyword: string;
  volume: number;
  competition: number;
  score: number;
}

export interface KeywordResearchSuggestions {
  similar: KeywordResearchItem[];
  questions: KeywordResearchItem[];
  related: KeywordResearchItem[];
}

export interface KeywordResearchResponse {
  main_query: KeywordResearchItem;
  suggestions: KeywordResearchSuggestions;
}

export interface SavedKeywordItem {
  id: number;
  keyword: string;
  volume: number;
  competition: number;
  score: number;
  category: string;
}

export interface SavedKeywordPayload {
  keyword: string;
  volume: number;
  competition: number;
  score: number;
  category?: string;
}

export interface ExplosiveChannelItem {
  channel_id: string;
  channel_name: string;
  avatar_url: string;
  subscribers: number;
  channel_age_days: number;
  total_views: number;
  viral_coefficient: number;
  video_id: string;
  representative_video_title: string;
  representative_video_thumbnail: string;
  representative_video_views: number;
  updated_at: string;
}

export type ExplosiveChannelSortOption =
  | "viral_coefficient_desc"
  | "video_views_desc";

export interface ExplosiveChannelFilters {
  min_views?: number;
  min_viral_coeff?: number;
}

export interface ForceRadarScanResponse {
  status: string;
  message: string;
}

export type RadarUploadPeriod = "all" | "month" | "3_months" | "6_months" | "year";

export interface RadarStatusResponse {
  is_running: boolean;
  upload_period: RadarUploadPeriod;
}

export interface ClearExplosiveChannelsResponse {
  status: string;
  message: string;
}

export interface RadarStatsResponse {
  total_keywords: number;
  checked_today: number;
}

export interface AnomalySearchParams {
  q: string;
  period?: UploadPeriod;
  duration_min?: number;
  duration_max?: number;
  min_virality_percent?: number;
  limit?: number;
  offset?: number;
}

export interface EnrichedVideoModel {
  video: {
    video_id: string;
    channel_id?: string;
    channel_title?: string;
    title?: string;
    views_count?: number;
    published_text?: string;
    duration_text?: string;
    thumbnail_url?: string;
    channel_avatar_url?: string;
    is_short?: boolean;
  };
  channel: {
    subscribers_count?: number;
    total_videos?: number;
    total_views?: number;
    channel_age_days?: number;
    is_verified?: boolean;
    is_artist?: boolean;
    is_kids?: boolean;
    channel_avatar_url?: string;
  };
  virality_coefficient?: number;
}
