import { describe, expect, it } from "vitest";

import {
  dailyIntelligenceFamilyDetailHref,
  decodeDailyIntelligenceRouteParam,
} from "./daily-intelligence-routes";

describe("dailyIntelligenceFamilyDetailHref", () => {
  it("encodes family_key with colons", () => {
    const key = "keyword:123:foo:bar";
    const href = dailyIntelligenceFamilyDetailHref("2026-10-10", key);
    expect(href).toContain(encodeURIComponent(key));
    expect(decodeDailyIntelligenceRouteParam(href.split("/families/")[1]!)).toBe(key);
  });
});
