import { describe, expect, it } from "vitest";

import {
  channelRelativeFromEvidence,
  familyHistoricalAnchorCounts,
  familyObservationPresenceLabel,
  familyObservationSourceLabel,
  formatChannelRelativeSummary,
  formatVphValue,
  observationSourceLabel,
  videoObservationAttentionLabel,
  youtubeWatchUrl,
} from "./saved-research-format";
import { DAILY_INTELLIGENCE_SAVE_ANCHOR_KIND } from "./saved-research-labels";

describe("saved-research-format", () => {
  it("builds canonical YouTube watch URL", () => {
    expect(youtubeWatchUrl("abc123")).toBe("https://www.youtube.com/watch?v=abc123");
  });

  it("formats VPH without duplicate suffix", () => {
    const v = formatVphValue(1200);
    expect(v).toBeTruthy();
    expect(v?.includes("VPH")).toBe(false);
  });

  it("parses channel relative from frozen evidence", () => {
    const rel = channelRelativeFromEvidence({
      channel_relative_signal: {
        status: "production_ready",
        baseline_quality: "production_ready",
        comparable_video_count: 5,
        vph_vs_channel_median: 2.1,
        notes: [],
      },
    });
    expect(rel?.status).toBe("production_ready");
    expect(formatChannelRelativeSummary(rel)).toContain("2.10×");
  });

  it("labels family daily intelligence anchor as historical save", () => {
    const payload = {
      observation_kind: DAILY_INTELLIGENCE_SAVE_ANCHOR_KIND,
      counts: { video_count: 3, channel_count: 2 },
      family: { video_count: 3, channel_count: 2 },
    };
    expect(familyObservationSourceLabel(payload)).toBe("Сохранено из исторического отчёта");
    expect(familyObservationPresenceLabel({ family_present: false, payload })).toBe(
      "Сохранено из исторического отчёта",
    );
    expect(familyObservationSourceLabel(payload)).not.toBe("Attention refresh");
    expect(familyHistoricalAnchorCounts(payload).video_count).toBe(3);
  });

  it("labels live family absence when not anchor", () => {
    expect(
      familyObservationPresenceLabel({ family_present: false, payload: { attention_run_id: "run1" } }),
    ).toContain("не в текущей выборке");
  });

  it("labels daily intelligence anchor without live absence wording", () => {
    const payload = {
      observation_kind: DAILY_INTELLIGENCE_SAVE_ANCHOR_KIND,
      present_in_daily_intelligence_edition: true,
    };
    expect(observationSourceLabel(payload)).toContain("Daily Intelligence");
    expect(
      videoObservationAttentionLabel({
        video_present_in_attention: false,
        payload,
      }),
    ).toContain("историческ");
  });

  it("shows unavailable baseline message", () => {
    expect(
      formatChannelRelativeSummary({
        status: "unavailable",
        baseline_quality: "none",
        comparable_video_count: 0,
        vph_vs_channel_median: null,
        notes: [],
      }),
    ).toContain("Недостаточно сопоставимой истории канала");
  });
});
