import { describe, expect, it } from "vitest";

import {
  computeViewsRank,
  mergePublicationsByVideoId,
} from "@/lib/channel-single-analysis-overview";
import type { ChannelSingleAnalysisPublication } from "@/lib/types";

function pub(
  video_id: string,
  views: number,
  kind: string = "regular",
): ChannelSingleAnalysisPublication {
  return {
    video_id,
    title: video_id,
    thumbnail_url: "",
    views_count: views,
    published_text: "",
    duration_text: "",
    url: "",
    kind,
    published_at: "2026-01-01T00:00:00.000Z",
    duration_seconds: null,
    in_feed: true,
  };
}

describe("computeViewsRank", () => {
  it("assigns the same rank for equal views", () => {
    const list = [pub("a", 100), pub("b", 100), pub("c", 50), pub("focus", 100)];
    const result = computeViewsRank("focus", list);
    expect(result.rank).toBe(1);
    expect(result.groupSize).toBe(4);
  });

  it("orders by views desc with distinct rank for lower tier", () => {
    const list = [pub("focus", 50), pub("a", 200), pub("b", 200), pub("c", 100)];
    const result = computeViewsRank("focus", list);
    expect(result.rank).toBe(4);
  });
});

describe("mergePublicationsByVideoId", () => {
  it("deduplicates by video_id", () => {
    const merged = mergePublicationsByVideoId([pub("a", 1)], [pub("a", 2), pub("b", 3)]);
    expect(merged.map((p) => p.video_id).sort()).toEqual(["a", "b"]);
    expect(merged.find((p) => p.video_id === "a")?.views_count).toBe(1);
  });
});
