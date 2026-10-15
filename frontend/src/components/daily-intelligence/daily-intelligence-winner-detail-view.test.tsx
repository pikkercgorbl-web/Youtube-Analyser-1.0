import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DailyIntelligenceWinnerDetailView } from "./daily-intelligence-winner-detail-view";

const getDailyIntelligenceReport = vi.fn();
const getDailyIntelligenceWinner = vi.fn();
const listDailyIntelligenceVideoAppearances = vi.fn();
const getDailyIntelligenceWinnerOutcomeFollowUp = vi.fn();

vi.mock("@/lib/api", () => ({
  getDailyIntelligenceReport: (...args: unknown[]) => getDailyIntelligenceReport(...args),
  getDailyIntelligenceWinner: (...args: unknown[]) => getDailyIntelligenceWinner(...args),
  listDailyIntelligenceVideoAppearances: (...args: unknown[]) =>
    listDailyIntelligenceVideoAppearances(...args),
  getDailyIntelligenceWinnerOutcomeFollowUp: (...args: unknown[]) =>
    getDailyIntelligenceWinnerOutcomeFollowUp(...args),
  listSavedVideos: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  saveDailyIntelligenceVideoToResearch: vi.fn(),
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
  winner_count: 1,
  family_count: 0,
  coverage_gaps: [],
  summary: {},
};

const winnerDetail = {
  video_id: "abcdefghij1",
  rank: 3,
  title: "Historical Winner",
  channel_id: "ch",
  channel_title: "Channel",
  youtube_url: "https://www.youtube.com/watch?v=abcdefghij1",
  is_repeat_in_prior_reports: false,
  discovery_provenance_available: true,
  discovery_provenance: { available: true, keyword_id: 1 },
  evidence: {
    human_reasons: ["Test reason"],
    acceleration_state: "accelerating",
  },
};

describe("DailyIntelligenceWinnerDetailView", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  beforeEach(() => {
    getDailyIntelligenceReport.mockResolvedValue(report);
    getDailyIntelligenceWinner.mockResolvedValue(winnerDetail);
    getDailyIntelligenceWinnerOutcomeFollowUp.mockResolvedValue({
      report_date: "2026-10-10",
      video_id: "abcdefghij1",
      rank: 3,
      coverage_category: "NOT_MATURED",
      coverage_reason: null,
      outcome_window_phase: "open_awaiting_measurement",
      signal_timestamps: {},
      discovery_outcome_anchor: { horizon_hours: 72, tolerance_hours: 12 },
      outcome_measurement: {},
      attention_views_provenance: {
        frozen_attention_views: null,
        attention_views_source: "fallback_unknown",
        candidate_baseline_snapshot_at: null,
        baseline_provenance_verified: false,
      },
      metrics_interpretation: "insufficient_attention_baseline",
      comparison_metrics: {
        views_at_attention_frozen: null,
        views_at_outcome_horizon: null,
        delta_views_descriptive: null,
        descriptive_growth_ratio: null,
        verified_post_signal_growth: null,
        verified_post_signal_growth_ratio: null,
        elapsed_hours_edition_signal_to_outcome: null,
        metrics_reason: null,
      },
      frozen_delayed_outcome: {},
      reference_evaluated_at: "2026-10-12T00:00:00+00:00",
    });
    listDailyIntelligenceVideoAppearances.mockResolvedValue({
      items: [
        {
          source_run_id: "attention_run",
          report_date: "2026-10-10",
          source_computed_at: "2026-10-10T12:00:00+00:00",
          rank: 5,
          video_id: "abcdefghij1",
          title: "Historical Winner",
          discovery_provenance: { available: false },
        },
      ],
      total: 15,
      limit: 10,
      offset: 0,
    });
  });

  it("loads frozen winner without live attention API", async () => {
    render(<DailyIntelligenceWinnerDetailView reportDate="2026-10-10" videoId="abcdefghij1" />);
    await waitFor(() => {
      expect(screen.getByText("Historical Winner")).toBeInTheDocument();
    });
    expect(getDailyIntelligenceWinner).toHaveBeenCalledWith("2026-10-10", "abcdefghij1");
    expect(getDailyIntelligenceReport).toHaveBeenCalledWith("2026-10-10");
  });

  it("shows Нет данных for missing metric fields", async () => {
    render(<DailyIntelligenceWinnerDetailView reportDate="2026-10-10" videoId="abcdefghij1" />);
    await waitFor(() => {
      expect(screen.getAllByText("Нет данных").length).toBeGreaterThan(0);
    });
  });

  it("paginates appearances", async () => {
    listDailyIntelligenceVideoAppearances.mockResolvedValueOnce({
      items: [],
      total: 15,
      limit: 10,
      offset: 0,
    });
    render(<DailyIntelligenceWinnerDetailView reportDate="2026-10-10" videoId="abcdefghij1" />);
    await waitFor(() => {
      expect(screen.getByTestId("di-toggle-all-appearances")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("di-toggle-all-appearances"));
    await waitFor(() => {
      expect(screen.getByText("Вперёд")).toBeInTheDocument();
    });
    listDailyIntelligenceVideoAppearances.mockResolvedValueOnce({
      items: [],
      total: 15,
      limit: 10,
      offset: 10,
    });
    fireEvent.click(screen.getByText("Вперёд"));
    await waitFor(() => {
      expect(listDailyIntelligenceVideoAppearances).toHaveBeenLastCalledWith("abcdefghij1", {
        limit: 10,
        offset: 10,
      });
    });
  });

  it("shows error state on API failure", async () => {
    getDailyIntelligenceWinner.mockRejectedValue(new Error("404"));
    render(<DailyIntelligenceWinnerDetailView reportDate="2026-10-10" videoId="bad" />);
    await waitFor(() => {
      expect(screen.getByText("Видео не найдено")).toBeInTheDocument();
    });
  });

  it("keeps historical detail when follow-up API fails", async () => {
    getDailyIntelligenceWinnerOutcomeFollowUp.mockRejectedValue(new Error("follow-up down"));
    render(<DailyIntelligenceWinnerDetailView reportDate="2026-10-10" videoId="abcdefghij1" />);
    await waitFor(() => {
      expect(screen.getByText("Historical Winner")).toBeInTheDocument();
    });
    expect(await screen.findByText(/контрольного измерения недоступен/i)).toBeInTheDocument();
  });

  it("renders research sections and hides full appearances by default", async () => {
    render(<DailyIntelligenceWinnerDetailView reportDate="2026-10-10" videoId="abcdefghij1" />);
    await waitFor(() => {
      expect(screen.getByTestId("di-winner-hero")).toBeInTheDocument();
    });
    expect(screen.getByText("Почему Radar выделил видео")).toBeInTheDocument();
    expect(screen.getByText("Что произошло дальше")).toBeInTheDocument();
    expect(screen.queryByTestId("di-appearance-table")).not.toBeInTheDocument();
  });
});
