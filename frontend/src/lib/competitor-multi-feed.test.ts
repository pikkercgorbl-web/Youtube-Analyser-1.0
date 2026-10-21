import { describe, expect, it } from "vitest";

import { sortRegularPublicationsUnknownLast } from "@/lib/competitor-multi-feed";
import type { ChannelSingleAnalysisPublication } from "@/lib/types";

function pub(video_id: string, views: number, published_at: string | null): ChannelSingleAnalysisPublication {
  return {
    video_id,
    title: video_id,
    thumbnail_url: "",
    views_count: views,
    published_text: "",
    duration_text: "",
    url: "",
    kind: "regular",
    published_at,
    duration_seconds: null,
    in_feed: true,
  };
}

describe("sortRegularPublicationsUnknownLast", () => {
  it("puts unknown views last for most_views", () => {
    const sorted = sortRegularPublicationsUnknownLast(
      [pub("a", 0, "2026-01-01T00:00:00.000Z"), pub("b", 100, "2026-01-01T00:00:00.000Z")],
      "most_views",
    );
    expect(sorted[0].video_id).toBe("b");
    expect(sorted[1].video_id).toBe("a");
  });

  it("orders by date when both have published_at", () => {
    const sorted = sortRegularPublicationsUnknownLast(
      [pub("old", 1, "2026-01-01T00:00:00.000Z"), pub("new", 1, "2026-06-01T00:00:00.000Z")],
      "newest",
    );
    expect(sorted[0].video_id).toBe("new");
    expect(sorted[1].video_id).toBe("old");
  });
});
