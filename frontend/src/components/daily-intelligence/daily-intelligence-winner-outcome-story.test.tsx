import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { DailyIntelligenceWinnerOutcomeStory } from "./daily-intelligence-winner-outcome-story";

const baseFollowUp = {
  report_date: "2026-10-10",
  video_id: "v1",
  rank: 1,
  coverage_category: "MEASURED_POST_SIGNAL",
  coverage_reason: null,
  outcome_window_phase: "closed",
  signal_timestamps: {},
  discovery_outcome_anchor: {},
  outcome_measurement: {},
  attention_views_provenance: {
    frozen_attention_views: 1000,
    attention_views_source: "frozen_payload_unknown_source",
    candidate_baseline_snapshot_at: null,
    baseline_provenance_verified: false,
  },
  metrics_interpretation: "verified_post_signal_growth_unavailable",
  comparison_metrics: {
    views_at_attention_frozen: 1000,
    views_at_outcome_horizon: 2000,
    delta_views_descriptive: 1000,
    descriptive_growth_ratio: 2,
    verified_post_signal_growth: null,
    verified_post_signal_growth_ratio: null,
    elapsed_hours_edition_signal_to_outcome: 70,
    metrics_reason: null,
  },
  frozen_delayed_outcome: {},
  reference_evaluated_at: "2026-10-12T00:00:00+00:00",
};

describe("DailyIntelligenceWinnerOutcomeStory", () => {
  afterEach(() => cleanup());

  it("shows descriptive delta without verified growth label", () => {
    render(
      <DailyIntelligenceWinnerOutcomeStory followUp={baseFollowUp} loading={false} error={null} />,
    );
    expect(screen.getByText(/Разница \(описательно\)/)).toBeInTheDocument();
    expect(screen.getByText(/не подтверждено/)).toBeInTheDocument();
    expect(screen.queryByText("Verified post-signal growth")).not.toBeInTheDocument();
  });

  it("shows pending state for NOT_MATURED", () => {
    render(
      <DailyIntelligenceWinnerOutcomeStory
        followUp={{
          ...baseFollowUp,
          coverage_category: "NOT_MATURED",
          outcome_window_phase: "open_awaiting_measurement",
          comparison_metrics: {
            ...baseFollowUp.comparison_metrics,
            delta_views_descriptive: null,
            views_at_outcome_horizon: null,
          },
        }}
        loading={false}
        error={null}
      />,
    );
    expect(screen.getByText(/Ожидается контрольное измерение/)).toBeInTheDocument();
  });
});
