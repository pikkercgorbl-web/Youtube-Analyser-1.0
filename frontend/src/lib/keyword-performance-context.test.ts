import { describe, expect, it } from "vitest";

import {
  attributionEquivalenceExplanation,
  formatKeywordPerformancePeriod,
  keywordDetailLeadSummary,
  keywordPerformanceListContextLines,
} from "@/lib/keyword-performance-context";
import type { KeywordPerformanceMetrics } from "@/lib/keyword-performance-types";

describe("keywordPerformanceListContextLines", () => {
  it("describes cumulative snapshot period and refresh time", () => {
    const lines = keywordPerformanceListContextLines({
      data_source: "snapshot",
      evaluated_at: "2026-10-19T18:54:06Z",
      window_from: null,
      window_to: null,
      ranking_version: "breakout_v1",
      attribution_mode: "all_hits",
    });
    expect(lines[0]).toMatch(/накопительно за всё время/i);
    expect(lines[0]).toMatch(/обновлено/i);
    expect(lines.join(" ")).toMatch(/предрасчётный снимок/i);
  });

  it("surfaces unavailable snapshot", () => {
    const lines = keywordPerformanceListContextLines({
      data_source: "unavailable",
      evaluated_at: null,
      window_from: null,
      window_to: null,
      ranking_version: null,
      attribution_mode: "all_hits",
    });
    expect(lines[0]).toMatch(/недоступны/i);
  });
});

describe("formatKeywordPerformancePeriod", () => {
  it("formats explicit window", () => {
    expect(
      formatKeywordPerformancePeriod("2026-01-01T00:00:00Z", "2026-01-31T00:00:00Z"),
    ).toMatch(/период/i);
  });
});

describe("keywordDetailLeadSummary", () => {
  it("uses human phrasing without raw id", () => {
    const metrics = {
      keyword_id: 99,
      scan_count: 2,
      attributed_video_count: 5,
      unique_video_count: 7,
      attribution_mode: "first_discovery",
      evidence_status: "early",
      last_scan_at: "2026-10-19T12:00:00Z",
    } as KeywordPerformanceMetrics;
    const lead = keywordDetailLeadSummary(metrics);
    expect(lead).not.toMatch(/keyword_id/i);
    expect(lead).toMatch(/5 видео/i);
    expect(lead).toMatch(/первый источник/i);
  });
});

describe("attributionEquivalenceExplanation", () => {
  it("explains identical counts when no shared videos", () => {
    const note = attributionEquivalenceExplanation({
      attribution_mode: "first_discovery",
      shared_video_count: 0,
      attributed_video_count: 10,
      unique_video_count: 10,
    } as KeywordPerformanceMetrics);
    expect(note).toMatch(/одинаковые числа/i);
  });
});
