import { describe, expect, it } from "vitest";

import {
  discoveryOperationsSummary,
  monitoringOperationsSummary,
  outcome72hOperationsSummary,
  snapshotOperationsSummary,
} from "@/lib/operations-summaries";
import type {
  DiscoveryOperationsBlock,
  KeywordOutcomeOperationsBlock,
  MonitoringOperationsBlock,
  SnapshotOperationsBlock,
} from "@/lib/operations-types";

const discoveryBase = {
  worker: { activity_state: "active_recently" as const },
  last_cycle_finished_at: "2026-09-28T11:55:00Z",
  last_cycle_status: "ok",
  last_error: null,
  keyword_errors_last_cycle: 0,
  keywords_due_now: 0,
} as DiscoveryOperationsBlock;

describe("operations-summaries", () => {
  it("discovery active cycle summary", () => {
    const s = discoveryOperationsSummary(discoveryBase, "5 мин назад");
    expect(s.lines[0].text).toMatch(/Discovery работает/);
    expect(s.tone).toBe("informational");
  });

  it("discovery stale with due keys", () => {
    const s = discoveryOperationsSummary(
      {
        ...discoveryBase,
        worker: { ...discoveryBase.worker, activity_state: "stale_activity" },
        keywords_due_now: 89,
      } as DiscoveryOperationsBlock,
      "—",
    );
    expect(s.lines[0].text).toMatch(/давно не запускался/i);
    expect(s.lines[1]?.text).toMatch(/89 ключей/);
  });

  it("monitoring eligible zero with loaded", () => {
    const s = monitoringOperationsSummary(
      {
        loaded_video_count: 10,
        eligible_video_count: 0,
        inserted_snapshot_count: 0,
        worker: { activity_state: "active_recently" },
        last_cycle_status: "ok",
      } as MonitoringOperationsBlock,
      5,
    );
    expect(s.lines[0].text).toMatch(/подходящих под текущие правила/i);
  });

  it("snapshot zero 24h", () => {
    const s = snapshotOperationsSummary({
      snapshots_last_24h: 0,
    } as SnapshotOperationsBlock);
    expect(s.lines[0].text).toMatch(/24 ч нет/i);
  });

  it("outcome zero valid", () => {
    const s = outcome72hOperationsSummary({
      valid_72h_outcome_count: 0,
      matures_next_24h: 0,
      matured_72h_count: 0,
      missing_72h_outcome_count: 0,
    } as KeywordOutcomeOperationsBlock);
    expect(s.lines[0].text).toMatch(/нет валидных 72/i);
  });
});
