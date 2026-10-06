import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OperationsDashboard } from "@/components/operations/operations-dashboard";
import * as api from "@/lib/api";
import type { OperationsOverviewResponse } from "@/lib/operations-types";

vi.mock("@/lib/api", () => ({
  getOperationsOverview: vi.fn(),
  getMonitoringOverview: vi.fn(),
  fetchKeywordPerformanceList: vi.fn(),
}));

const worker = {
  lock_status: "idle",
  lock_holder: null,
  lock_acquired_at: null,
  last_activity_at: "2026-09-28T10:00:00Z",
  activity_state: "active_recently" as const,
  expected_interval_seconds: 300,
  stale_lock_minutes: 90,
  liveness_note: "Last cycle/lock activity only; true process liveness requires Stage 1.19D heartbeat.",
};

function overviewFixture(
  overrides: Partial<OperationsOverviewResponse> = {},
): OperationsOverviewResponse {
  return {
    generated_at: "2026-09-28T12:00:00Z",
    discovery: {
      worker: { ...worker, activity_state: "stale_activity" },
      last_cycle_started_at: "2026-09-28T11:50:00Z",
      last_cycle_finished_at: "2026-09-28T11:55:00Z",
      last_cycle_status: "ok",
      last_run_id: "disc-run-1",
      last_error: null,
      last_cycle_runtime_seconds: 12.5,
      keywords_scanned_last_cycle: 5,
      raw_candidates_last_cycle: 40,
      unique_videos_last_cycle: 30,
      persisted_videos_last_cycle: 10,
      keyword_errors_last_cycle: 0,
      keywords_due_now: 3,
      keywords_due_next_1h: 2,
      keywords_due_next_24h: 7,
      keywords_due_next_24h_includes_1h: true,
    },
    monitoring: {
      worker,
      last_cycle_finished_at: "2026-09-28T11:58:00Z",
      last_cycle_started_at: "2026-09-28T11:57:00Z",
      last_cycle_status: "ok",
      last_run_id: "mon-run-1",
      last_cycle_runtime_seconds: 8,
      loaded_video_count: 100,
      eligible_video_count: 80,
      selected_capture_count: 10,
      inserted_snapshot_count: 9,
      missing_count: 1,
      fetch_failed_count: 0,
      validation_failed_count: 0,
      persistence_failed_count: 0,
      due_count_at_last_cycle: 4,
      overdue_count_at_last_cycle: 1,
      live_planner_due_count: null,
      live_planner_overdue_count: null,
      live_planner_requested: false,
    },
    outcome_capture: {
      worker: {
        lock_status: "idle",
        lock_holder: null,
        lock_acquired_at: null,
        last_activity_at: "2026-09-28T11:00:00Z",
        activity_state: "unknown",
        expected_interval_seconds: 3600,
        stale_lock_minutes: 90,
        liveness_note: "Delayed outcome capture worker",
      },
      planner_pending: 10,
      planner_due: 2,
      planner_overdue: 0,
      planner_satisfied: 5,
      planner_expired: 80,
      unique_due_videos: 2,
      last_cycle_started_at: "2026-09-28T11:00:00Z",
      last_cycle_finished_at: "2026-09-28T11:01:00Z",
      last_cycle_status: "ok",
      last_run_id: "outcome_test",
      selected_video_count_last_cycle: 2,
      deferred_video_count_last_cycle: 0,
      inserted_snapshot_count_last_cycle: 2,
      fetch_failed_count_last_cycle: 0,
      duplicate_snapshot_count_last_cycle: 0,
      missing_video_count_last_cycle: 0,
    },
    snapshots: {
      latest_snapshot_at: "2026-09-28T11:59:00Z",
      snapshots_last_1h: 5,
      snapshots_last_24h: 42,
      unique_videos_snapshotted_last_24h: 38,
      daily_counts_last_7d: [{ date: "2026-09-28", count: 10 }],
    },
    keyword_outcomes: {
      attribution_mode: "all_hits",
      horizon_hours: 72,
      tolerance_hours: 12,
      attributed_observation_count: 100,
      pending_72h_count: 20,
      matured_72h_count: 80,
      valid_72h_outcome_count: 30,
      missing_72h_outcome_count: 50,
      matures_next_6h: 2,
      matures_next_24h: 5,
      matures_next_48h: 9,
    },
    errors: {
      discovery_last_cycle_error: null,
      monitoring_recent_error_summaries: [],
    },
    recent_cycles: {
      discovery: [
        {
          discovery_run_id: "disc-run-1",
          started_at: "2026-09-28T11:50:00Z",
          finished_at: "2026-09-28T11:55:00Z",
          runtime_seconds: 12,
          keywords_scanned: 5,
          raw_candidates: 40,
          unique_candidates: 30,
          persisted_videos: 10,
          qualification_passed: 0,
          qualification_rejected: 0,
          keyword_scan_failures: 0,
          error_summaries: [],
        },
      ],
      monitoring: [
        {
          run_id: "mon-run-1",
          started_at: "2026-09-28T11:57:00Z",
          finished_at: "2026-09-28T11:58:00Z",
          runtime_seconds: 8,
          cycle_status: "ok",
          loaded_video_count: 100,
          selected_request_count: 10,
          inserted_snapshot_count: 9,
          missing_count: 1,
          fetch_failed_count: 0,
          validation_failed_count: 0,
          persistence_failed_count: 0,
          due_count: 4,
          overdue_count: 1,
          error_summary: null,
        },
      ],
    },
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

beforeEach(() => {
  vi.mocked(api.getOperationsOverview).mockResolvedValue(overviewFixture());
});

function primaryText(): string {
  return document.body.textContent ?? "";
}

describe("OperationsDashboard", () => {
  it("uses live planner false by default", async () => {
    render(<OperationsDashboard />);
    await waitFor(() => expect(api.getOperationsOverview).toHaveBeenCalled());
    expect(api.getOperationsOverview).toHaveBeenCalledWith(
      expect.objectContaining({
        include_live_monitoring_planner: false,
        outcome_attribution_mode: "all_hits",
      }),
    );
    const toggle = await screen.findByTestId("operations-live-planner-toggle");
    expect(toggle).not.toBeChecked();
  });

  it("renders human Discovery summary", async () => {
    render(<OperationsDashboard />);
    const strip = await screen.findByTestId("operations-discovery-summary");
    expect(within(strip).getByText(/Discovery давно не запускался/i)).toBeInTheDocument();
  });

  it("shows loaded>0 and eligible=0 explanatory copy", async () => {
    vi.mocked(api.getOperationsOverview).mockResolvedValue(
      overviewFixture({
        monitoring: {
          ...overviewFixture().monitoring,
          loaded_video_count: 50,
          eligible_video_count: 0,
          inserted_snapshot_count: 0,
        },
      }),
    );
    render(<OperationsDashboard />);
    expect(await screen.findByTestId("operations-monitoring-no-eligible")).toBeInTheDocument();
    expect(
      within(screen.getByTestId("operations-monitoring-no-eligible")).getByText(
        /нет видео, подходящих под текущие правила мониторинга/i,
      ),
    ).toBeInTheDocument();
  });

  it("uses Russian operational labels in primary UI", async () => {
    render(<OperationsDashboard />);
    await screen.findByTestId("operations-discovery-due-now");
    expect(screen.getByText("Ключей пора обработать")).toBeInTheDocument();
    expect(screen.getByText("Подходит для наблюдения")).toBeInTheDocument();
    expect(screen.getAllByText("Снимков сохранено").length).toBeGreaterThan(0);
  });

  it("does not expose raw Loaded/Eligible/Selected/Inserted in primary UI", async () => {
    render(<OperationsDashboard />);
    await screen.findByTestId("operations-discovery-due-now");
    const text = primaryText();
    expect(text).not.toMatch(/\bLoaded\b/);
    expect(text).not.toMatch(/\bEligible\b/);
    expect(text).not.toMatch(/\bSelected\b/);
    expect(text).not.toMatch(/\bInserted\b/);
    expect(text).not.toMatch(/\bDue\b/);
    expect(text).not.toMatch(/\bRun ID\b/);
  });

  it("renders zero snapshot context when 24h is zero", async () => {
    vi.mocked(api.getOperationsOverview).mockResolvedValue(
      overviewFixture({
        snapshots: {
          ...overviewFixture().snapshots,
          snapshots_last_24h: 0,
          snapshots_last_1h: 0,
        },
      }),
    );
    render(<OperationsDashboard />);
    expect(await screen.findByTestId("operations-snapshot-zero-24h")).toBeInTheDocument();
  });

  it("renders zero valid 72h context", async () => {
    vi.mocked(api.getOperationsOverview).mockResolvedValue(
      overviewFixture({
        keyword_outcomes: {
          ...overviewFixture().keyword_outcomes,
          valid_72h_outcome_count: 0,
        },
      }),
    );
    render(<OperationsDashboard />);
    expect(await screen.findByTestId("operations-outcome-zero-valid")).toBeInTheDocument();
  });

  it("does not style missing outcomes as error", async () => {
    render(<OperationsDashboard />);
    await screen.findByTestId("operations-outcome-missing");
    expect(screen.queryByTestId("error-state")).not.toBeInTheDocument();
    const missingBar = document.querySelector(".bg-muted-foreground\\/35");
    expect(missingBar).toBeTruthy();
  });

  it("hides cycle run_id until disclosure expanded", async () => {
    render(<OperationsDashboard />);
    await screen.findByTestId("operations-discovery-cycles");
    expect(screen.queryByText("disc-run-1")).not.toBeInTheDocument();
    const toggles = screen.getAllByRole("button", { name: /Технические детали/i });
    fireEvent.click(toggles[0]);
    expect(await screen.findByText("disc-run-1")).toBeInTheDocument();
  });

  it("does not show empty errors section", async () => {
    render(<OperationsDashboard />);
    await screen.findByTestId("operations-summary-layer");
    expect(screen.queryByTestId("operations-errors-section")).not.toBeInTheDocument();
  });

  it("shows errors section when API reports errors", async () => {
    vi.mocked(api.getOperationsOverview).mockResolvedValue(
      overviewFixture({
        errors: {
          discovery_last_cycle_error: "scan timeout",
          monitoring_recent_error_summaries: [],
        },
      }),
    );
    render(<OperationsDashboard />);
    expect(await screen.findByTestId("operations-errors-section")).toBeInTheDocument();
    expect(screen.getByText(/scan timeout/)).toBeInTheDocument();
  });

  it("attribution defaults to all_hits near 72h section", async () => {
    render(<OperationsDashboard />);
    const select = await screen.findByTestId("operations-attribution-select");
    expect(select).toHaveValue("all_hits");
    expect(screen.getByText("72 ч исходы")).toBeInTheDocument();
  });

  it("keeps data on refresh failure", async () => {
    render(<OperationsDashboard />);
    await screen.findByTestId("operations-discovery-due-now");
    vi.mocked(api.getOperationsOverview).mockRejectedValueOnce(new Error("refresh fail"));
    fireEvent.click(screen.getByTestId("operations-refresh"));
    await waitFor(() => expect(screen.getByText(/Ошибка обновления/i)).toBeInTheDocument());
    expect(screen.getByTestId("operations-discovery-due-now")).toHaveTextContent("3");
  });

  it("uses design-system summary strips", async () => {
    render(<OperationsDashboard />);
    expect(await screen.findByTestId("operations-monitoring-summary")).toBeInTheDocument();
    expect(screen.getByTestId("operations-snapshot-summary")).toBeInTheDocument();
  });

  it("renders discovery due counts and monitoring due/overdue", async () => {
    render(<OperationsDashboard />);
    expect(await screen.findByTestId("operations-discovery-due-now")).toHaveTextContent("3");
    expect(screen.getByTestId("operations-monitoring-due")).toHaveTextContent("4");
    expect(screen.getByTestId("operations-monitoring-overdue")).toHaveTextContent("1");
  });

  it("renders snapshot and maturity counts", async () => {
    render(<OperationsDashboard />);
    expect(await screen.findByTestId("operations-snapshot-24h")).toHaveTextContent("42");
    expect(screen.getByTestId("operations-outcome-valid")).toHaveTextContent("30");
    expect(screen.getByTestId("operations-outcome-missing")).toHaveTextContent("50");
    expect(screen.getByTestId("operations-upcoming-24h")).toHaveTextContent("5");
  });

  it("shows liveness disclaimer in secondary placement", async () => {
    render(<OperationsDashboard />);
    const note = await screen.findByTestId("operations-liveness-note");
    expect(note.textContent).toMatch(/heartbeat|lock/i);
    expect(screen.queryByRole("heading", { name: /Операции/i })).toBeInTheDocument();
  });

  it("shows system status badge with Russian label", async () => {
    render(<OperationsDashboard />);
    expect(await screen.findByText(/Давно не было циклов/)).toBeInTheDocument();
  });

  it("shows initial error distinct from empty state", async () => {
    vi.mocked(api.getOperationsOverview).mockRejectedValueOnce(new Error("network down"));
    render(<OperationsDashboard />);
    expect(await screen.findByText("Не удалось загрузить операции")).toBeInTheDocument();
    expect(screen.queryByText("Данных пока нет")).not.toBeInTheDocument();
  });

  it("does not call keyword performance or monitoring overview", async () => {
    render(<OperationsDashboard />);
    await screen.findByTestId("operations-discovery-due-now");
    expect(api.getMonitoringOverview).not.toHaveBeenCalled();
    expect(api.fetchKeywordPerformanceList).not.toHaveBeenCalled();
  });

  it("manual refresh triggers another request", async () => {
    render(<OperationsDashboard />);
    await screen.findByTestId("operations-discovery-due-now");
    fireEvent.click(screen.getByTestId("operations-refresh"));
    await waitFor(() => expect(api.getOperationsOverview).toHaveBeenCalledTimes(2));
  });

  it("live planner toggle changes API param", async () => {
    render(<OperationsDashboard />);
    await screen.findByTestId("operations-live-planner-toggle");
    fireEvent.click(screen.getByTestId("operations-live-planner-toggle"));
    await waitFor(() =>
      expect(api.getOperationsOverview).toHaveBeenLastCalledWith(
        expect.objectContaining({ include_live_monitoring_planner: true }),
      ),
    );
  });

  it("renders recent cycle tables", async () => {
    render(<OperationsDashboard />);
    expect(await screen.findByTestId("operations-discovery-cycles")).toBeInTheDocument();
    expect(screen.getByTestId("operations-monitoring-cycles")).toBeInTheDocument();
  });
});
