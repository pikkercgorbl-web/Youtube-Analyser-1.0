import { describe, expect, it } from "vitest";

import {
  formatOutcomeNullableDelta,
  formatOutcomeNullableViews,
  formatComparisonMetricsBlock,
} from "./daily-intelligence-outcome-format";

describe("daily-intelligence-outcome-format", () => {
  it("does not coerce null to zero", () => {
    expect(formatOutcomeNullableViews(null)).toBe("—");
    expect(formatOutcomeNullableDelta(undefined)).toBe("—");
  });

  it("formats descriptive metrics", () => {
    const block = formatComparisonMetricsBlock({
      views_at_attention_frozen: 1000,
      views_at_outcome_horizon: 2500,
      delta_views_descriptive: 1500,
      descriptive_growth_ratio: 2.5,
      verified_post_signal_growth: null,
      verified_post_signal_growth_ratio: null,
      elapsed_hours_edition_signal_to_outcome: 72,
      metrics_reason: null,
    });
    expect(block.deltaDescriptive).toMatch(/\+1[\s\u00a0]?500/);
    expect(block.verifiedGrowth).toBe("—");
  });
});
