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
  videos: {
    channel_name: string;
    channel_url: string;
    channel_avatar: string;
    video_title: string;
    video_url: string;
    views: number;
    channel_average_views: number;
    outlier_score: number;
    published_at: string;
  }[];
}

export interface ChannelSingleAnalysisPublication {
  video_id: string;
  channel_id?: string | null;
  title: string;
  thumbnail_url: string;
  views_count: number;
  published_text: string;
  duration_text: string;
  url: string;
  kind: string;
  published_at: string | null;
  duration_seconds: number | null;
  in_feed: boolean;
}

export interface ChannelSingleAgePeerSample {
  video_id: string;
  title: string;
  thumbnail_url: string;
  views_count: number;
  age_hours: number;
}

export interface ChannelSingleFocusComparison {
  status: string;
  multiplier: number | null;
  peer_count: number;
  median_views: number | null;
  focus_views: number | null;
  focus_age_hours: number | null;
  peer_age_min_hours: number | null;
  peer_age_max_hours: number | null;
  searched_age_low_hours: number | null;
  searched_age_high_hours: number | null;
  age_peer_samples: ChannelSingleAgePeerSample[];
  message: string;
  disclaimer: string;
}

export interface ChannelSingleAnalysisShelfMoreResponse {
  channel_id: string;
  new_publications: ChannelSingleAnalysisPublication[];
  feed_loaded_count: number;
  has_more: boolean;
  pagination_note: string;
  fetched_at: string;
}

export interface ChannelSingleAnalysisShelfResponse {
  channel_id: string;
  channel_title: string;
  subscribers_count: number | null;
  channel_avatar_url: string;
  feed_loaded_count: number;
  publications: ChannelSingleAnalysisPublication[];
  fetched_at: string;
}

export interface ChannelSingleAnalysisEnrichResponse {
  channel_id: string;
  publications: ChannelSingleAnalysisPublication[];
  regular_confirmed_count: number;
  focus: ChannelSingleAnalysisPublication | null;
  focus_loaded_separately: boolean;
  comparison: ChannelSingleFocusComparison;
  enrichment_error: string | null;
}

export interface ChannelSingleCompareResponse {
  comparison: ChannelSingleFocusComparison;
  focus: ChannelSingleAnalysisPublication | null;
  focus_loaded_separately: boolean;
  enrichment_error: string | null;
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
  vph?: number | null;
  updated_at: string;
}

export type ExplosiveChannelSortOption =
  | "viral_coefficient_desc"
  | "video_views_desc"
  | "vph_desc";

export interface ExplosiveChannelFilters {
  min_views?: number;
  min_viral_coeff?: number;
}

export interface ForceRadarScanResponse {
  status: string;
  message: string;
}

export type RadarUploadPeriod = "all" | "month" | "3_months" | "6_months" | "year";

export type RadarWorkerStatus = "idle" | "running" | "stopped";

export interface RadarContentFormatOptions {
  exclude_streams?: boolean;
  exclude_shorts?: boolean;
  exclude_videos?: boolean;
}

export interface RadarStatusResponse {
  is_running: boolean;
  upload_period: RadarUploadPeriod;
  worker_status: RadarWorkerStatus;
}

export interface ClearExplosiveChannelsResponse {
  status: string;
  message: string;
}

export interface RadarStatsResponse {
  total_keywords: number;
  checked_today: number;
}

export interface RadarResetResponse {
  status: string;
  message: string;
  total_keywords: number;
}

export interface RadarGenerateIdeasResponse {
  ideas: string[];
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
    subscribers_count?: number;
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
