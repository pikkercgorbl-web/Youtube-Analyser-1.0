import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DailyIntelligenceFamilyDetailView } from "./daily-intelligence-family-detail-view";

const getDailyIntelligenceReport = vi.fn();
const getDailyIntelligenceFamily = vi.fn();

vi.mock("@/lib/api", () => ({
  getDailyIntelligenceReport: (...args: unknown[]) => getDailyIntelligenceReport(...args),
  getDailyIntelligenceFamily: (...args: unknown[]) => getDailyIntelligenceFamily(...args),
  listSavedFamilies: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  saveDailyIntelligenceFamilyToResearch: vi.fn(),
}));

const report = {
  report_date: "2026-10-10",
  status: "provisional",
  source_run_id: "run1",
  source_computed_at: "2026-10-10T14:08:09+00:00",
  source_window_start: null,
  source_window_end: null,
  source_window_hours: 24,
  generated_at: "2026-10-10T14:08:10+00:00",
  locked_at: null,
  publish_attempt: 1,
  winner_count: 0,
  family_count: 1,
  coverage_gaps: [],
  summary: {},
};

describe("DailyIntelligenceFamilyDetailView", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  beforeEach(() => {
    getDailyIntelligenceReport.mockResolvedValue(report);
  });

  it("renders family key and keyword_only disclaimer", async () => {
    getDailyIntelligenceFamily.mockResolvedValue({
      family_key: "keyword:99:topic",
      rank: 2,
      label: "Test Family",
      video_count: 5,
      channel_count: 3,
      is_repeat_in_prior_reports: false,
      evidence: {
        family_kind: "keyword_provenance",
        quality_flags: ["keyword_only"],
        video_ids: [],
      },
    });
    render(
      <DailyIntelligenceFamilyDetailView
        reportDate="2026-10-10"
        familyKey="keyword:99:topic"
      />,
    );
    await waitFor(() => {
      expect(screen.getByText("Test Family")).toBeInTheDocument();
    });
    expect(screen.getByTestId("di-family-key")).toHaveTextContent("keyword:99:topic");
    expect(screen.getByText(/не доказывает тренд/i)).toBeInTheDocument();
    expect(getDailyIntelligenceFamily).toHaveBeenCalledWith("2026-10-10", "keyword:99:topic");
  });

  it("shows error when family missing", async () => {
    getDailyIntelligenceFamily.mockRejectedValue(new Error("not found"));
    render(
      <DailyIntelligenceFamilyDetailView reportDate="2026-10-10" familyKey="missing" />,
    );
    await waitFor(() => {
      expect(screen.getByText("Family не найдена")).toBeInTheDocument();
    });
  });
});
