import { describe, expect, it } from "vitest";

import {
  buildManualSearchApiPayload,
  countManualSearchFilterGroups,
  DEFAULT_MANUAL_SEARCH_FILTERS,
  manualSearchFilterChips,
  normalizeManualSearchFilters,
  validateManualSearchFilters,
} from "@/lib/manual-search-filters";

describe("manual-search-filters", () => {
  it("buildManualSearchApiPayload keeps relevance and no server-side cuts", () => {
    const payload = buildManualSearchApiPayload("test query");
    expect(payload.sort_by).toBe("relevance");
    expect(payload.filters.virality_only_above_one).toBe(false);
    expect(payload.filters.views_min).toBeNull();
    expect(payload.filters.published_within).toBeNull();
    expect(payload.filters.hide_shorts).toBe(false);
  });

  it("drops legacy virality fields when normalizing stored filters", () => {
    const normalized = normalizeManualSearchFilters({
      publishedPeriod: "month",
      // @ts-expect-error legacy junk
      virality_min: 1,
      videoType: "shorts",
    });
    expect(normalized.publishedPeriod).toBe("month");
    expect(normalized.videoType).toBe("shorts");
  });

  it("validates range order", () => {
    expect(
      validateManualSearchFilters({
        ...DEFAULT_MANUAL_SEARCH_FILTERS,
        viewsMin: 5000,
        viewsMax: 1000,
      }),
    ).toMatch(/Просмотры/);
  });

  it("counts filter groups and builds chips", () => {
    const filters = {
      ...DEFAULT_MANUAL_SEARCH_FILTERS,
      publishedPeriod: "week" as const,
      viewsMin: 1000,
    };
    expect(countManualSearchFilterGroups(filters)).toBe(2);
    const labels = manualSearchFilterChips(filters).map((c) => c.label);
    expect(labels).toContain("За неделю");
    expect(labels.some((l) => l.includes("просмотров") && l.includes("1"))).toBe(true);
  });
});
