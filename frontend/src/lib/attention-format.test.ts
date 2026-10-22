import { describe, expect, it } from "vitest";

import {
  claimsBreakoutWinner,
  confirmed72hCount,
  formatOptionalSubscribers,
  groupingSourceLabel,
  patternActivity,
  rewriteHumanReason,
  snapshotFreshnessLabel,
} from "@/lib/attention-format";
import { savedTopicAffordance } from "@/lib/saved-topics";

describe("attention format", () => {
  it("does not present breakout-eligible as winner", () => {
    const text = rewriteHumanReason("57 breakout-eligible videos");
    expect(text).toContain("подходят для анализа Breakout");
    expect(text.toLowerCase()).not.toContain("winner");
    expect(claimsBreakoutWinner(text)).toBe(false);
  });

  it("does not render unknown subscribers as 0", () => {
    expect(formatOptionalSubscribers(null)).toBeNull();
    expect(formatOptionalSubscribers(undefined)).toBeNull();
    expect(formatOptionalSubscribers(0)).toBeNull();
    expect(formatOptionalSubscribers(1200)).not.toBe("0");
  });

  it("labels grouping sources", () => {
    expect(groupingSourceLabel("title_phrase")).toContain("фраз");
    expect(groupingSourceLabel("keyword_provenance")).toContain("запрос");
    expect(groupingSourceLabel("video_topic")).toContain("тема");
  });

  it("renders activity windows without virality wording", () => {
    const activity = patternActivity({
      videos_previous_48_24h: 2,
      videos_previous_24h: 6,
      videos_last_24h: 14,
      first_seen_at: "2026-09-30T00:00:00Z",
      latest_seen_at: "2026-10-01T00:00:00Z",
    });
    expect(activity.label).toBe("2 → 6 → 14");
    expect(activity.label.toLowerCase()).not.toContain("вирус");
  });

  it("shows insufficient history when windows are empty", () => {
    const activity = patternActivity({
      videos_previous_48_24h: 0,
      videos_previous_24h: 0,
      videos_last_24h: 0,
      first_seen_at: null,
      latest_seen_at: null,
    });
    expect(activity.available).toBe(false);
    expect(activity.label).toBe("Недостаточно истории");
  });

  it("counts confirmed 72h from delayed_outcome_state", () => {
    expect(
      confirmed72hCount([
        { delayed_outcome_state: "confirmed" },
        { delayed_outcome_state: "pending" },
      ]),
    ).toBe(1);
  });

  it("describes snapshot freshness from computed_at", () => {
    const computed = "2026-10-01T12:00:00.000Z";
    const now = Date.parse("2026-10-01T12:12:00.000Z");
    expect(snapshotFreshnessLabel(computed, now)).toBe(
      "Обновлено 12 мин назад",
    );
  });
});

describe("saved topics hook", () => {
  it("does not fake persistence", () => {
    const affordance = savedTopicAffordance({
      familyKey: "family:phrase:abc",
      runId: "run-1",
    });
    expect(affordance.enabled).toBe(true);
    expect(affordance.hint).toContain("Сохранить");
  });
});
