import { describe, expect, it, vi } from "vitest";

import {
  COMPETITOR_LOAD_CONCURRENCY,
  applyChannelPreviewSuccess,
  buildUniqueChannelViews,
  dedupeIdenticalChannelRefs,
  runCompetitorLoadPool,
} from "@/lib/competitor-multi-load";
import type { CompetitorChannelPreviewResponse } from "@/lib/types";

function preview(
  channelId: string,
  inputRef: string,
  channelTitle?: string,
): CompetitorChannelPreviewResponse {
  return {
    input_ref: inputRef,
    channel_id: channelId,
    channel_title: channelTitle ?? channelId,
    subscribers_count: null,
    channel_avatar_url: "",
    feed_loaded_count: 1,
    regular_confirmed_count: 1,
    publications: [
      {
        video_id: `${channelId}-v1`,
        channel_id: channelId,
        title: "t",
        thumbnail_url: "",
        views_count: 10,
        published_text: "",
        duration_text: "",
        url: "",
        kind: "regular",
        published_at: "2026-01-01T00:00:00.000Z",
        duration_seconds: 60,
        in_feed: true,
      },
    ],
    load_status: "ready",
    enrichment_error: null,
    fetched_at: "2026-01-01T00:00:00.000Z",
  };
}

describe("dedupeIdenticalChannelRefs", () => {
  it("removes identical refs", () => {
    expect(deduplicate(["@A", "@a", "  @A  "])).toEqual(["@A"]);
  });
});

function deduplicate(refs: string[]) {
  return dedupeIdenticalChannelRefs(refs);
}

describe("buildUniqueChannelViews", () => {
  it("merges same channel_id from two jobs", () => {
    let jobs = applyChannelPreviewSuccess(
      [
        {
          inputRef: "a",
          status: "ready",
          errorMessage: null,
          userError: null,
          retryLoading: false,
          response: preview("UC1", "a"),
          mergedIntoChannelId: null,
        },
        {
          inputRef: "b",
          status: "queued",
          errorMessage: null,
          userError: null,
          retryLoading: false,
          response: null,
          mergedIntoChannelId: null,
        },
      ],
      "b",
      preview("UC1", "b"),
    );
    const views = buildUniqueChannelViews(jobs);
    expect(views).toHaveLength(1);
    expect(views[0].aliasInputRefs.length).toBeGreaterThanOrEqual(1);
  });

  it("sets displayTitle from input ref when API title is channel id", () => {
    const jobs = [
      {
        inputRef: "@mychan",
        status: "ready" as const,
        errorMessage: null,
        userError: null,
        retryLoading: false,
        response: preview("UC1", "@mychan"),
        mergedIntoChannelId: null,
      },
    ];
    const views = buildUniqueChannelViews(jobs);
    expect(views[0].displayTitle).toBe("@mychan");
  });
});

describe("runCompetitorLoadPool", () => {
  it("limits concurrency to 2", async () => {
    let active = 0;
    let maxActive = 0;
    const delays = [50, 50, 50, 50];
    const fetchOne = vi.fn(async () => {
      active += 1;
      maxActive = Math.max(maxActive, active);
      await new Promise((r) => setTimeout(r, delays.shift() ?? 10));
      active -= 1;
      return preview("UCX", "ref");
    });

    await runCompetitorLoadPool({
      inputRefs: ["r1", "r2", "r3", "r4"],
      generation: 1,
      isGenerationCurrent: () => true,
      getJobGeneration: () => 1,
      abortControllers: new Map(),
      fetchOne,
      onJobStart: () => {},
      onJobSuccess: () => {},
      onJobError: () => {},
    });

    expect(maxActive).toBeLessThanOrEqual(COMPETITOR_LOAD_CONCURRENCY);
    expect(fetchOne).toHaveBeenCalledTimes(4);
  });
});
