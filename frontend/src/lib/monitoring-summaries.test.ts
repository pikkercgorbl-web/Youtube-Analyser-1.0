import { describe, expect, it } from "vitest";

import {
  breakoutMonitoringSummary,
  priorityMonitoringSummary,
} from "@/lib/monitoring-summaries";
import type { MonitoringOverview } from "@/lib/monitoring-types";

const overviewBase: MonitoringOverview = {
  active_monitored_count: 10,
  tier_counts: {},
  unmonitored_count: 0,
  due_count: 0,
  overdue_count: 0,
  pending_count: 5,
  stopped_count: 0,
  latest_cycle: null,
};

describe("monitoring-summaries", () => {
  it("priority due and overdue lines", () => {
    const s = priorityMonitoringSummary({
      ...overviewBase,
      due_count: 12,
      overdue_count: 3,
    });
    expect(s.lines.some((l) => l.text.includes("12"))).toBe(true);
    expect(s.lines.some((l) => l.text.includes("просроч"))).toBe(true);
  });

  it("priority idle queue", () => {
    const s = priorityMonitoringSummary(overviewBase);
    expect(s.lines[0].text).toMatch(/нет видео, требующих обработки/i);
  });

  it("breakout empty with active base", () => {
    const s = breakoutMonitoringSummary(0, 5);
    expect(s.lines[0].text).toMatch(/не подходят под текущие правила breakout/i);
  });
});
