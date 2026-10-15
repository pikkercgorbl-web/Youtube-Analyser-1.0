import { describe, expect, it } from "vitest";

import { memberDisplayMetrics, memberMetricOrMissing } from "./family-member-metrics";

describe("family-member-metrics", () => {
  it("uses Нет измерения for missing views", () => {
    expect(
      memberMetricOrMissing(null, "missing_snapshot", "views"),
    ).toBe("Нет измерения");
  });

  it("formats winner snapshot views", () => {
    const m = memberDisplayMetrics({
      video_id: "x",
      title: "t",
      channel_id: "c",
      channel_title: "C",
      youtube_url: "https://www.youtube.com/watch?v=x",
      published_at: null,
      age_hours: 1,
      views: 500,
      vph: 50,
      subscribers: null,
      in_winner_snapshot: true,
      breakout_rank: 2,
      breakout_eligible: true,
      acceleration_state: null,
      delayed_outcome_state: null,
      delayed_outcome_growth: null,
      reason_codes: [],
      human_reasons: [],
      keyword_ids: [],
      views_measurement_status: "from_winner_snapshot",
    });
    expect(m.views).not.toBe("Нет измерения");
    expect(m.vph).toBeTruthy();
  });
});
