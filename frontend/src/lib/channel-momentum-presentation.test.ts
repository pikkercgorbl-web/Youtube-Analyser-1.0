import { describe, expect, it } from "vitest";

import type { AttentionChannelMomentum } from "@/lib/attention-types";
import {
  buildChannelCalculationDetails,
  channelMomentumCategoryCounts,
  classifyChannelMomentum,
  channelMomentumHeadline,
  CHANNEL_MOMENTUM_MEDIAN_GROWTH_UI_RATIO,
  formatCategoryCountsSummary,
  pickEvidenceVideos,
} from "@/lib/channel-momentum-presentation";

function baseChannel(
  overrides: Partial<AttentionChannelMomentum> = {},
): AttentionChannelMomentum {
  return {
    channel_id: "UCtest",
    channel_title: "Test Channel",
    subscriber_count_latest: 10_000,
    observed_video_count: 10,
    recent_video_count: 4,
    previous_video_count: 6,
    breakout_video_count: 0,
    confirmed_72h_count: 0,
    recent_median_vph: 100,
    previous_median_vph: 80,
    recent_median_vph_vs_previous: 1.25,
    subscriber_growth_absolute: null,
    subscriber_growth_pct: null,
    subscriber_growth_available: false,
    first_observed_at: null,
    latest_observed_at: null,
    representative_video_ids: ["v1", "v2"],
    reason_codes: [],
    human_reasons: [],
    recent_window_days: 7,
    previous_window_days: 7,
    recent_measurable_count: 4,
    previous_measurable_count: 6,
    recent_improvement_count: 2,
    improvement_ratio_threshold: 1.5,
    previous_baseline_zero: false,
    incompleteness_notes: [],
    ...overrides,
  };
}

describe("classifyChannelMomentum", () => {
  it("uses UI median threshold, not backend improvement threshold", () => {
    expect(CHANNEL_MOMENTUM_MEDIAN_GROWTH_UI_RATIO).toBe(1.05);
    const atThreshold = baseChannel({
      recent_median_vph_vs_previous: 1.05,
      improvement_ratio_threshold: 1.5,
    });
    expect(classifyChannelMomentum(atThreshold)).toBe("confirmed_growth");
    expect(classifyChannelMomentum(baseChannel({ recent_median_vph_vs_previous: 1.04 }))).toBe(
      "strong_outliers",
    );
  });

  it("labels median ratio with improving videos as growth signal headline", () => {
    expect(classifyChannelMomentum(baseChannel({ recent_median_vph_vs_previous: 1.2 }))).toBe(
      "confirmed_growth",
    );
    expect(channelMomentumHeadline(baseChannel({ recent_median_vph_vs_previous: 1.2 })).title).toBe(
      "Есть сигнал роста",
    );
  });

  it("marks low median with improving videos as strong outliers", () => {
    const ch = baseChannel({ recent_median_vph_vs_previous: 0.61, recent_improvement_count: 2 });
    expect(classifyChannelMomentum(ch)).toBe("strong_outliers");
    expect(channelMomentumHeadline(ch).title).toBe("Отдельные сильные ролики");
  });

  it("marks zero baseline as insufficient", () => {
    expect(
      classifyChannelMomentum(
        baseChannel({ previous_baseline_zero: true, recent_improvement_count: 0 }),
      ),
    ).toBe("insufficient_data");
  });
});

describe("category summary alignment", () => {
  it("sums categories to channel count", () => {
    const channels = [
      baseChannel({ recent_median_vph_vs_previous: 2 }),
      baseChannel({ channel_id: "UC2", recent_median_vph_vs_previous: 0.8 }),
      baseChannel({
        channel_id: "UC3",
        previous_baseline_zero: true,
        recent_improvement_count: 0,
      }),
    ];
    const counts = channelMomentumCategoryCounts(channels);
    expect(counts.confirmed_growth + counts.strong_outliers + counts.insufficient_data).toBe(3);
    expect(formatCategoryCountsSummary(counts)).toContain("с сигналом роста");
  });
});

describe("pickEvidenceVideos", () => {
  it("uses API representative_videos with horizon VPH, not Winners", () => {
    const pick = pickEvidenceVideos(
      baseChannel({
        representative_video_ids: ["v1", "v2"],
        representative_videos: [
          {
            video_id: "v1",
            title: "From momentum evidence",
            youtube_url: "https://www.youtube.com/watch?v=v1",
            horizon_vph: 42,
            measured_at: "2026-10-01T12:00:00Z",
            actual_age_hours: 24.2,
            target_horizon_hours: 24,
            vs_previous_median_ratio: 2.1,
            meets_improvement_threshold: true,
            unavailable_reason: null,
            snapshot_row_id: 1,
            measurement_source: "attention_snapshot_frozen",
            attention_computed_at: null,
          },
          {
            video_id: "v2",
            title: "Missing snap",
            youtube_url: "https://www.youtube.com/watch?v=v2",
            horizon_vph: null,
            measured_at: null,
            actual_age_hours: null,
            target_horizon_hours: 24,
            vs_previous_median_ratio: null,
            meets_improvement_threshold: null,
            unavailable_reason: "no_snapshot_near_horizon",
            snapshot_row_id: null,
            measurement_source: "video_snapshot_replay_before_attention",
            attention_computed_at: "2026-10-01T12:00:00Z",
          },
        ],
      }),
      3,
    );
    expect(pick.videos).toHaveLength(1);
    expect(pick.videos[0].title).toBe("From momentum evidence");
    expect(pick.videos[0].metricCaption).toContain("42");
    expect(pick.missingFromWinnersCount).toBe(1);
  });
});

describe("buildChannelCalculationDetails", () => {
  it("dedupes incomplete history from human_reasons and notes", () => {
    const lines = buildChannelCalculationDetails(
      baseChannel({
        incompleteness_notes: ["2 recent eligible without snapshot"],
        human_reasons: [
          "Incomplete history: 2 recent eligible without snapshot",
          "2 recent videos at ~24h (±6.0h) each ≥ 1.5× previous median 10.0 VPH",
        ],
      }),
    );
    const incompleteLines = lines.filter((l) => l.includes("Неполная история"));
    expect(incompleteLines).toHaveLength(1);
  });
});
