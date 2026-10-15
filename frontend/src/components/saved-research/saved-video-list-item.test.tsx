import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SavedVideoListItem } from "./saved-video-list-item";
import type { SavedVideoListItem as Row } from "@/lib/saved-research-types";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

const row: Row = {
  id: 1,
  video_id: "abcdefghij1",
  title: "Test saved video",
  channel_title: "Channel",
  status: "WATCHING",
  notes: "",
  tags: [],
  saved_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
  archived_at: null,
  latest_observed_at: null,
  in_current_attention: null,
  frozen_views: 100,
  frozen_vph: 10,
  current_views: 200,
  current_vph: 12,
  related_family_labels: [],
  latest_analyst_verdict: null,
  latest_analyst_verdict_at: null,
  latest_measurement_source: "monitoring",
};

describe("SavedVideoListItem", () => {
  it("renders youtube thumbnail and preserves metrics", () => {
    render(<SavedVideoListItem row={row} />);
    expect(screen.getByTestId("saved-video-thumb")).toBeInTheDocument();
    const img = screen.getByRole("img", { name: "Test saved video" });
    expect(img.getAttribute("src")).toContain("abcdefghij1");
    expect(screen.getByText(/100/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Test saved video" })).toHaveAttribute(
      "href",
      "/saved/videos/1",
    );
  });
});
