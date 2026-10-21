import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { WinnersTable } from "./winners-table";
import { isTopicCollection } from "./pattern-family-card";
import type {
  AttentionPatternFamily,
  AttentionVideoWinner,
} from "@/lib/attention-types";
afterEach(cleanup);
describe("Analyst presentation", () => {
  it("separates real API keyword/topic kinds from phrase evidence", () => {
    for (const family_kind of ["keyword_provenance", "video_topic"])
      expect(
        isTopicCollection({
          family_kind,
          quality_flags: [],
          opportunity_presentation_tier: "search_collection",
        } as unknown as AttentionPatternFamily),
      ).toBe(true);
    expect(
      isTopicCollection({
        family_kind: "title_phrase",
        quality_flags: [],
        opportunity_presentation_tier: "needs_review",
      } as unknown as AttentionPatternFamily),
    ).toBe(false);
  });
  it("keeps every returned candidate reachable and filters across the complete set", () => {
    const videos = Array.from(
      { length: 14 },
      (_, i) =>
        ({
          video_id: `v${i}`,
          title: `Video ${i}`,
          channel_title: "Channel",
          youtube_url: `https://www.youtube.com/watch?v=v${i}`,
          breakout_rank: i + 1,
          views: i,
          vph: i,
          age_hours: 24,
          subscribers: null,
          human_reasons: [],
          reason_codes: [],
          channel_relative_signal: null,
          acceleration_state: "stable",
          delayed_outcome_state: "pending",
        }) as unknown as AttentionVideoWinner,
    );
    render(<WinnersTable videos={videos} />);
    expect(screen.getAllByTestId("winner-row")).toHaveLength(12);
    fireEvent.click(
      screen.getByRole("button", { name: "Показать ещё 2 видео" }),
    );
    expect(screen.getAllByTestId("winner-row")).toHaveLength(14);
    fireEvent.change(screen.getByLabelText("Поиск по названию или каналу"), {
      target: { value: "Video 13" },
    });
    expect(screen.getAllByTestId("winner-row")).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Детали видео" })).toHaveAttribute(
      "href",
      "/opportunities/videos/v13",
    );
    expect(screen.getByRole("link", { name: "Динамика видео" })).toHaveAttribute(
      "href",
      "/monitoring/videos/v13",
    );
    expect(screen.queryByTestId("winner-insight-blocks")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Поиск по названию или каналу"), {
      target: { value: "absent" },
    });
    expect(screen.getByText("Видео не найдены")).toBeInTheDocument();
  });
  it("shows at most two signal badges from structured reason codes", () => {
    const row = {
      video_id: "v-high",
      title: "High VPH clip",
      channel_title: "Channel",
      channel_id: "ch-1",
      youtube_url: "https://www.youtube.com/watch?v=v-high",
      breakout_rank: 1,
      views: 1000,
      vph: 5000,
      age_hours: 12,
      subscribers: null,
      human_reasons: [],
      reason_codes: ["high_current_vph", "accelerating_velocity"],
      channel_relative_signal: null,
      acceleration_state: "accelerating",
      delayed_outcome_state: "pending",
    } as unknown as AttentionVideoWinner;
    render(<WinnersTable videos={[row]} />);
    const badges = screen.getByTestId("opportunity-video-signal-badges");
    expect(badges).toHaveTextContent("Высокий темп");
    expect(badges).toHaveTextContent("Набирает скорость");
    expect(badges.textContent?.split("Высокий темп").length).toBeLessThanOrEqual(2);
  });
});
