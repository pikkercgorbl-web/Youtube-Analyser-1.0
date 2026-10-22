import { describe, expect, it } from "vitest";

import { formatRelativeTime, parseApiInstant } from "./operations-format";

describe("parseApiInstant", () => {
  it("treats naive API datetime as UTC", () => {
    const ref = "2026-10-07T14:39:25+00:00";
    const naiveLatest = "2026-10-07 14:25:11";
    const rel = formatRelativeTime(naiveLatest, ref);
    expect(rel.relative).toBe("14 мин назад");
    expect(parseApiInstant(naiveLatest)).toBe(parseApiInstant("2026-10-07T14:25:11Z"));
  });
});
