import { describe, expect, it } from "vitest";

import { dailyIntelligenceStatusLabel } from "./daily-intelligence-labels";

describe("daily-intelligence-labels", () => {
  it("maps status codes to Russian labels", () => {
    expect(dailyIntelligenceStatusLabel("provisional")).toBe("Предварительный");
    expect(dailyIntelligenceStatusLabel("complete")).toBe("Зафиксирован");
    expect(dailyIntelligenceStatusLabel("partial")).toBe("Зафиксирован с ограничениями");
    expect(dailyIntelligenceStatusLabel("unavailable")).toBe("Нет публикаций");
  });
});
