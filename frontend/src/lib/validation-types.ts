export type ResearchPortfolioSavedInPeriod = {
  videos: number;
  families: number;
  legacy_topics: number;
  research_combined: number;
  combined_total: number;
};

export type ResearchPortfolioSavedItem = {
  kind: "video" | "family";
  id: number;
  title: string;
  saved_at: string;
  current_status: string;
  has_latest_feedback: boolean;
  observation_count: number;
};

export type ResearchPortfolioReport = {
  temporal_contracts: Record<string, string>;
  saved_in_period: ResearchPortfolioSavedInPeriod;
  current_status_counts: Record<string, number>;
  decisions_in_period: {
    status_transition_events: Record<string, number>;
    status_changed_events: number;
    events_by_type: Record<string, number>;
    total_events: number;
  };
  latest_feedback: {
    research_verdict_distribution: Record<string, number>;
    cohort_with_latest_feedback: number;
    cohort_without_latest_feedback: number;
  };
  observations: {
    cohort_with_any_observation: number;
    cohort_with_multiple_observations: number;
    evidence_state_distribution: Record<string, number>;
  };
  pending_signals: Record<string, number>;
  saved_in_period_items: ResearchPortfolioSavedItem[];
  portfolio_hints: {
    has_saved_research: boolean;
    has_decisions_in_period: boolean;
    saved_without_decisions_message: string | null;
  };
  interpretation_notes: string[];
};

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
  research_portfolio: ResearchPortfolioReport;
};
