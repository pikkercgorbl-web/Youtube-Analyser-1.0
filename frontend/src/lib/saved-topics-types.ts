export type SavedTopicStatus = "WATCHING" | "WANT_TO_TEST" | "TESTING" | "DROPPED";

export type SavedTopicObservation = {
  id: number;
  attention_run_id: string;
  captured_at: string;
  payload: Record<string, unknown>;
};

export type SavedTopicWatchMilestone = {
  kind: "saved" | "detected_again" | "not_detected";
  occurred_at: string;
  attention_run_id?: string | null;
};

export type SavedTopicWatchSummary = {
  headline: string;
  observation_count: number;
  saved_at: string;
  last_observation_at: string | null;
  last_present_at: string | null;
  last_absent_at: string | null;
  latest_attention_run_at: string | null;
  present_in_latest_snapshot: boolean | null;
  analysis_lifecycle:
    | "present_in_latest"
    | "absent_in_latest"
    | "no_new_attention_run"
    | "awaiting_first_follow_up"
    | "no_observations";
  stale_message: string | null;
  milestones: SavedTopicWatchMilestone[];
};

export type SavedTopicListItem = {
  id: number;
  family_key: string;
  label: string;
  status: SavedTopicStatus;
  notes: string;
  tags: string[];
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  latest_observation_at: string | null;
  present_in_latest_snapshot: boolean | null;
  watch_headline?: string | null;
  watch_stale_message?: string | null;
  analysis_lifecycle?: string | null;
  observation_count?: number;
};

export type FindingRating = "USEFUL" | "NOT_USEFUL" | "UNCLEAR";
export type OwnTestOutcome = "UNKNOWN" | "BETTER" | "AS_EXPECTED" | "WORSE";

export type SavedTopicFeedback = {
  id: number;
  recorded_at: string;
  finding_rating: FindingRating;
  reason_comment: string;
  own_test_video_url: string | null;
  own_test_video_published_at: string | null;
  own_test_outcome: OwnTestOutcome;
  manual_metrics: Record<string, unknown>;
};

export type SavedTopicDetail = {
  id: number;
  family_key: string;
  status: SavedTopicStatus;
  notes: string;
  tags: string[];
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  frozen_snapshot: Record<string, unknown>;
  live_observation: SavedTopicObservation | null;
  count_deltas: Record<string, number> | null;
  latest_feedback: SavedTopicFeedback | null;
  watch_summary?: SavedTopicWatchSummary | null;
};

export type SavedTopicTimelineItem = {
  kind: "observation" | "event";
  occurred_at: string;
  observation_id?: number;
  attention_run_id?: string;
  payload?: Record<string, unknown>;
  id?: number;
  event_type?: string;
};

export type SavedTopicTimelineResponse = {
  items: SavedTopicTimelineItem[];
  total: number;
  limit: number;
  offset: number;
};

export type SavedTopicFeedbackPayload = {
  finding_rating: FindingRating;
  reason_comment?: string;
  own_test_video_url?: string | null;
  own_test_video_published_at?: string | null;
  own_test_outcome?: OwnTestOutcome;
  manual_metrics?: {
    measured_at?: string | null;
    views?: number | null;
    vph?: number | null;
    notes?: string | null;
  } | null;
};

export type SavedTopicSaveResponse = {
  item: SavedTopicDetail;
  created: boolean;
  idempotent: boolean;
  archived_requires_restore?: boolean;
  message?: string | null;
};

export type SavedTopicListResponse = {
  items: SavedTopicListItem[];
  total: number;
};

export type SavedTopicHistoryResponse = {
  items: SavedTopicObservation[];
  total: number;
  limit: number;
  offset: number;
};

export type SavedTopicPatchPayload = {
  status?: SavedTopicStatus;
  notes?: string;
  tags?: string[];
};
