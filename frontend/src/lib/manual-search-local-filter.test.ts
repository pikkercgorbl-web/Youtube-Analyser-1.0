import { describe, expect, it } from "vitest";

import { DEFAULT_MANUAL_SEARCH_FILTERS } from "@/lib/manual-search-filters";
import {
  applyManualSearchLocalFilters,
  classifyManualSearchVideo,
  mergeEnrichedPreservingOrder,
} from "@/lib/manual-search-local-filter";
import type { EnrichedVideoModel } from "@/lib/types";

function item(
  id: string,
  patch: Partial<EnrichedVideoModel["video"]> & { subs?: number; is_short?: boolean },
): EnrichedVideoModel {
  return {
    video: {
      video_id: id,
      title: patch.title ?? id,
      views_count: patch.views_count,
      published_text: patch.published_text,
      duration_text: patch.duration_text,
      is_short: patch.is_short,
    },
    channel: { subscribers_count: patch.subs },
    virality_coefficient: 0,
  };
}

describe("manual-search-local-filter", () => {
  it("mergeEnrichedPreservingOrder keeps YouTube order", () => {
    const base = [item("a", {}), item("b", {}), item("c", {})];
    const enriched = [
      { ...item("b", { subs: 100 }), channel: { subscribers_count: 100 } },
      { ...item("a", { subs: 50 }), channel: { subscribers_count: 50 } },
    ];
    const merged = mergeEnrichedPreservingOrder(base, enriched);
    expect(merged.map((r) => r.video.video_id)).toEqual(["a", "b", "c"]);
    expect(merged[0].channel.subscribers_count).toBe(50);
  });

  it("does not treat unknown duration as Shorts for type filter", () => {
    const unknown = item("u", { duration_text: "", is_short: false });
    expect(classifyManualSearchVideo(unknown)).toBe("unknown");
    const filtered = applyManualSearchLocalFilters([unknown], {
      ...DEFAULT_MANUAL_SEARCH_FILTERS,
      videoType: "shorts",
    });
    expect(filtered).toHaveLength(0);
  });

  it("filters views without coercing missing views to zero", () => {
    const withViews = item("v", { views_count: 5000 });
    const noViews = item("n", {});
    const filters = { ...DEFAULT_MANUAL_SEARCH_FILTERS, viewsMin: 1000 };
    const out = applyManualSearchLocalFilters([withViews, noViews], filters);
    expect(out.map((r) => r.video.video_id)).toEqual(["v"]);
  });

  it("restores hidden rows when filter cleared", () => {
    const rows = [item("a", { views_count: 100 }), item("b", { views_count: 5000 })];
    const strict = applyManualSearchLocalFilters(rows, {
      ...DEFAULT_MANUAL_SEARCH_FILTERS,
      viewsMin: 1000,
    });
    expect(strict).toHaveLength(1);
    const relaxed = applyManualSearchLocalFilters(rows, DEFAULT_MANUAL_SEARCH_FILTERS);
    expect(relaxed).toHaveLength(2);
  });
});
