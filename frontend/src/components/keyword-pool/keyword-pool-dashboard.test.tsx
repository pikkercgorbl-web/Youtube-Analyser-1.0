import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { KeywordPoolDashboard } from "@/components/keyword-pool/keyword-pool-dashboard";
import * as api from "@/lib/api";
import type { TargetKeywordItem } from "@/lib/keyword-pool-types";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("@/lib/api", () => ({
  fetchTargetKeywords: vi.fn(),
}));

function hoursFromNow(h: number): string {
  return new Date(Date.now() + h * 3_600_000).toISOString();
}

function hoursAgo(h: number): string {
  return new Date(Date.now() - h * 3_600_000).toISOString();
}

function baseRow(partial: Partial<TargetKeywordItem>): TargetKeywordItem {
  return {
    id: 1,
    keyword: "alpha",
    created_at: "2026-01-01T00:00:00Z",
    last_checked: "2026-09-19T12:00:00Z",
    lifecycle_status: "active",
    scan_interval_seconds: 86_400,
    next_scan_at: hoursFromNow(24),
    status_changed_at: null,
    status_reason: "created",
    source_type: "seed",
    parent_keyword_id: null,
    ...partial,
  };
}

describe("KeywordPoolDashboard", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("shows due keywords as Пора сканировать and no VPH columns", async () => {
    vi.mocked(api.fetchTargetKeywords).mockResolvedValue([
      baseRow({ id: 1, keyword: "due-key", next_scan_at: hoursAgo(2) }),
      baseRow({
        id: 2,
        keyword: "child",
        parent_keyword_id: 1,
        lifecycle_status: "archived",
        next_scan_at: null,
      }),
    ]);

    render(<KeywordPoolDashboard />);

    await waitFor(() => {
      expect(screen.getByTestId("keyword-pool-table")).toBeInTheDocument();
    });

    expect(within(screen.getByTestId("pool-row-1")).getByText("Пора сканировать")).toBeInTheDocument();
    expect(screen.getByText("Не сканируется")).toBeInTheDocument();
    expect(screen.queryByText(/VPH/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/breakout/i)).not.toBeInTheDocument();

    const row = screen.getByTestId("pool-row-1");
    expect(within(row).getByText("Исходный")).toBeInTheDocument();
    expect(within(row).queryByText("seed")).not.toBeInTheDocument();
    expect(within(row).queryByText("created")).not.toBeInTheDocument();
  });

  it("shows parent keyword only in expansion", async () => {
    vi.mocked(api.fetchTargetKeywords).mockResolvedValue([
      baseRow({ id: 10, keyword: "parent" }),
      baseRow({ id: 11, keyword: "child", parent_keyword_id: 10 }),
    ]);

    render(<KeywordPoolDashboard />);

    await waitFor(() => {
      expect(screen.getByTestId("pool-row-11")).toBeInTheDocument();
    });

    expect(screen.getByTestId("pool-row-11")).not.toHaveTextContent("parent");
    const detailButtons = screen.getAllByRole("button", { name: /Технические детали/i });
    fireEvent.click(detailButtons[detailButtons.length - 1]!);
    expect(screen.getByText("Создан из")).toBeInTheDocument();
    expect(screen.getAllByText("parent").length).toBeGreaterThan(0);
  });

  it("links to keyword performance from expansion", async () => {
    vi.mocked(api.fetchTargetKeywords).mockResolvedValue([baseRow({ id: 42 })]);

    render(<KeywordPoolDashboard />);

    await waitFor(() => {
      expect(screen.getByTestId("pool-row-42")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /Технические детали/i }));

    const perfLink = await screen.findByRole("link", { name: "Производительность" });
    expect(perfLink).toHaveAttribute("href", "/keyword-performance/42");
  });

  it("shows empty pool state", async () => {
    vi.mocked(api.fetchTargetKeywords).mockResolvedValue([]);

    render(<KeywordPoolDashboard />);

    await waitFor(() => {
      expect(screen.getByTestId("empty-state")).toHaveTextContent("Пул ключей пуст.");
    });
  });

  it("shows no-due note when queue empty", async () => {
    vi.mocked(api.fetchTargetKeywords).mockResolvedValue([
      baseRow({
        next_scan_at: hoursFromNow(48),
      }),
    ]);

    render(<KeywordPoolDashboard />);

    await waitFor(() => {
      expect(screen.getByTestId("pool-no-due-note")).toBeInTheDocument();
    });
  });

  it("preserves last data when refresh fails", async () => {
    vi.mocked(api.fetchTargetKeywords)
      .mockResolvedValueOnce([baseRow({ keyword: "kept" })])
      .mockRejectedValueOnce(new Error("network"));

    render(<KeywordPoolDashboard />);

    await waitFor(() => {
      expect(screen.getByText("kept")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /Обновить/i }));

    await waitFor(() => {
      expect(screen.getByTestId("stale-data-warning")).toBeInTheDocument();
    });
    expect(screen.getByText("kept")).toBeInTheDocument();
  });

  it("shows lifecycle help about operational scheduling", async () => {
    vi.mocked(api.fetchTargetKeywords).mockResolvedValue([baseRow({})]);

    render(<KeywordPoolDashboard />);

    await waitFor(() => {
      expect(screen.getByText(/не оценка качества/i)).toBeInTheDocument();
    });
  });
});
