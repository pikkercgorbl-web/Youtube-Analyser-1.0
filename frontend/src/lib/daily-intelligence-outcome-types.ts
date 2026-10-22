export type OutcomeCoverageCategory =
  | "NOT_MATURED"
  | "MEASURED_POST_SIGNAL"
  | "MEASURED_PRE_SIGNAL"
  | "MATURED_MISSING"
  | "INVALID_TIMELINE"
  | "INSUFFICIENT_EVIDENCE";

export type OutcomeWindowPhase =
  | "not_yet_open"
  | "open_awaiting_measurement"
  | "closed"
  | "not_applicable";

export type AttentionViewsSource =
  | "verified_snapshot"
  | "frozen_payload_unknown_source"
  | "fallback_unknown";

export type DailyIntelligenceOutcomeCoverageItem = {
  video_id: string;
  rank: number;
  coverage_category: OutcomeCoverageCategory | string;
  outcome_window_phase: OutcomeWindowPhase | string;
  coverage_reason?: string | null;
};

export type DailyIntelligenceOutcomeCoverageResponse = {
  report_date: string;
  edition_signal_source_computed_at: string | null;
  reference_evaluated_at: string;
  winner_count: number;
  coverage_counts: Record<string, number>;
  coverage_by_category: Record<string, number>;
  items: DailyIntelligenceOutcomeCoverageItem[];
};

export type DailyIntelligenceAttentionViewsProvenance = {
  frozen_attention_views: number | null;
  attention_views_source: AttentionViewsSource | string;
  candidate_baseline_snapshot_at: string | null;
  baseline_provenance_verified: boolean;
};

export type DailyIntelligenceComparisonMetrics = {
  views_at_attention_frozen: number | null;
  views_at_outcome_horizon: number | null;
  delta_views_descriptive: number | null;
  descriptive_growth_ratio: number | null;
  verified_post_signal_growth: number | null;
  verified_post_signal_growth_ratio: number | null;
  elapsed_hours_edition_signal_to_outcome: number | null;
  metrics_reason: string | null;
};

export type DailyIntelligenceWinnerOutcomeFollowUp = {
  report_date: string;
  video_id: string;
  rank: number;
  coverage_category: OutcomeCoverageCategory | string;
  coverage_reason: string | null;
  outcome_window_phase: OutcomeWindowPhase | string;
  signal_timestamps: Record<string, unknown>;
  discovery_outcome_anchor: Record<string, unknown>;
  outcome_measurement: Record<string, unknown>;
  attention_views_provenance: DailyIntelligenceAttentionViewsProvenance;
  metrics_interpretation: string;
  comparison_metrics: DailyIntelligenceComparisonMetrics;
  frozen_delayed_outcome: Record<string, unknown>;
  reference_evaluated_at: string;
};
