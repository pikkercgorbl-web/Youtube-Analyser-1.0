import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DailyIntelligenceDashboard } from "./daily-intelligence-dashboard";

const listDailyIntelligenceDates = vi.fn();
const getDailyIntelligenceReport = vi.fn();
const listDailyIntelligenceWinners = vi.fn();
const listDailyIntelligenceFamilies = vi.fn();
const listDailyIntelligenceRuns = vi.fn();
const getDailyIntelligenceOutcomeCoverage = vi.fn();

const replaceMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock }),
  useSearchParams: () => new URLSearchParams(""),
}));

vi.mock("@/lib/api", () => ({
  listDailyIntelligenceDates: (...args: unknown[]) => listDailyIntelligenceDates(...args),
  getDailyIntelligenceReport: (...args: unknown[]) => getDailyIntelligenceReport(...args),
  listDailyIntelligenceWinners: (...args: unknown[]) => listDailyIntelligenceWinners(...args),
  listDailyIntelligenceFamilies: (...args: unknown[]) => listDailyIntelligenceFamilies(...args),
  listDailyIntelligenceRuns: (...args: unknown[]) => listDailyIntelligenceRuns(...args),
  getDailyIntelligenceOutcomeCoverage: (...args: unknown[]) =>
    getDailyIntelligenceOutcomeCoverage(...args),
}));

const reportSummary = {
  report_date: "2026-10-10",
  status: "provisional",
  source_run_id: "attention_20261010T140809Z",
  source_computed_at: "2026-10-10T14:08:09+00:00",
  source_window_start: "2026-10-09T14:08:09+00:00",
  source_window_end: "2026-10-10T14:08:09+00:00",
  source_window_hours: 24,
  generated_at: "2026-10-10T14:08:10+00:00",
  locked_at: null,
  publish_attempt: 2,
  winner_count: 50,
  family_count: 20,
  coverage_gaps: [],
  summary: {},
};

describe("DailyIntelligenceDashboard", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  beforeEach(() => {
    getDailyIntelligenceOutcomeCoverage.mockResolvedValue({
      report_date: "2026-10-10",
      edition_signal_source_computed_at: "2026-10-10T14:08:09+00:00",
      reference_evaluated_at: "2026-10-12T00:00:00+00:00",
      winner_count: 50,
      coverage_counts: { MEASURED_POST_SIGNAL: 18 },
      coverage_by_category: { MEASURED_POST_SIGNAL: 18, NOT_MATURED: 32 },
      items: [
        {
          video_id: "abcdefghij1",
          rank: 1,
          coverage_category: "MEASURED_POST_SIGNAL",
          outcome_window_phase: "closed",
        },
      ],
    });
    listDailyIntelligenceWinners.mockResolvedValue({
      items: [
        {
          video_id: "abcdefghij1",
          rank: 1,
          title: "Test Video",
          channel_id: "ch1",
          channel_title: "Channel",
          youtube_url: "https://www.youtube.com/watch?v=abcdefghij1",
          is_repeat_in_prior_reports: false,
          discovery_provenance_available: true,
          reason_summary: "Сильный результат среди видео окна анализа",
        },
      ],
      total: 50,
      limit: 25,
      offset: 0,
    });
    listDailyIntelligenceFamilies.mockResolvedValue({
      items: [],
      total: 20,
      limit: 25,
      offset: 0,
    });
    listDailyIntelligenceRuns.mockResolvedValue({
      items: [
        {
          source_run_id: "attention_20261010T125919Z",
          source_computed_at: "2026-10-10T12:59:19+00:00",
          captured_at: "2026-10-10T12:59:20+00:00",
          winner_count: 50,
          family_count: 20,
        },
        {
          source_run_id: "attention_20261010T140809Z",
          source_computed_at: "2026-10-10T14:08:09+00:00",
          captured_at: "2026-10-10T14:08:10+00:00",
          winner_count: 50,
          family_count: 20,
        },
      ],
      total: 2,
      limit: 25,
      offset: 0,
    });
  });

  it("shows empty state when no dates", async () => {
    listDailyIntelligenceDates.mockResolvedValue({ items: [], total: 0, limit: 200, offset: 0 });
    render(<DailyIntelligenceDashboard />);
    expect(await screen.findByText("Исторических отчётов пока нет")).toBeTruthy();
  });

  it("shows provisional report and totals without loading all rows", async () => {
    listDailyIntelligenceDates.mockResolvedValue({
      items: [{ ...reportSummary }],
      total: 1,
      limit: 200,
      offset: 0,
    });
    getDailyIntelligenceReport.mockResolvedValue(reportSummary);
    render(<DailyIntelligenceDashboard />);
    expect(await screen.findByText("Предварительный")).toBeTruthy();
    expect(await screen.findByTestId("di-report-header")).toBeTruthy();
    expect(await screen.findByTestId("di-report-header")).toHaveTextContent(/50 видео/);
    expect(await screen.findByText(/В выпуске: 20 тем/)).toBeTruthy();
    expect(listDailyIntelligenceWinners).toHaveBeenCalledWith("2026-10-10", { limit: 25, offset: 0 });
    expect(getDailyIntelligenceOutcomeCoverage).toHaveBeenCalledWith("2026-10-10");
    fireEvent.click(screen.getByRole("button", { name: "Данные и расчёт" }));
    expect(await screen.findByTestId("di-outcome-coverage-summary")).toBeTruthy();
    const thumb = document.querySelector('img[src*="i.ytimg.com/vi/abcdefghij1/mqdefault"]');
    expect(thumb).toBeTruthy();
    expect(await screen.findByTestId("di-winner-reason-summary")).toHaveTextContent(
      "Сильный результат среди видео",
    );
    expect(screen.getByText("№1 в выпуске")).toBeTruthy();
  });

  it("gracefully handles outcome coverage API failure", async () => {
    listDailyIntelligenceDates.mockResolvedValue({
      items: [{ ...reportSummary }],
      total: 1,
      limit: 200,
      offset: 0,
    });
    getDailyIntelligenceReport.mockResolvedValue(reportSummary);
    getDailyIntelligenceOutcomeCoverage.mockRejectedValue(new Error("coverage fail"));
    render(<DailyIntelligenceDashboard />);
    await screen.findByTestId("di-report-header");
    fireEvent.click(await screen.findByRole("button", { name: "Данные и расчёт" }));
    expect(await screen.findByTestId("di-outcome-coverage-error")).toBeTruthy();
  });

  it("shows run history entries", async () => {
    listDailyIntelligenceDates.mockResolvedValue({
      items: [{ ...reportSummary }],
      total: 1,
      limit: 200,
      offset: 0,
    });
    getDailyIntelligenceReport.mockResolvedValue(reportSummary);
    render(<DailyIntelligenceDashboard />);
    fireEvent.click(await screen.findByRole("button", { name: "Данные и расчёт" }));
    expect(await screen.findByText("attention_20261010T125919Z")).toBeTruthy();
    expect(screen.getAllByText("attention_20261010T140809Z").length).toBeGreaterThan(0);
  });

  it("handles API failure on dates", async () => {
    listDailyIntelligenceDates.mockRejectedValue(new Error("network fail"));
    render(<DailyIntelligenceDashboard />);
    expect(await screen.findByText(/network fail/)).toBeTruthy();
  });

  it("paginates winners", async () => {
    listDailyIntelligenceDates.mockResolvedValue({
      items: [{ ...reportSummary }],
      total: 1,
      limit: 200,
      offset: 0,
    });
    getDailyIntelligenceReport.mockResolvedValue(reportSummary);
    listDailyIntelligenceWinners
      .mockResolvedValueOnce({
        items: [],
        total: 50,
        limit: 25,
        offset: 0,
      })
      .mockResolvedValueOnce({
        items: [],
        total: 50,
        limit: 25,
        offset: 25,
      });
    render(<DailyIntelligenceDashboard />);
    await screen.findByText("Видео, на которые стоит посмотреть");
    await waitFor(() => expect(screen.getAllByRole("button", { name: "Вперёд" }).length).toBeGreaterThan(0));
    fireEvent.click(screen.getAllByRole("button", { name: "Вперёд" })[0]!);
    await waitFor(() =>
      expect(listDailyIntelligenceWinners).toHaveBeenCalledWith("2026-10-10", { limit: 25, offset: 25 }),
    );
  });
});
