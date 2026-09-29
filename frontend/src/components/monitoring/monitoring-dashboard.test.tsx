import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MonitoringDashboard } from "@/components/monitoring/monitoring-dashboard";
import * as api from "@/lib/api";

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
  getMonitoringStatus: vi.fn(),
  getMonitoringOverview: vi.fn(),
  getMonitoringVideos: vi.fn(),
  getMonitoringCycles: vi.fn(),
}));

const overviewFixture = {
  active_monitored_count: 2,
  tier_counts: { A: 1, B: 1, C: 0 },
  unmonitored_count: 0,
  due_count: 1,
  overdue_count: 0,
  pending_count: 3,
  stopped_count: 0,
  latest_cycle: null,
};

const videoItem = {
  video_id: "vid1",
  channel_id: "ch1",
  title: "Test Video",
  channel_title: "Channel",
  tier: "A",
  current_views: 12000,
  current_vph: null,
  age_hours: 10,
  published_at: "2026-09-14T12:00:00Z",
  latest_snapshot_at: null,
  next_checkpoint_hours: 12,
  monitoring_status: "active",
  due_checkpoint_hours: [],
  overdue_checkpoint_hours: [],
  baseline_status: null,
  vph_vs_channel_median: null,
  content_format: "regular",
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  vi.mocked(api.getMonitoringStatus).mockResolvedValue({
    status: "stale",
    lock_holder: "host:1",
    lock_acquired_at: null,
    worker_interval_seconds: 900,
    stale_after_seconds: 5400,
    last_seen: null,
    is_lock_stale: true,
    current_time: "2026-09-15T12:00:00Z",
  });
  vi.mocked(api.getMonitoringOverview).mockResolvedValue(overviewFixture);
  vi.mocked(api.getMonitoringVideos).mockResolvedValue({
    items: [videoItem],
    total: 1,
    limit: 50,
    offset: 0,
  });
  vi.mocked(api.getMonitoringCycles).mockResolvedValue({ items: [], limit: 10 });
});

describe("MonitoringDashboard", () => {
  it("renders priority human summary", async () => {
    render(<MonitoringDashboard />);
    const strip = await screen.findByTestId("monitoring-priority-summary");
    await waitFor(() => {
      expect(within(strip).getByText(/готовы к следующему снимку/i)).toBeInTheDocument();
    });
  });

  it("renders breakout human summary when mode switched", async () => {
    render(<MonitoringDashboard />);
    fireEvent.click(await screen.findByTestId("monitoring-mode-breakout"));
    const strip = await screen.findByTestId("monitoring-breakout-summary");
    expect(within(strip).getByText(/breakout v1/i)).toBeInTheDocument();
  });

  it("mode explanations differ", async () => {
    render(<MonitoringDashboard />);
    const help = await screen.findByTestId("monitoring-mode-help");
    expect(help.textContent).toMatch(/очередь/i);
    fireEvent.click(screen.getByTestId("monitoring-mode-breakout"));
    await waitFor(() => expect(help.textContent).toMatch(/VPH/i));
  });

  it("priority and breakout tables differ", async () => {
    render(<MonitoringDashboard />);
    await screen.findByTestId("monitoring-priority-table");
    expect(screen.getByText("След. контрольная точка")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("monitoring-mode-breakout"));
    await screen.findByTestId("monitoring-breakout-table");
    expect(screen.getByText("Место")).toBeInTheDocument();
    expect(screen.queryByText("След. контрольная точка")).not.toBeInTheDocument();
  });

  it("translates due/overdue in badges", async () => {
    vi.mocked(api.getMonitoringVideos).mockResolvedValue({
      items: [{ ...videoItem, due_checkpoint_hours: [12], overdue_checkpoint_hours: [] }],
      total: 1,
      limit: 50,
      offset: 0,
    });
    render(<MonitoringDashboard />);
    const table = await screen.findByTestId("monitoring-priority-table");
    expect(within(table).getByText("Пора снять снимок")).toBeInTheDocument();
  });

  it("shows tier operational help via tooltip trigger", async () => {
    render(<MonitoringDashboard />);
    await screen.findByTestId("monitoring-priority-summary");
    expect(screen.getByTitle(/Tier определяет частоту/i)).toBeInTheDocument();
  });

  it("shows capture pool labels in breakout expansion", async () => {
    vi.mocked(api.getMonitoringVideos).mockResolvedValue({
      items: [
        {
          ...videoItem,
          breakout_rank: 1,
          breakout_ranking_value: 500,
          in_active_capture_pool: false,
          latest_snapshot_at: "2026-09-15T11:00:00Z",
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });
    render(<MonitoringDashboard />);
    fireEvent.click(await screen.findByTestId("monitoring-mode-breakout"));
    await screen.findByText("#1");
    fireEvent.click(screen.getByRole("button", { name: /Контекст мониторинга/i }));
    expect(await screen.findByText("Вне пула наблюдения")).toBeInTheDocument();
  });

  it("does not show composite score in breakout mode", async () => {
    vi.mocked(api.getMonitoringVideos).mockResolvedValue({
      items: [
        {
          ...videoItem,
          current_vph: 120,
          breakout_rank: 2,
          breakout_ranking_value: 120,
          in_active_capture_pool: true,
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });
    render(<MonitoringDashboard />);
    fireEvent.click(await screen.findByTestId("monitoring-mode-breakout"));
    await screen.findByText("#2");
    expect(screen.queryByText(/breakout_ranking/)).not.toBeInTheDocument();
    expect(screen.queryByText("120 / 100")).not.toBeInTheDocument();
  });

  it("breakout empty context", async () => {
    vi.mocked(api.getMonitoringVideos).mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    });
    render(<MonitoringDashboard />);
    fireEvent.click(await screen.findByTestId("monitoring-mode-breakout"));
    expect(
      await screen.findByText(/нет видео, подходящих для breakout-рейтинга/i),
    ).toBeInTheDocument();
  });

  it("priority empty context", async () => {
    vi.mocked(api.getMonitoringVideos).mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    });
    render(<MonitoringDashboard />);
    expect(
      await screen.findByText(/нет видео, которым пора делать следующий снимок/i),
    ).toBeInTheDocument();
  });

  it("formats snapshot freshness in breakout table", async () => {
    vi.mocked(api.getMonitoringVideos).mockResolvedValue({
      items: [
        {
          ...videoItem,
          breakout_rank: 1,
          current_vph: 10,
          latest_snapshot_at: "2026-09-15T11:00:00Z",
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });
    render(<MonitoringDashboard />);
    fireEvent.click(await screen.findByTestId("monitoring-mode-breakout"));
    const table = await screen.findByTestId("monitoring-breakout-table");
    expect(within(table).getByText(/обновлено/i)).toBeInTheDocument();
  });

  it("hides raw English enums in primary status filter labels", async () => {
    render(<MonitoringDashboard />);
    await screen.findByTestId("monitoring-priority-table");
    expect(screen.getByRole("option", { name: "Просрочено" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "overdue" })).not.toBeInTheDocument();
  });

  it("hides video_id until row disclosure", async () => {
    render(<MonitoringDashboard />);
    await screen.findByTestId("monitoring-priority-table");
    expect(screen.queryByText("vid1")).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: /Технические детали/i })[0]);
    expect(await screen.findByText("vid1")).toBeInTheDocument();
  });

  it("keeps previous videos on refresh failure", async () => {
    render(<MonitoringDashboard />);
    await screen.findByText("Test Video");
    vi.mocked(api.getMonitoringVideos).mockRejectedValueOnce(new Error("videos down"));
    fireEvent.click(screen.getByTestId("monitoring-refresh"));
    await waitFor(() => expect(screen.getByText(/Ошибка обновления/i)).toBeInTheDocument());
    expect(screen.getByText("Test Video")).toBeInTheDocument();
  });

  it("does not add per-row API calls beyond list fetch", async () => {
    render(<MonitoringDashboard />);
    await screen.findByText("Test Video");
    const videoCalls = vi.mocked(api.getMonitoringVideos).mock.calls.length;
    expect(videoCalls).toBeGreaterThanOrEqual(1);
    expect(api.getMonitoringOverview).toHaveBeenCalled();
    expect(api.getMonitoringStatus).toHaveBeenCalled();
  });

  it("tier filter updates query", async () => {
    render(<MonitoringDashboard />);
    await screen.findAllByText("Test Video");
    fireEvent.change(screen.getAllByDisplayValue("Tier: все")[0], { target: { value: "A" } });
    await waitFor(() => {
      expect(api.getMonitoringVideos).toHaveBeenCalledWith(
        expect.objectContaining({ tier: "A" }),
      );
    });
  });

  it("status filter updates query in priority mode", async () => {
    render(<MonitoringDashboard />);
    await screen.findAllByText("Test Video");
    fireEvent.change(screen.getByDisplayValue("Все состояния"), { target: { value: "due" } });
    await waitFor(() => {
      expect(api.getMonitoringVideos).toHaveBeenCalledWith(
        expect.objectContaining({ status: "due" }),
      );
    });
  });

  it("breakout mode sends sort breakout_v1 without status filter", async () => {
    render(<MonitoringDashboard />);
    await screen.findAllByText("Test Video");
    fireEvent.click(screen.getByTestId("monitoring-mode-breakout"));
    await waitFor(() => {
      expect(api.getMonitoringVideos).toHaveBeenCalledWith(
        expect.objectContaining({ sort: "breakout_v1", status: undefined }),
      );
    });
  });

  it("shows worker status badge", async () => {
    render(<MonitoringDashboard />);
    expect(await screen.findByText(/Состояние устарело|Статус недоступен|Воркер/i)).toBeInTheDocument();
  });

  it("shows empty latest cycle in disclosure", async () => {
    render(<MonitoringDashboard />);
    fireEvent.click(await screen.findByRole("button", { name: /Последний цикл/i }));
    expect(await screen.findByTestId("monitoring-no-cycles")).toBeInTheDocument();
  });

  it("video row links to detail", async () => {
    render(<MonitoringDashboard />);
    const link = (await screen.findAllByRole("link", { name: "Test Video" }))[0];
    expect(link).toHaveAttribute("href", "/monitoring/videos/vid1");
  });

  it("paginates results", async () => {
    vi.mocked(api.getMonitoringVideos).mockResolvedValue({
      items: [videoItem],
      total: 120,
      limit: 50,
      offset: 0,
    });
    render(<MonitoringDashboard />);
    await screen.findAllByText("Test Video");
    fireEvent.click(screen.getAllByRole("button", { name: "Вперёд" })[0]);
    await waitFor(() => {
      expect(api.getMonitoringVideos).toHaveBeenCalledWith(
        expect.objectContaining({ offset: 50 }),
      );
    });
  });
});
