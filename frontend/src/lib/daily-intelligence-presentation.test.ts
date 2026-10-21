import { describe, expect, it } from "vitest";

import {
  buildDiWinnerWhyInReport,
  buildReportDiscoverySummary,
  diWinnerListReasonSummary,
  formatReportAnalyzedPeriod,
} from "./daily-intelligence-presentation";
import type { DailyIntelligenceReportSummary } from "@/lib/daily-intelligence-types";

const report: DailyIntelligenceReportSummary = {
  report_date: "2026-10-10",
  status: "complete",
  source_run_id: "run",
  source_computed_at: "2026-10-10T14:00:00.000Z",
  source_window_start: "2026-10-09T14:00:00.000Z",
  source_window_end: "2026-10-10T14:00:00.000Z",
  source_window_hours: 24,
  generated_at: "2026-10-10T14:01:00.000Z",
  locked_at: null,
  publish_attempt: 1,
  winner_count: 50,
  family_count: 20,
  coverage_gaps: [],
  summary: {},
};

describe("daily intelligence presentation", () => {
  it("summarizes report without live metrics promise", () => {
    const text = buildReportDiscoverySummary(report);
    expect(text).toMatch(/50 видео/);
    expect(text).toMatch(/не текущие/);
  });

  it("formats analyzed window in UTC", () => {
    expect(formatReportAnalyzedPeriod(report)).toMatch(/UTC/);
  });

  it("falls back when reason_summary missing", () => {
    expect(diWinnerListReasonSummary(undefined)).toMatch(/не сохранена/);
  });

  it("uses frozen evidence for why block", () => {
    const block = buildDiWinnerWhyInReport(
      {
        reason_codes: ["breakout_high_rank"],
        breakout_rank: 3,
        human_reasons: ["breakout_v1 rank 3 in this attention window"],
      },
      3,
    );
    expect(block.short).toBe("Место №3");
    expect(block.detail).toMatch(/rank 3/);
  });
});
