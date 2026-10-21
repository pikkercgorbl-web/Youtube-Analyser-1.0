import axios from "axios";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OpportunityWinnerDetailView } from "./opportunity-winner-detail-view";
import type { AttentionVideoWinner } from "@/lib/attention-types";

const getAttentionVideo = vi.fn();

vi.mock("@/lib/api", () => ({
  getAttentionVideo: (...args: unknown[]) => getAttentionVideo(...args),
  listSavedVideos: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  saveSavedVideo: vi.fn(),
}));

const baseVideo: AttentionVideoWinner = {
  video_id: "abcdefghij1",
  title: "Long title ".repeat(20),
  channel_id: "ch1",
  channel_title: "Channel One",
  youtube_url: "https://www.youtube.com/watch?v=abcdefghij1",
  published_at: null,
  age_hours: 12,
  views: 1000,
  vph: 80,
  subscribers: 5000,
  breakout_rank: 3,
  breakout_eligible: true,
  channel_relative_signal: {
    status: "production_ready",
    baseline_quality: "production_ready",
    comparable_video_count: 5,
    vph_vs_channel_median: 2.1,
    notes: [],
  },
  acceleration_state: "accelerating",
  delayed_outcome_state: "pending",
  delayed_outcome_growth: null,
  reason_codes: ["breakout_high_rank"],
  human_reasons: ["breakout_v1 rank 3 in this attention window"],
  keyword_ids: [1],
  discovery_keywords: [{ keyword_id: 1, keyword: "cartoon ai" }],
};

afterEach(cleanup);

describe("OpportunityWinnerDetailView", () => {
  beforeEach(() => {
    getAttentionVideo.mockReset();
    sessionStorage.clear();
  });

  it("renders compact insight blocks and disclosures when video loads", async () => {
    getAttentionVideo.mockResolvedValue({
      video: baseVideo,
      data_source: "snapshot",
      run_id: "run-1",
      computed_at: "2026-10-12T00:00:00Z",
    });
    render(<OpportunityWinnerDetailView videoId="abcdefghij1" />);
    await waitFor(() =>
      expect(screen.getByTestId("winner-insight-blocks")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("winner-insight-why")).toBeInTheDocument();
    expect(screen.getByTestId("winner-insight-channel")).toBeInTheDocument();
    expect(screen.getByTestId("winner-insight-next")).toBeInTheDocument();
    expect(screen.getByTestId("winner-snapshot-context")).toBeInTheDocument();
    expect(screen.getByText("Как рассчитано")).toBeInTheDocument();
    expect(screen.getByText("Где найдено")).toBeInTheDocument();
    expect(screen.getByTestId("winner-detail-back")).toHaveAttribute("href", "/opportunities");
  });

  it("shows skeleton while loading without stash", async () => {
    getAttentionVideo.mockImplementation(
      () =>
        new Promise((resolve) => {
          setTimeout(
            () =>
              resolve({
                video: baseVideo,
                data_source: "snapshot",
                run_id: "run-1",
                computed_at: "2026-10-12T00:00:00Z",
              }),
            50,
          );
        }),
    );
    render(<OpportunityWinnerDetailView videoId="abcdefghij1" />);
    expect(screen.getByTestId("winner-detail-skeleton")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByTestId("winner-detail-skeleton")).not.toBeInTheDocument(),
    );
  });

  it("shows missing state for 404", async () => {
    getAttentionVideo.mockRejectedValue(
      new axios.AxiosError("not found", "ERR", undefined, undefined, {
        status: 404,
        data: {},
        headers: {},
        config: {} as never,
        statusText: "Not Found",
      }),
    );
    render(<OpportunityWinnerDetailView videoId="missing" />);
    await waitFor(() =>
      expect(screen.getByText(/нет в текущем снимке Winners/i)).toBeInTheDocument(),
    );
  });
});
