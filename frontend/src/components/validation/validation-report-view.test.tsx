import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ValidationReportView } from "./validation-report-view";

vi.mock("@/lib/api", () => ({
  getValidationReport: vi.fn(),
}));

import { getValidationReport } from "@/lib/api";

const basePortfolio = {
  temporal_contracts: {},
  saved_in_period: {
    videos: 1,
    families: 2,
    legacy_topics: 0,
    research_combined: 3,
    combined_total: 3,
  },
  current_status_counts: { WATCHING: 2, TESTING: 1 },
  decisions_in_period: {
    status_transition_events: { to_TESTING: 0, to_WANT_TO_TEST: 0, to_DROPPED: 0, to_WATCHING: 0 },
    status_changed_events: 0,
    events_by_type: {},
    total_events: 0,
  },
  latest_feedback: {
    research_verdict_distribution: {},
    cohort_with_latest_feedback: 0,
    cohort_without_latest_feedback: 3,
  },
  observations: {
    cohort_with_any_observation: 3,
    cohort_with_multiple_observations: 0,
    evidence_state_distribution: { pending: 3, validated: 0, insufficient: 0 },
  },
  pending_signals: {
    cohort_still_watching: 2,
    cohort_want_to_test: 0,
    cohort_in_testing: 1,
    cohort_dropped: 0,
    cohort_without_feedback: 3,
    cohort_single_observation_only: 3,
  },
  saved_in_period_items: [
    {
      kind: "video" as const,
      id: 1,
      title: "Test video",
      saved_at: "2026-10-01T12:00:00+00:00",
      current_status: "WATCHING",
      has_latest_feedback: false,
      observation_count: 1,
    },
  ],
  portfolio_hints: {
    has_saved_research: true,
    has_decisions_in_period: false,
    saved_without_decisions_message:
      "У вас есть сохранённые исследования, но вы ещё не фиксировали решения.",
  },
  interpretation_notes: ["Сохранение — не тест."],
};

describe("ValidationReportView", () => {
  beforeEach(() => {
    vi.mocked(getValidationReport).mockReset();
  });

  it("shows portfolio totals and hint when saves exist without decisions", async () => {
    vi.mocked(getValidationReport).mockResolvedValue({
      period: { start: null, end: null },
      topics_saved_in_period: 0,
      current_status_counts: {},
      status_transition_events: {},
      latest_finding_rating_distribution: {},
      topics_with_latest_feedback: 0,
      topics_with_own_test_video_url: 0,
      topics_with_known_own_test_outcome: 0,
      latest_observation_presence: {},
      topics_with_comparable_count_deltas: 0,
      frozen_support_source_breakdown: {},
      frozen_family_kind_breakdown: {},
      interpretation_notes: [],
      research_portfolio: basePortfolio,
    });

    render(<ValidationReportView />);

    await waitFor(() => {
      expect(screen.getByText("Итоги исследований")).toBeInTheDocument();
    });

    expect(screen.getAllByText("Сохранено за период").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("3").length).toBeGreaterThanOrEqual(1);
    expect(
      screen.getByText(/У вас есть сохранённые исследования, но вы ещё не фиксировали решения/),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Test video/ })).toHaveAttribute("href", "/saved/videos/1");
  });

  it("shows error state on failure", async () => {
    vi.mocked(getValidationReport).mockRejectedValue(new Error("network"));

    render(<ValidationReportView />);

    await waitFor(() => {
      expect(screen.getByText("network")).toBeInTheDocument();
    });
  });
});
