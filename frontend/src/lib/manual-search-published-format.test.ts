import { describe, expect, it } from "vitest";

import {
  formatManualSearchAgeLabel,
  formatViewsAndAgeLine,
} from "@/lib/manual-search-published-format";

describe("manual-search-published-format", () => {
  it("localizes relative day counts to Russian", () => {
    expect(formatManualSearchAgeLabel("1 day ago")).toBe("1 день назад");
    expect(formatManualSearchAgeLabel("5 days ago")).toBe("5 дней назад");
  });

  it("formats views and age on one line", () => {
    const line = formatViewsAndAgeLine(1600, "1 day ago");
    expect(line).toContain("просмотров");
    expect(line).toContain("1 день назад");
    expect(line).toContain("·");
  });

  it("omits views when count unknown", () => {
    expect(formatViewsAndAgeLine(undefined, "2 weeks ago")).toMatch(/недел/i);
    expect(formatViewsAndAgeLine(0, "2 weeks ago")).toMatch(/недел/i);
  });
});
