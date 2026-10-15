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
