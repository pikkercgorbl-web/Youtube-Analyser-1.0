import { describe, expect, it } from "vitest";

import { discoveryListSummary } from "@/lib/keyword-performance-summaries";
import type { KeywordPerformanceMetrics } from "@/lib/keyword-performance-types";

const row = {
  keyword_id: 1,
  keyword: "a",
  scan_count: 1,
  unique_video_count: 10,
  evidence_status: "early",
} as KeywordPerformanceMetrics;

describe("keyword-performance-summaries", () => {
  it("discovery summary counts keywords and videos", () => {
    const s = discoveryListSummary([row, { ...row, keyword_id: 2, keyword: "b" }]);
    expect(s.lines[0].text).toMatch(/2 ключей/);
    expect(s.lines[0].text).toMatch(/20/);
  });
});
