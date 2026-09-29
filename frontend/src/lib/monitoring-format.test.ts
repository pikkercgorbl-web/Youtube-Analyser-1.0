import { describe, expect, it } from "vitest";

import {
  formatAgeHours,
  formatMonitoringVph,
  workerStatusLabel,
} from "@/lib/monitoring-format";

describe("monitoring-format", () => {
  it("formats null VPH safely", () => {
    expect(formatMonitoringVph(null)).toBe("—");
  });

  it("formats age hours", () => {
    expect(formatAgeHours(12.4)).toContain("ч");
    expect(formatAgeHours(50)).toContain("д");
  });

  it("does not label unknown as online", () => {
    expect(workerStatusLabel("unknown")).toBe("Статус недоступен");
    expect(workerStatusLabel("running")).not.toMatch(/online/i);
  });
});
