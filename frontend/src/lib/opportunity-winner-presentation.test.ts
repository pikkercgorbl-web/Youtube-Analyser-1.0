import { describe, expect, it } from "vitest";

import type { AttentionVideoWinner } from "@/lib/attention-types";

import {
  buildVideoHighlightSnapshot,
  buildWinnerChannelBlock,
  buildWinnerInsightBlocks,
  buildWinnerNextBlock,
  buildWinnerWhyHereBlock,
  formatWinnerSnapshotContextLine,
  frozenVideoHighlightFromPayload,
  pickOpportunityVideoBadges,
  videoSignalInputFromWinner,
} from "./opportunity-winner-presentation";

function base(overrides: Partial<AttentionVideoWinner> = {}): AttentionVideoWinner {
  return {
    video_id: "v1",
    title: "Title",
    channel_id: "c1",
    channel_title: "Ch",
    youtube_url: "https://www.youtube.com/watch?v=v1",
    published_at: null,
    age_hours: 24,
    views: 1000,
    vph: 120,
    subscribers: 5000,
    breakout_rank: 2,
    breakout_eligible: true,
    channel_relative_signal: null,
    acceleration_state: "stable",
    delayed_outcome_state: "pending",
    delayed_outcome_growth: null,
    reason_codes: ["breakout_high_rank", "high_current_vph"],
    human_reasons: [],
    keyword_ids: [],
    ...overrides,
  };
}

describe("buildWinnerWhyHereBlock", () => {
  it("uses breakout rank when confirmed by code", () => {
    const block = buildWinnerWhyHereBlock(base());
    expect(block.short).toBe("Radar №2");
    expect(block.detail).toMatch(/VPH/);
  });
});

describe("buildWinnerChannelBlock", () => {
  it("hides ratio when only one comparable video", () => {
    const block = buildWinnerChannelBlock(
      base({
        channel_relative_signal: {
          status: "diagnostic",
          baseline_quality: "diagnostic",
          comparable_video_count: 1,
          vph_vs_channel_median: 3,
          notes: [],
        },
      }),
    );
    expect(block.short).toBe("Пока мало данных");
    expect(block.detail).toMatch(/1 сопоставимый/);
    expect(block.detail).not.toMatch(/3\.00×/);
  });

  it("shows production-ready ratio", () => {
    const block = buildWinnerChannelBlock(
      base({
        channel_relative_signal: {
          status: "production_ready",
          baseline_quality: "production_ready",
          comparable_video_count: 5,
          vph_vs_channel_median: 2.4,
          notes: [],
        },
      }),
    );
    expect(block.short).toBe("Сильнее нормы");
    expect(block.detail).toMatch(/2\.40×/);
  });
});

describe("buildWinnerNextBlock", () => {
  it("suggests dynamics when channel compare is weak", () => {
    const block = buildWinnerNextBlock(base({ channel_relative_signal: null }));
    expect(block.short).toBe("Динамика");
  });
});

describe("buildWinnerInsightBlocks", () => {
  it("returns three blocks", () => {
    expect(buildWinnerInsightBlocks(base())).toHaveLength(3);
  });
});

describe("buildVideoHighlightSnapshot", () => {
  it("formats high VPH with top quartile line", () => {
    const snap = buildVideoHighlightSnapshot(
      videoSignalInputFromWinner(
        base({
          vph: 1302.6,
          reason_codes: ["high_current_vph", "breakout_high_rank"],
          breakout_rank: 5,
        }),
      ),
    );
    expect(snap?.headline).toBe("Radar №5");
    expect(snap?.detail).toMatch(/просмотров\/час/);
    expect(snap?.detail).toMatch(/топ-25%/);
  });

  it("manual frozen payload without attention codes", () => {
    expect(
      frozenVideoHighlightFromPayload({
        evidence: { from_canonical_video: true, views: 100 },
      }).kind,
    ).toBe("manual");
  });
});

describe("pickOpportunityVideoBadges", () => {
  it("caps at two badges and skips eligibility-only codes", () => {
    const badges = pickOpportunityVideoBadges(
      base({
        reason_codes: ["breakout_high_rank", "high_current_vph", "accelerating_velocity"],
        acceleration_state: "accelerating",
        vph: 100,
      }),
    );
    expect(badges).toHaveLength(2);
    expect(badges[0]).toBe("Высокий темп");
    expect(badges).not.toContain("В подборке Radar");
  });
});

describe("formatWinnerSnapshotContextLine", () => {
  it("mentions snapshot time and window, not publish time", () => {
    const line = formatWinnerSnapshotContextLine({
      computedAt: "2026-10-12T12:00:00.000Z",
      windowHours: 24,
      windowStart: "2026-10-11T12:00:00.000Z",
      windowEnd: "2026-10-12T12:00:00.000Z",
    });
    expect(line).toMatch(/Снимок Attention/);
    expect(line).toMatch(/окно/i);
    expect(line).toMatch(/не по дате публикации/);
  });
});
