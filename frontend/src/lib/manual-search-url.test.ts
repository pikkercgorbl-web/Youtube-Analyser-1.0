import { describe, expect, it } from "vitest";

import { buildManualSearchFromSavedUrl } from "@/lib/manual-search-url";

describe("buildManualSearchFromSavedUrl", () => {
  it("encodes from_saved entry without triggering server search", () => {
    const href = buildManualSearchFromSavedUrl({
      sourceSavedId: 42,
      sourceVideoId: "abc123",
      initialQuery: "query with spaces & symbols",
    });
    expect(href.startsWith("/?")).toBe(true);
    const params = new URLSearchParams(href.slice(2));
    expect(params.get("from_saved")).toBe("1");
    expect(params.get("source_saved_id")).toBe("42");
    expect(params.get("source_video_id")).toBe("abc123");
    expect(params.get("q")).toBe("query with spaces & symbols");
  });
});
