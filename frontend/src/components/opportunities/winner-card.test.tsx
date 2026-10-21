import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { WinnerCard } from "./winner-card";
import type { AttentionVideoWinner } from "@/lib/attention-types";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("@/components/saved-research/save-video-button", () => ({
  SaveVideoButton: () => <button type="button">Сохранить</button>,
}));

const video = {
  video_id: "abc12345678",
  title: "Sample winner title for card layout",
  channel_title: "Test Channel",
  youtube_url: "https://www.youtube.com/watch?v=abc12345678",
  breakout_rank: 1,
  views: 50000,
  vph: 12000,
  age_hours: 12,
  subscribers: null,
  human_reasons: [],
  reason_codes: ["breakout_high_rank"],
  channel_relative_signal: null,
  acceleration_state: "stable",
  delayed_outcome_state: "pending",
} as unknown as AttentionVideoWinner;

describe("WinnerCard", () => {
  it("shows metrics and actions without insight blocks", () => {
    render(<WinnerCard video={video} />);
    expect(screen.getByTestId("winner-card")).toBeInTheDocument();
    expect(screen.queryByTestId("winner-insight-blocks")).not.toBeInTheDocument();
    expect(screen.queryByText("Почему здесь")).not.toBeInTheDocument();
    expect(screen.getByText("В среднем за час")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Детали видео" })).toHaveAttribute(
      "href",
      "/opportunities/videos/abc12345678",
    );
    expect(screen.getByRole("link", { name: "Динамика видео" })).toHaveAttribute(
      "href",
      "/monitoring/videos/abc12345678",
    );
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeInTheDocument();
  });
});
