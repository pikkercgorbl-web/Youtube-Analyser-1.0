export type ActivityState = "active_recently" | "stale_activity" | "unknown" | "error";

export type OutcomeAttributionMode = "all_hits" | "first_discovery";

export interface WorkerActivityBlock {
  lock_status: string | null;
  lock_holder: string | null;
  lock_acquired_at: string | null;
  last_activity_at: string | null;
  activity_state: ActivityState;
  expected_interval_seconds: number;
  stale_lock_minutes: number;
  liveness_note: string;
}

export interface DiscoveryCycleOps {
  discovery_run_id: string;
  started_at: string | null;
  finished_at: string | null;
  runtime_seconds: number | null;
  keywords_scanned: number;
  raw_candidates: number;
  unique_candidates: number;
  persisted_videos: number;
  qualification_passed: number;
  qualification_rejected: number;
  keyword_scan_failures: number;
  error_summaries: string[];
}

export interface DiscoveryOperationsBlock {
  worker: WorkerActivityBlock;
  last_cycle_started_at: string | null;
  last_cycle_finished_at: string | null;
  last_cycle_status: string | null;
  last_run_id: string | null;
  last_error: string | null;
  last_cycle_runtime_seconds: number | null;
  keywords_scanned_last_cycle: number;
  raw_candidates_last_cycle: number;
  unique_videos_last_cycle: number;
  persisted_videos_last_cycle: number;
  keyword_errors_last_cycle: number;
  keywords_due_now: number;
  keywords_due_next_1h: number;
  keywords_due_next_24h: number;
  keywords_due_next_24h_includes_1h: boolean;
}

export interface MonitoringOperationsBlock {
  worker: WorkerActivityBlock;
  last_cycle_started_at: string | null;
  last_cycle_finished_at: string | null;
  last_cycle_status: string | null;
  last_run_id: string | null;
  last_cycle_runtime_seconds: number | null;
  loaded_video_count: number;
  eligible_video_count: number;
  selected_capture_count: number;
  inserted_snapshot_count: number;
  missing_count: number;
  fetch_failed_count: number;
  validation_failed_count: number;
  persistence_failed_count: number;
  due_count_at_last_cycle: number;
  overdue_count_at_last_cycle: number;
  live_planner_due_count: number | null;
  live_planner_overdue_count: number | null;
  live_planner_requested: boolean;
}

export interface SnapshotDailyCount {
  date: string;
  count: number;
}

export interface SnapshotOperationsBlock {
  latest_snapshot_at: string | null;
  snapshots_last_1h: number;
  snapshots_last_24h: number;
  unique_videos_snapshotted_last_24h: number;
  daily_counts_last_7d: SnapshotDailyCount[];
}

export interface KeywordOutcomeOperationsBlock {
  attribution_mode: OutcomeAttributionMode;
  horizon_hours: number;
  tolerance_hours: number;
  attributed_observation_count: number;
  pending_72h_count: number;
  matured_72h_count: number;
  valid_72h_outcome_count: number;
  missing_72h_outcome_count: number;
  matures_next_6h: number;
  matures_next_24h: number;
  matures_next_48h: number;
}

export interface OperationsErrorsBlock {
  discovery_last_cycle_error: string | null;
  monitoring_recent_error_summaries: string[];
}

export interface MonitoringCycleHistoryItem {
  run_id: string;
  started_at: string;
  finished_at: string | null;
  runtime_seconds: number;
  cycle_status: string;
  loaded_video_count: number;
  selected_request_count: number;
  inserted_snapshot_count: number;
  missing_count: number;
  fetch_failed_count: number;
  validation_failed_count: number;
  persistence_failed_count: number;
  due_count: number;
  overdue_count: number;
  error_summary: string | null;
}

export interface RecentCyclesBlock {
  discovery: DiscoveryCycleOps[];
  monitoring: MonitoringCycleHistoryItem[];
}

export interface OperationsOverviewResponse {
  generated_at: string;
  discovery: DiscoveryOperationsBlock;
  monitoring: MonitoringOperationsBlock;
  snapshots: SnapshotOperationsBlock;
  keyword_outcomes: KeywordOutcomeOperationsBlock;
  errors: OperationsErrorsBlock;
  recent_cycles: RecentCyclesBlock;
}

export interface OperationsOverviewParams {
  include_live_monitoring_planner?: boolean;
  discovery_history_limit?: number;
  monitoring_history_limit?: number;
  outcome_attribution_mode?: OutcomeAttributionMode;
}
