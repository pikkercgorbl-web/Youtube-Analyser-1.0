import { describe, expect, it } from "vitest";

import {
  displayOrMissing,
  formatWinnerMetrics,
} from "./daily-intelligence-evidence-format";

describe("formatWinnerMetrics", () => {
  it("shows Нет данных for missing views instead of zero", () => {
    const m = formatWinnerMetrics({});
    expect(m.views).toBe("Нет данных");
    expect(m.vph).toBe("Нет данных");
  });

  it("formats present views", () => {
    const m = formatWinnerMetrics({ views: 1200, vph: 10.5 });
    expect(m.views).not.toBe("Нет данных");
    expect(m.vph).not.toBe("Нет данных");
  });
});

describe("displayOrMissing", () => {
  it("returns Нет данных for null", () => {
    expect(displayOrMissing(null)).toBe("Нет данных");
  });
});
