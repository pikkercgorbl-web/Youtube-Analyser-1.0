export type ValidationReport = {
  period: { start: string | null; end: string | null };
  topics_saved_in_period: number;
  current_status_counts: Record<string, number>;
  status_transition_events: Record<string, number>;
  latest_finding_rating_distribution: Record<string, number>;
  topics_with_latest_feedback: number;
  topics_with_own_test_video_url: number;
  topics_with_known_own_test_outcome: number;
  latest_observation_presence: Record<string, number>;
  topics_with_comparable_count_deltas: number;
  frozen_support_source_breakdown: Record<string, number>;
  frozen_family_kind_breakdown: Record<string, number>;
  interpretation_notes: string[];
};
