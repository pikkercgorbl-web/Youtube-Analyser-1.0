export type AttentionDataSource = "snapshot" | "live_compute" | "unavailable";

export type AttentionChannelRelativeSignal = {
  status: string;
  baseline_quality: string;
  comparable_video_count: number;
  vph_vs_channel_median: number | null;
  notes: string[];
};

export type AttentionVideoWinner = {
  video_id: string;
  title: string;
  channel_id: string;
  channel_title: string;
  youtube_url: string;
  published_at: string | null;
  age_hours: number | null;
  views: number | null;
  vph: number | null;
  subscribers: number | null;
  breakout_rank: number | null;
  breakout_eligible: boolean;
  channel_relative_signal: AttentionChannelRelativeSignal | null;
  acceleration_state: string;
  delayed_outcome_state: string;
  delayed_outcome_growth: number | null;
  reason_codes: string[];
  human_reasons: string[];
  keyword_ids: number[];
};

export type AttentionPattern = {
  pattern_key: string;
  kind: string;
  label: string;
  video_count: number;
  channel_count: number;
  keyword_count: number;
  breakout_video_count: number;
  small_channel_winner_count: number;
  first_seen_at: string | null;
  latest_seen_at: string | null;
  videos_last_24h: number;
  videos_previous_24h: number;
  videos_previous_48_24h: number;
  participating_video_ids: string[];
  participating_channel_ids: string[];
  participating_keyword_ids: number[];
  reason_codes: string[];
  human_reasons: string[];
};

export type AttentionChannelMomentum = {
  channel_id: string;
  channel_title: string;
  subscriber_count_latest: number | null;
  observed_video_count: number;
  recent_video_count: number;
  previous_video_count: number;
  breakout_video_count: number;
  confirmed_72h_count: number;
  recent_median_vph: number | null;
  previous_median_vph: number | null;
  recent_median_vph_vs_previous: number | null;
  subscriber_growth_absolute: number | null;
  subscriber_growth_pct: number | null;
  subscriber_growth_available: boolean;
  first_observed_at: string | null;
  latest_observed_at: string | null;
  representative_video_ids: string[];
  reason_codes: string[];
  human_reasons: string[];
  recent_window_days: number;
  previous_window_days: number;
  momentum_horizon_hours?: number;
  momentum_horizon_tolerance_hours?: number;
  recent_eligible_count?: number;
  previous_eligible_count?: number;
  recent_measurable_count?: number;
  previous_measurable_count?: number;
  recent_improvement_count?: number;
  improvement_ratio_threshold?: number;
  previous_baseline_zero?: boolean;
  incompleteness_notes?: string[];
};

export type AttentionSummary = {
  run_id: string | null;
  computed_at: string;
  timezone_name: string;
  window_hours: number;
  window_start: string;
  window_end: string;
  source: string;
  candidate_video_count: number;
  winner_count: number;
  pattern_count: number;
  channel_momentum_count: number;
  video_limit: number;
  pattern_limit: number;
  channel_limit: number;
  notes: Record<string, unknown>;
};

export type AttentionSummaryApiResponse = {
  summary: AttentionSummary | null;
  data_source: AttentionDataSource | string;
};

export type AttentionListMeta = {
  data_source: AttentionDataSource | string;
  run_id: string | null;
  computed_at: string | null;
  limit: number;
  offset: number;
  total: number;
};

export type AttentionVideoListResponse = AttentionListMeta & {
  items: AttentionVideoWinner[];
};

export type AttentionPatternListResponse = AttentionListMeta & {
  items: AttentionPattern[];
};

export type AttentionChannelListResponse = AttentionListMeta & {
  items: AttentionChannelMomentum[];
};

export type AttentionPatternMemberVideo = {
  video_id: string;
  title: string;
  channel_id: string;
  channel_title: string;
  youtube_url: string;
  published_at: string | null;
  age_hours: number | null;
  views: number | null;
  vph: number | null;
  subscribers: number | null;
  in_winner_snapshot: boolean;
  breakout_rank: number | null;
  breakout_eligible: boolean | null;
  acceleration_state: string | null;
  delayed_outcome_state: string | null;
  delayed_outcome_growth: number | null;
  reason_codes: string[];
  human_reasons: string[];
  keyword_ids: number[];
};

export type AttentionRelatedKeyword = {
  keyword_id: number;
  keyword: string;
};

export type AttentionParticipatingChannel = {
  channel_id: string;
  channel_title: string;
  video_count: number;
};

export type AttentionPatternDetailResponse = {
  pattern: AttentionPattern | null;
  data_source: AttentionDataSource | string;
  run_id: string | null;
  computed_at: string | null;
  videos: AttentionPatternMemberVideo[];
  related_keywords: AttentionRelatedKeyword[];
  channels: AttentionParticipatingChannel[];
};

export type AttentionPatternFamily = {
  family_key: string;
  label: string;
  family_kind: string;
  member_pattern_keys: string[];
  member_labels: string[];
  video_count: number;
  channel_count: number;
  keyword_count: number;
  breakout_eligible_count: number;
  videos_last_24h: number;
  videos_previous_24h: number;
  videos_previous_48_24h: number;
  grouping_reasons: string[];
  quality_flags: string[];
  support_sources: string[];
  first_seen_at: string | null;
  latest_seen_at: string | null;
  participating_video_ids: string[];
  participating_channel_ids: string[];
  participating_keyword_ids: number[];
};

export type AttentionPatternFamilyListResponse = AttentionListMeta & {
  items: AttentionPatternFamily[];
};

export type AttentionPatternFamilyDetailResponse = {
  family: AttentionPatternFamily | null;
  data_source: AttentionDataSource | string;
  run_id: string | null;
  computed_at: string | null;
  videos: AttentionPatternMemberVideo[];
  related_keywords: AttentionRelatedKeyword[];
  channels: AttentionParticipatingChannel[];
  member_patterns: AttentionPattern[];
};
