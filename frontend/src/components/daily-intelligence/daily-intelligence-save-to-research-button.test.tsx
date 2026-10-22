import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DailyIntelligenceSaveToResearchButton } from "./daily-intelligence-save-to-research-button";

const listSavedVideos = vi.fn();
const saveDailyIntelligenceVideoToResearch = vi.fn();

vi.mock("@/lib/api", () => ({
  listSavedVideos: (...args: unknown[]) => listSavedVideos(...args),
  listSavedFamilies: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  saveDailyIntelligenceVideoToResearch: (...args: unknown[]) =>
    saveDailyIntelligenceVideoToResearch(...args),
  saveDailyIntelligenceFamilyToResearch: vi.fn(),
}));

describe("DailyIntelligenceSaveToResearchButton", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  beforeEach(() => {
    listSavedVideos.mockResolvedValue({ items: [], total: 0 });
  });

  it("calls DI save endpoint without attention API", async () => {
    saveDailyIntelligenceVideoToResearch.mockResolvedValue({
      item: { id: 99 },
      created: true,
      idempotent: false,
    });
    render(
      <DailyIntelligenceSaveToResearchButton
        kind="video"
        reportDate="2026-10-10"
        videoId="vid1"
      />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("di-save-to-research")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("di-save-to-research"));
    await waitFor(() => {
      expect(saveDailyIntelligenceVideoToResearch).toHaveBeenCalledWith("2026-10-10", "vid1");
    });
    expect(screen.getByTestId("di-save-to-research-saved")).toHaveAttribute("href", "/saved/videos/99");
  });

  it("shows existing saved link", async () => {
    listSavedVideos.mockResolvedValue({
      items: [{ id: 7, video_id: "vid1", archived_at: null }],
      total: 1,
    });
    render(
      <DailyIntelligenceSaveToResearchButton
        kind="video"
        reportDate="2026-10-10"
        videoId="vid1"
      />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("di-save-to-research-saved")).toBeInTheDocument();
    });
  });

  it("shows archived 409 message", async () => {
    saveDailyIntelligenceVideoToResearch.mockRejectedValue({
      response: { status: 409, data: { detail: "archived" } },
    });
    render(
      <DailyIntelligenceSaveToResearchButton
        kind="video"
        reportDate="2026-10-10"
        videoId="vid1"
      />,
    );
    await waitFor(() => screen.getByTestId("di-save-to-research"));
    fireEvent.click(screen.getByTestId("di-save-to-research"));
    await waitFor(() => {
      expect(screen.getByText("archived")).toBeInTheDocument();
    });
  });
});
