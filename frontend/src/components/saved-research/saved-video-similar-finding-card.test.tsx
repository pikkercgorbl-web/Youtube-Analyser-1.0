import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SavedVideoSimilarFindingCard } from "./saved-video-similar-finding-card";
import type { SavedVideoSimilarFinding } from "@/lib/saved-research-types";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

const baseRow: SavedVideoSimilarFinding = {
  id: 7,
  video_id: "abcdefghij7",
  title: "Sample finding",
  channel_title: "Channel",
  views_count: 1000,
  published_text: "2 days ago",
  thumbnail_url: null,
  matched_query: "grain carts",
  last_found_at: "2026-10-01T00:00:00Z",
  youtube_url: "https://www.youtube.com/watch?v=abcdefghij7",
  relevance_score: 44,
  relevance_tier: "primary",
  why_found: "совпадение предметных слов",
  other_reason: null,
  user_verdict: null,
  saved_to_research: false,
};

describe("SavedVideoSimilarFindingCard", () => {
  it("feedback and save invoke separate handlers", () => {
    const onSave = vi.fn();
    const onFeedback = vi.fn();
    render(
      <SavedVideoSimilarFindingCard
        row={baseRow}
        showOtherHint={false}
        onSave={onSave}
        onFeedback={onFeedback}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Подходит" }));
    expect(onFeedback).toHaveBeenCalledWith(7, "fit");
    expect(onSave).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(onSave).toHaveBeenCalledWith(7);
  });

  it("shows saved state on the save button", () => {
    render(
      <SavedVideoSimilarFindingCard
        row={{ ...baseRow, saved_to_research: true }}
        showOtherHint={false}
        onSave={vi.fn()}
        onFeedback={vi.fn()}
      />,
    );
    const btn = screen.getByRole("button", { name: "Сохранено" });
    expect(btn).toBeDisabled();
  });
});
