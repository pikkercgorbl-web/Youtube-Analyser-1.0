import { describe, expect, it } from "vitest";

import { buildValidationSummaryBlocks } from "./validation-presentation";
import type { ResearchPortfolioReport } from "./validation-types";

const basePortfolio = (obsPatch?: Partial<ResearchPortfolioReport["observations"]>): ResearchPortfolioReport => ({
  temporal_contracts: {},
  saved_in_period: {
    videos: 1,
    families: 1,
    legacy_topics: 0,
    research_combined: 2,
    combined_total: 2,
  },
  current_status_counts: {},
  decisions_in_period: {
    status_transition_events: {},
    status_changed_events: 0,
    events_by_type: {},
    total_events: 0,
  },
  latest_feedback: {
    research_verdict_distribution: {},
    cohort_with_latest_feedback: 0,
    cohort_without_latest_feedback: 2,
  },
  observations: {
    cohort_with_any_observation: 2,
    cohort_with_multiple_observations: 0,
    evidence_state_distribution: {},
    cohort_with_new_analytical_observation_in_period: 1,
    ...obsPatch,
  },
  pending_signals: {},
  saved_in_period_items: [],
  portfolio_hints: {
    has_saved_research: true,
    has_decisions_in_period: false,
    saved_without_decisions_message: null,
  },
  interpretation_notes: [],
});

describe("buildValidationSummaryBlocks", () => {
  it("uses backend new analytical observation count when period is set", () => {
    const blocks = buildValidationSummaryBlocks(basePortfolio(), {
      from: "2026-10-01",
      to: "2026-10-31",
    });
    expect(blocks.find((b) => b.id === "observations-in-period")?.value).toBe(1);
    expect(blocks.find((b) => b.id === "observations-in-period")?.title).toMatch(/новое наблюдение/);
  });

  it("falls back to cohort observation total without period", () => {
    const blocks = buildValidationSummaryBlocks(
      basePortfolio({ cohort_with_new_analytical_observation_in_period: null }),
      { from: "", to: "" },
    );
    expect(blocks.find((b) => b.id === "observations-any")?.value).toBe(2);
    expect(blocks.find((b) => b.id === "observations-in-period")).toBeUndefined();
  });
});
