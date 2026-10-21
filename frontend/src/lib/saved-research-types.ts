import type { AttentionRelatedKeyword } from "./attention-types";
import type { SavedResearchAnalystVerdict } from "./saved-research-analyst-feedback-types";

export type SavedResearchStatus =
  | "WATCHING"
  | "WANT_TO_TEST"
  | "TESTING"
  | "DROPPED";

export type RelatedFamilyRef = {
  family_key: string;
  label: string;
};

export type SavedVideoListItem = {
  id: number;
  video_id: string;
  title: string;
  channel_title: string;
  status: SavedResearchStatus;
  notes: string;
  tags: string[];
  saved_at: string;
  updated_at: string;
  archived_at: string | null;
  latest_observed_at: string | null;
  in_current_attention: boolean | null;
  frozen_views: number | null;
  frozen_vph: number | null;
  current_views: number | null;
  current_vph: number | null;
  related_family_labels: string[];
  latest_analyst_verdict: SavedResearchAnalystVerdict | null;
  latest_analyst_verdict_at: string | null;
  latest_measurement_source: string | null;
};

export type SavedVideoObservation = {
  id: number;
  attention_run_id: string | null;
  observed_at: string;
  video_present_in_attention: boolean;
  monitoring_snapshot_available: boolean;
  views: number | null;
  vph: number | null;
  subscriber_count: number | null;
  breakout_rank: number | null;
  acceleration_state: string | null;
  delayed_outcome_state: string | null;
  family_memberships: RelatedFamilyRef[];
  payload: Record<string, unknown>;
};

export type SavedVideoHistoryResponse = {
  items: SavedVideoObservation[];
  total: number;
  limit: number;
  offset: number;
};

export type SavedFamilyObservation = {
  id: number;
  attention_run_id: string;
  observed_at: string;
  family_present: boolean;
  label: string | null;
  video_count: number | null;
  channel_count: number | null;
  keyword_count: number | null;
  payload: Record<string, unknown>;
  absence_message: string | null;
};

export type SavedFamilyHistoryResponse = {
  items: SavedFamilyObservation[];
  total: number;
  limit: number;
  offset: number;
};

export type SavedVideoManualRefreshResponse = {
  item: SavedVideoDetail;
  capture_run_id: string;
  measured_at: string;
  snapshot_id: number;
  metrics_source: string;
  idempotent: boolean;
  cooldown_seconds: number;
};

export type SavedVideoSimilarWatch = {
  saved_video_id: number;
  status: string;
  display_state: string;
  suggested_queries: string[];
  confirmed_queries: string[];
  confirmed_at: string | null;
  next_scan_at: string | null;
  last_scan_at: string | null;
  last_error: string | null;
  findings_count: number;
  load_estimate: Record<string, unknown>;
};

export type SavedVideoSimilarFinding = {
  id: number;
  video_id: string;
  title: string;
  channel_title: string;
  views_count: number | null;
  published_text: string | null;
  thumbnail_url: string | null;
  matched_query: string;
  last_found_at: string;
  youtube_url: string;
  relevance_score: number;
  relevance_tier: string;
  why_found: string | null;
  other_reason: string | null;
  user_verdict: "fit" | "not_fit" | null;
  saved_to_research: boolean;
};

export type SavedVideoSimilarFindingsList = {
  primary_items: SavedVideoSimilarFinding[];
  other_items: SavedVideoSimilarFinding[];
  primary_total: number;
  other_total: number;
  total: number;
};

export type SavedVideoDetail = {
  id: number;
  video_id: string;
  status: SavedResearchStatus;
  notes: string;
  tags: string[];
  saved_at: string;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  created_from_attention_run_id: string | null;
  frozen_snapshot: Record<string, unknown>;
  live_observation: SavedVideoObservation | null;
  metric_deltas: Record<string, number> | null;
  attention_absence_message: string | null;
  discovery_keywords?: AttentionRelatedKeyword[];
};

export type SavedFamilyListItem = {
  id: number;
  family_key: string;
  label: string;
  status: SavedResearchStatus;
  notes: string;
  tags: string[];
  saved_at: string;
  updated_at: string;
  archived_at: string | null;
  latest_observed_at: string | null;
  family_present: boolean | null;
  frozen_video_count: number | null;
  current_video_count: number | null;
  frozen_channel_count: number | null;
  current_channel_count: number | null;
  latest_analyst_verdict: SavedResearchAnalystVerdict | null;
  latest_analyst_verdict_at: string | null;
};

export type SavedFamilyTopicQuerySuggestionItem = {
  query: string;
  source_type: string;
  source_explanation: string;
  supporting_video_count: number | null;
};

export type SavedFamilyTopicDirection = {
  direction_id: string;
  label: string;
  explanation: string;
  suggestions: SavedFamilyTopicQuerySuggestionItem[];
};

export type SavedFamilyTopicWatch = {
  saved_family_id: number;
  status: string;
  display_state: string;
  suggested_queries: string[];
  suggested_query_items: SavedFamilyTopicQuerySuggestionItem[];
  suggestion_mode: string;
  suggestion_message: string | null;
  mixed_keyword_provenance: boolean;
  search_directions: SavedFamilyTopicDirection[];
  confirmed_queries: string[];
  confirmed_at: string | null;
  next_scan_at: string | null;
  last_scan_at: string | null;
  last_error: string | null;
  findings_count: number;
  load_estimate: Record<string, unknown>;
  topic_label: string;
  anchor_label: string;
};

export type SavedFamilyTopicFinding = {
  id: number;
  video_id: string;
  title: string;
  channel_title: string;
  views_count: number | null;
  published_text: string | null;
  thumbnail_url: string | null;
  matched_query: string;
  last_found_at: string;
  youtube_url: string;
  saved_to_research: boolean;
};

export type SavedFamilyTopicFindingsList = {
  items: SavedFamilyTopicFinding[];
  total: number;
  limit: number;
  offset: number;
  hits_by_query: Record<string, number>;
  confirmed_queries: string[];
};

export type SavedFamilyDetail = {
  id: number;
  family_key: string;
  label: string;
  status: SavedResearchStatus;
  notes: string;
  tags: string[];
  saved_at: string;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  created_from_attention_run_id: string | null;
  frozen_snapshot: Record<string, unknown>;
  live_observation: SavedFamilyObservation | null;
  count_deltas: Record<string, number> | null;
  absence_message: string | null;
};
