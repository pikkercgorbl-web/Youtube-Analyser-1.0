import { describe, expect, it } from "vitest";

import {
  cyclePartialPrimaryCause,
  cycleStatusDetailLabel,
  monitoringExecutionErrorCount,
} from "./monitoring-cycle-presentation";
import type { MonitoringCycle } from "./monitoring-types";

function cycle(partial: Partial<MonitoringCycle>): MonitoringCycle {
  return {
    run_id: "r1",
    started_at: "2026-10-13T00:00:00Z",
    finished_at: "2026-10-13T00:01:00Z",
    runtime_seconds: 5,
    cycle_status: "partial",
    loaded: 100,
    tier_a: 0,
    tier_b: 0,
    tier_c: 0,
    due: 1,
    overdue: 1,
    selected: 2,
    deferred: 0,
    inserted: 1,
    missing: 1,
    fetch_failed: 0,
    validation_failed: 0,
    persistence_failed: 0,
    duplicate_snapshot_count: 0,
    ...partial,
  };
}

describe("monitoring-cycle-presentation", () => {
  it("detects missing-only partial", () => {
    const row = cycle({ partial_primary_cause: "missing_only" });
    expect(cyclePartialPrimaryCause(row)).toBe("missing_only");
    expect(monitoringExecutionErrorCount(row)).toBe(0);
    expect(cycleStatusDetailLabel(row)).toMatch(/API|missing/i);
  });

  it("shows execution errors separately from missing", () => {
    const row = cycle({
      missing: 0,
      fetch_failed: 1,
      partial_primary_cause: "execution_errors",
    });
    expect(cyclePartialPrimaryCause(row)).toBe("execution_errors");
    expect(monitoringExecutionErrorCount(row)).toBe(1);
  });
});
