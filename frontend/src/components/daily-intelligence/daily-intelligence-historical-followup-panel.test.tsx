import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { DailyIntelligenceHistoricalFollowUpPanel } from "./daily-intelligence-historical-followup-panel";

const baseFollowUp = {
  report_date: "2026-10-10",
  video_id: "abcdefghij1",
  rank: 1,
  coverage_category: "MEASURED_POST_SIGNAL",
  coverage_reason: null,
  outcome_window_phase: "closed",
  signal_timestamps: {
    first_signal_source_computed_at: "2026-10-10T12:00:00+00:00",
    edition_signal_source_computed_at: "2026-10-10T14:08:09+00:00",
  },
  discovery_outcome_anchor: {
    discovered_at: "2026-10-07T10:00:00+00:00",
    outcome_window_target_at: "2026-10-10T10:00:00+00:00",
    outcome_window_start_at: "2026-10-09T22:00:00+00:00",
    outcome_window_end_at: "2026-10-10T22:00:00+00:00",
    horizon_hours: 72,
    tolerance_hours: 12,
  },
  outcome_measurement: {
    snapshot_captured_at: "2026-10-10T11:00:00+00:00",
    views_at_outcome_horizon: 5000,
  },
  attention_views_provenance: {
    frozen_attention_views: 1000,
    attention_views_source: "frozen_payload_unknown_source",
    candidate_baseline_snapshot_at: "2026-10-10T14:08:09+00:00",
    baseline_provenance_verified: false,
  },
  metrics_interpretation: "verified_post_signal_growth_unavailable",
  comparison_metrics: {
    views_at_attention_frozen: 1000,
    views_at_outcome_horizon: 5000,
    delta_views_descriptive: 4000,
    descriptive_growth_ratio: 5,
    verified_post_signal_growth: null,
    verified_post_signal_growth_ratio: null,
    elapsed_hours_edition_signal_to_outcome: 70,
    metrics_reason: null,
  },
  frozen_delayed_outcome: {
    delayed_outcome_state: "pending",
    delayed_outcome_growth: null,
  },
  reference_evaluated_at: "2026-10-12T12:00:00+00:00",
};

describe("DailyIntelligenceHistoricalFollowUpPanel", () => {
  afterEach(() => cleanup());

  it("shows unverified baseline warning and descriptive delta", async () => {
    render(
      <DailyIntelligenceHistoricalFollowUpPanel followUp={baseFollowUp} loading={false} error={null} />,
    );
    expect(screen.getByTestId("di-historical-followup")).toBeInTheDocument();
    expect(screen.getByText(/не доказано/)).toBeInTheDocument();
    expect(screen.getByText(/Возможный исходный snapshot/)).toBeInTheDocument();
    expect(screen.queryByText("Verified post-signal growth")).not.toBeInTheDocument();
  });

  it("shows pre-signal helper without verified growth", () => {
    render(
      <DailyIntelligenceHistoricalFollowUpPanel
        followUp={{
          ...baseFollowUp,
          coverage_category: "MEASURED_PRE_SIGNAL",
          metrics_interpretation: "pre_signal_outcome_only",
        }}
        loading={false}
        error={null}
      />,
    );
    expect(screen.getByText(/post-signal growth не показываем/)).toBeInTheDocument();
  });

  it("shows error state without blocking layout", () => {
    render(
      <DailyIntelligenceHistoricalFollowUpPanel followUp={null} loading={false} error="API down" />,
    );
    expect(screen.getByText(/Follow-up недоступен/)).toBeInTheDocument();
  });

  it("shows matured missing without success tone on verified growth", () => {
    render(
      <DailyIntelligenceHistoricalFollowUpPanel
        followUp={{
          ...baseFollowUp,
          coverage_category: "MATURED_MISSING",
          outcome_window_phase: "closed",
          outcome_measurement: { snapshot_captured_at: null },
          comparison_metrics: {
            ...baseFollowUp.comparison_metrics,
            views_at_outcome_horizon: null,
            delta_views_descriptive: null,
          },
        }}
        loading={false}
        error={null}
      />,
    );
    expect(screen.getAllByText(/закрыто, снимок не получен/).length).toBeGreaterThan(0);
    expect(screen.queryByText("Verified post-signal growth")).not.toBeInTheDocument();
  });
});
