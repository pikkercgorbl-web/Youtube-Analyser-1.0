import type { MonitoringCycle } from "@/lib/monitoring-types";

export type PartialPrimaryCause =
  | "none"
  | "missing_only"
  | "execution_errors"
  | "mixed";

export function monitoringExecutionErrorCount(cycle: {
  fetch_failed: number;
  validation_failed: number;
  persistence_failed: number;
}): number {
  return cycle.fetch_failed + cycle.validation_failed + cycle.persistence_failed;
}

export function cyclePartialPrimaryCause(cycle: MonitoringCycle): PartialPrimaryCause {
  const cause = cycle.partial_primary_cause;
  if (
    cause === "missing_only" ||
    cause === "execution_errors" ||
    cause === "mixed"
  ) {
    return cause;
  }
  if (cycle.cycle_status !== "partial") {
    return "none";
  }
  const missing = cycle.missing;
  const errors = monitoringExecutionErrorCount(cycle);
  if (missing > 0 && errors === 0) {
    return "missing_only";
  }
  if (missing === 0 && errors > 0) {
    return "execution_errors";
  }
  if (missing > 0 && errors > 0) {
    return "mixed";
  }
  return "none";
}

export function latestCycleAsPresentationRow(cycle: {
  run_id: string;
  started_at: string;
  finished_at: string | null;
  runtime_seconds: number;
  cycle_status: string;
  loaded_video_count: number;
  selected_request_count: number;
  inserted_snapshot_count: number;
  duplicate_snapshot_count: number;
  missing_count: number;
  fetch_failed_count: number;
  validation_failed_count: number;
  persistence_failed_count: number;
  execution_error_count?: number;
  partial_primary_cause?: string;
  cycle_status_detail?: string | null;
}): MonitoringCycle {
  return {
    run_id: cycle.run_id,
    started_at: cycle.started_at,
    finished_at: cycle.finished_at,
    runtime_seconds: cycle.runtime_seconds,
    cycle_status: cycle.cycle_status,
    loaded: cycle.loaded_video_count,
    tier_a: 0,
    tier_b: 0,
    tier_c: 0,
    due: 0,
    overdue: 0,
    selected: cycle.selected_request_count,
    deferred: 0,
    inserted: cycle.inserted_snapshot_count,
    missing: cycle.missing_count,
    fetch_failed: cycle.fetch_failed_count,
    validation_failed: cycle.validation_failed_count,
    persistence_failed: cycle.persistence_failed_count,
    duplicate_snapshot_count: cycle.duplicate_snapshot_count,
    execution_error_count: cycle.execution_error_count,
    partial_primary_cause: cycle.partial_primary_cause,
    cycle_status_detail: cycle.cycle_status_detail,
  };
}

export function cycleStatusDetailLabel(cycle: MonitoringCycle): string | null {
  if (cycle.cycle_status_detail?.trim()) {
    return cycle.cycle_status_detail.trim();
  }
  const cause = cyclePartialPrimaryCause(cycle);
  if (cause === "missing_only") {
    return `Видео не вернулось в ответе API (missing: ${cycle.missing}), остальные снимки сохранены.`;
  }
  if (cause === "execution_errors") {
    const n = monitoringExecutionErrorCount(cycle);
    return `Ошибки захвата данных: ${n}.`;
  }
  if (cause === "mixed") {
    return `Missing: ${cycle.missing}, ошибки захвата: ${monitoringExecutionErrorCount(cycle)}.`;
  }
  return null;
}
