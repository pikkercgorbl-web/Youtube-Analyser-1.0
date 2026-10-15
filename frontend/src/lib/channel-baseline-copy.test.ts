import { describe, expect, it } from "vitest";

import { formatChannelBaselineExplanation } from "./channel-baseline-copy";

describe("channel-baseline-copy", () => {
  it("explains unavailable baseline as data limitation", () => {
    const copy = formatChannelBaselineExplanation({
      status: "unavailable",
      baseline_quality: "none",
      comparable_video_count: 0,
      vph_vs_channel_median: null,
      notes: ["v1 uses lookback-window VideoSnapshots only"],
    });
    expect(copy.dataTestId).toBe("baseline-unavailable");
    expect(copy.body).toMatch(/ограничение данных/i);
    expect(copy.body).not.toMatch(/плох/i);
  });

  it("explains available baseline with comparable count", () => {
    const copy = formatChannelBaselineExplanation({
      status: "production_ready",
      baseline_quality: "production_ready",
      comparable_video_count: 4,
      vph_vs_channel_median: 1.8,
      notes: [],
    });
    expect(copy.dataTestId).toBe("baseline-available");
    expect(copy.body).toMatch(/4 прошлых роликов/);
    expect(copy.body).toMatch(/1\.80×/);
  });
});
