import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { KeywordPerformanceDashboard } from "@/components/keyword-performance/keyword-performance-dashboard";
import * as api from "@/lib/api";
import type { KeywordPerformanceListResponse } from "@/lib/keyword-performance-types";

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    ...props
  }: {
    children: ReactNode;
    href: string;
    className?: string;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/lib/api", () => ({
  fetchKeywordPerformanceList: vi.fn(),
}));

const baseItem = {
  keyword_id: 1,
  keyword: "alpha",
  lifecycle_status: "probation",
  source_type: "seed",
  last_checked: null,
  next_scan_at: null,
  scan_interval_seconds: 3600,
  is_due: false,
  overdue_seconds: 0,
  scheduling_hint: null,
  scan_count: 3,
  first_scan_at: null,
  last_scan_at: "2026-09-20T10:00:00Z",
  discovery_hit_count: 10,
  unique_video_count: 8,
  unique_channel_count: 5,
  within_keyword_duplicate_hit_count: 0,
  cross_keyword_duplicate_count: 2,
  already_known_video_count: 1,
  duplicate_hit_count: 2,
  duplicate_rate: 0.2,
  regular_video_count: 10,
  short_count: 0,
  live_count: 0,
  qualification_passed_count: 4,
  qualification_rejected_count: 6,
  qualification_pass_rate: 0.4,
  persisted_for_monitoring_count: 2,
  monitored_video_count: 2,
  videos_with_snapshot_count: 2,
  videos_with_snapshot_24h_count: 1,
  videos_with_snapshot_48h_count: 1,
  videos_with_snapshot_72h_count: 0,
  t24_outcome_count: 0,
  t48_outcome_count: 0,
  t72_outcome_count: 0,
  confirmed_breakout_count: 0,
  videos_per_scan: 3.33,
  unique_videos_per_scan: 2.67,
  evaluated_at: "2026-09-20T12:00:00Z",
  attribution_mode: "all_hits",
  ranking_version: null,
  global_eligible_video_count: null,
  horizon_hours: 72,
  horizon_snapshot_tolerance_hours: 12,
  new_to_corpus_video_count: 6,
  shared_video_count: 1,
  exclusive_first_discovery_count: 5,
  attributed_video_count: 8,
  monitorable_video_count: null,
  breakout_eligible_video_count: null,
  breakout_ranked_video_count: null,
  top_decile_breakout_count: null,
  top_decile_breakout_rate: null,
  median_vph_at_discovery: 120,
  p90_vph_at_discovery: 400,
  median_current_vph: null,
  observed_72h_video_count: null,
  missing_72h_video_count: null,
  median_absolute_view_growth_72h: null,
  evidence_status: "early",
  evidence_detail: {
    scan_count: 3,
    unique_video_count: 8,
    breakout_eligible_video_count: 0,
    observed_72h_video_count: 0,
  },
};

function listResponse(
  overrides: Partial<KeywordPerformanceListResponse> = {},
): KeywordPerformanceListResponse {
  return {
    items: [baseItem],
    limit: 100,
    evaluated_at: "2026-09-20T12:00:00Z",
    attribution_mode: "all_hits",
    window_from: null,
    window_to: null,
    ranking_version: null,
    global_eligible_video_count: null,
    horizon_hours: 72,
    horizon_snapshot_tolerance_hours: 12,
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  vi.mocked(api.fetchKeywordPerformanceList).mockResolvedValue(listResponse());
});

describe("KeywordPerformanceDashboard", () => {
  it("initial request uses breakout=false and delayed=false", async () => {
    render(<KeywordPerformanceDashboard />);
    await waitFor(() => {
      expect(api.fetchKeywordPerformanceList).toHaveBeenCalledWith(
        expect.objectContaining({
          include_breakout: false,
          include_delayed: false,
          attribution_mode: "all_hits",
        }),
      );
    });
  });

  it("renders slim Discovery table with Russian columns", async () => {
    render(<KeywordPerformanceDashboard />);
    const table = await screen.findByTestId("discovery-table");
    expect(within(table).getByText("Найдено видео")).toBeInTheDocument();
    expect(within(table).getByText("Новых для базы")).toBeInTheDocument();
    expect(within(table).getByText("VPH при находке")).toBeInTheDocument();
    expect(
      within(table).queryByText(/Cross-kw|Атриб\./i),
    ).not.toBeInTheDocument();
    expect(within(table).queryByText(/p90/i)).not.toBeInTheDocument();
  });

  it("shows new-to-corpus explanation in tooltip", async () => {
    render(<KeywordPerformanceDashboard />);
    await screen.findByTestId("discovery-table");
    expect(screen.getByTitle(/раньше не знала/i)).toBeInTheDocument();
  });

  it("shows VPH at discovery tooltip", async () => {
    render(<KeywordPerformanceDashboard />);
    await screen.findByTestId("discovery-table");
    expect(screen.getByTitle(/просмотров в час/i)).toBeInTheDocument();
  });

  it("shows evidence is not quality copy", async () => {
    render(<KeywordPerformanceDashboard />);
    expect(
      await screen.findByText(/Evidence показывает объём наблюдений/i),
    ).toBeInTheDocument();
  });

  it("shows lifecycle badge without quality verdict controls", async () => {
    render(<KeywordPerformanceDashboard />);
    await screen.findByText("Пробный");
    expect(screen.getByTitle(/не оценка его качества/i)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /archive|activate|promote/i }),
    ).not.toBeInTheDocument();
  });

  it("renders discovery summary strip", async () => {
    render(<KeywordPerformanceDashboard />);
    await waitFor(() => {
      expect(screen.getByTestId("kp-summary-strip")).toHaveTextContent(
        /уникальных видео найдено/i,
      );
    });
  });

  it("switching to Breakout requests breakout=true", async () => {
    render(<KeywordPerformanceDashboard />);
    await screen.findByTestId("discovery-table");
    vi.mocked(api.fetchKeywordPerformanceList).mockClear();
    vi.mocked(api.fetchKeywordPerformanceList).mockResolvedValue(
      listResponse({
        global_eligible_video_count: 100,
        ranking_version: "breakout_v1",
        items: [
          {
            ...baseItem,
            top_decile_breakout_rate: 0.1,
            top_decile_breakout_count: 1,
          },
        ],
      }),
    );
    fireEvent.click(screen.getByTestId("metric-family-breakout"));
    await waitFor(() => {
      expect(api.fetchKeywordPerformanceList).toHaveBeenCalledWith(
        expect.objectContaining({
          include_breakout: true,
          include_delayed: false,
        }),
      );
    });
    expect(await screen.findByTestId("breakout-explainer")).toHaveTextContent(
      /top-decile/i,
    );
  });

  it("global eligible N=0 shows unavailable state not poor performance", async () => {
    vi.mocked(api.fetchKeywordPerformanceList).mockResolvedValue(
      listResponse({
        global_eligible_video_count: 0,
        items: [{ ...baseItem, top_decile_breakout_rate: 0 }],
      }),
    );
    render(<KeywordPerformanceDashboard />);
    fireEvent.click(await screen.findByTestId("metric-family-breakout"));
    expect(
      await screen.findByTestId("breakout-global-unavailable"),
    ).toBeInTheDocument();
    await screen.findByTestId("breakout-table");
    expect(screen.getByTestId("breakout-rate-1")).toHaveTextContent("—");
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
  });

  it("observed_72h=0 shows unavailable phrasing in cell", async () => {
    vi.mocked(api.fetchKeywordPerformanceList).mockResolvedValue(
      listResponse({
        items: [
          {
            ...baseItem,
            observed_72h_video_count: 0,
            missing_72h_video_count: 8,
          },
        ],
      }),
    );
    render(<KeywordPerformanceDashboard />);
    fireEvent.click(await screen.findByTestId("metric-family-outcomes"));
    await screen.findByTestId("outcomes-table");
    expect(await screen.findByTestId("outcomes-none-yet")).toBeInTheDocument();
    expect(screen.getByTestId("observed-72h-1")).toHaveTextContent(
      "Исходов пока нет",
    );
  });

  it("attribution switch refetches", async () => {
    render(<KeywordPerformanceDashboard />);
    await screen.findByTestId("discovery-table");
    vi.mocked(api.fetchKeywordPerformanceList).mockClear();
    fireEvent.change(screen.getByTestId("attribution-mode"), {
      target: { value: "first_discovery" },
    });
    await waitFor(() => {
      expect(api.fetchKeywordPerformanceList).toHaveBeenCalledWith(
        expect.objectContaining({ attribution_mode: "first_discovery" }),
      );
    });
  });

  it("renders attribution explanations in Russian", async () => {
    render(<KeywordPerformanceDashboard />);
    expect(await screen.findByTestId("attribution-help")).toHaveTextContent(
      "Первый источник",
    );
    expect(screen.getByTestId("attribution-help")).toHaveTextContent(
      /не causal/i,
    );
    expect(screen.queryByText("all_hits")).not.toBeInTheDocument();
  });

  it("cross-keyword duplicate hidden until expansion", async () => {
    render(<KeywordPerformanceDashboard />);
    await screen.findByTestId("discovery-table");
    expect(
      screen.queryByText(/Пересечения с другими ключами/i),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getAllByRole("button", { name: /Аналитические детали/i })[0],
    );
    expect(
      await screen.findByText(/Пересечения с другими ключами/i),
    ).toBeInTheDocument();
  });

  it("p90 visible only in expansion", async () => {
    render(<KeywordPerformanceDashboard />);
    await screen.findByTestId("discovery-table");
    fireEvent.click(
      screen.getAllByRole("button", { name: /Аналитические детали/i })[0],
    );
    expect(await screen.findByText(/VPH p90 при находке/i)).toBeInTheDocument();
  });

  it("does not show keyword score", async () => {
    render(<KeywordPerformanceDashboard />);
    const root = await screen.findByTestId("keyword-performance-dashboard");
    expect(root).not.toHaveTextContent(/Opportunity Score/i);
    expect(root).not.toHaveTextContent(/Opportunity Score/i);
  });

  it("does not show full metric family tab", async () => {
    render(<KeywordPerformanceDashboard />);
    await screen.findByTestId("discovery-table");
    expect(screen.queryByTestId("metric-family-full")).not.toBeInTheDocument();
  });

  it("API error differs from empty state", async () => {
    vi.mocked(api.fetchKeywordPerformanceList).mockRejectedValue(
      new Error("boom"),
    );
    render(<KeywordPerformanceDashboard />);
    expect(await screen.findByTestId("api-error")).toBeInTheDocument();
    expect(screen.queryByTestId("empty-keywords")).not.toBeInTheDocument();
  });

  it("keeps data on refresh failure", async () => {
    render(<KeywordPerformanceDashboard />);
    await screen.findByText("alpha");
    vi.mocked(api.fetchKeywordPerformanceList).mockRejectedValueOnce(
      new Error("refresh fail"),
    );
    fireEvent.click(screen.getByTestId("kp-refresh"));
    await waitFor(() =>
      expect(screen.getByText(/Ошибка обновления/i)).toBeInTheDocument(),
    );
    expect(screen.getByText("alpha")).toBeInTheDocument();
  });

  it("uses single list fetch per mode switch", async () => {
    render(<KeywordPerformanceDashboard />);
    await screen.findByTestId("discovery-table");
    const callsAfterLoad = vi.mocked(api.fetchKeywordPerformanceList).mock.calls
      .length;
    fireEvent.click(screen.getByTestId("metric-family-breakout"));
    await waitFor(() =>
      expect(
        vi.mocked(api.fetchKeywordPerformanceList).mock.calls.length,
      ).toBeGreaterThan(callsAfterLoad),
    );
  });

  it("limit change refetches from additional filters", async () => {
    render(<KeywordPerformanceDashboard />);
    await screen.findByTestId("discovery-table");
    fireEvent.click(
      screen.getByRole("button", { name: /Дополнительные фильтры/i }),
    );
    vi.mocked(api.fetchKeywordPerformanceList).mockClear();
    fireEvent.change(screen.getByTestId("limit-select"), {
      target: { value: "50" },
    });
    await waitFor(() => {
      expect(api.fetchKeywordPerformanceList).toHaveBeenCalledWith(
        expect.objectContaining({
          limit: 50,
          include_breakout: false,
          include_delayed: false,
        }),
      );
    });
  });

  it("shows keyword-specific evidence label", async () => {
    render(<KeywordPerformanceDashboard />);
    await screen.findByTestId("discovery-table");
    expect(screen.getByText("Ранняя стадия")).toBeInTheDocument();
  });
});
