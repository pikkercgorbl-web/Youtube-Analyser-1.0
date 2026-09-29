export type MonitoringWorkerState = "running" | "stopped" | "stale" | "unknown";

export interface MonitoringWorkerStatus {
  status: MonitoringWorkerState;
  lock_holder: string | null;
  lock_acquired_at: string | null;
  worker_interval_seconds: number;
  stale_after_seconds: number;
  last_seen: string | null;
  is_lock_stale: boolean;
  current_time: string;
}

export interface MonitoringLatestCycle {
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
}

export interface MonitoringOverview {
  active_monitored_count: number;
  tier_counts: Record<string, number>;
  unmonitored_count: number;
  due_count: number;
  overdue_count: number;
  pending_count: number;
  stopped_count: number;
  latest_cycle: MonitoringLatestCycle | null;
}

export interface MonitoringVideoListItem {
  video_id: string;
  channel_id: string;
  title: string | null;
  channel_title: string | null;
  tier: string;
  current_views: number | null;
  current_vph: number | null;
  age_hours: number | null;
  published_at: string;
  latest_snapshot_at: string | null;
  next_checkpoint_hours: number | null;
  monitoring_status: string;
  due_checkpoint_hours: number[];
  overdue_checkpoint_hours: number[];
  baseline_status: string | null;
  vph_vs_channel_median: number | null;
  content_format: string | null;
  breakout_rank?: number | null;
  breakout_rank_version?: string | null;
  breakout_ranking_signal?: string | null;
  breakout_ranking_value?: number | null;
  breakout_ranking_reason?: string | null;
  breakout_ranking_excluded_reason?: string | null;
  in_active_capture_pool?: boolean | null;
}

export interface MonitoringVideoListResponse {
  items: MonitoringVideoListItem[];
  total: number;
  limit: number;
  offset: number;
}

export type MonitoringVideoSort =
  | "priority"
  | "breakout_v1"
  | "vph_desc"
  | "views_desc"
  | "age_asc"
  | "latest_snapshot_desc";

export type MonitoringVideoStatusFilter =
  | "due"
  | "overdue"
  | "pending"
  | "active"
  | "stopped";

export interface MonitoringVideosParams {
  tier?: "A" | "B" | "C";
  status?: MonitoringVideoStatusFilter;
  channel_id?: string;
  keyword?: string;
  sort?: MonitoringVideoSort;
  limit?: number;
  offset?: number;
}

export interface MonitoringCheckpoint {
  target_age_hours: number;
  status: string;
  matched_snapshot_age_hours: number | null;
  due_since_hours: number | null;
  expires_at_age_hours: number;
  recommended_action: string;
}

export interface MonitoringChannelBaseline {
  baseline_status: string;
  comparable_video_count: number | null;
  median_vph: number | null;
  p75_vph: number | null;
  p90_vph: number | null;
  vph_vs_channel_median: number | null;
  vph_vs_channel_p75: number | null;
}

export interface MonitoringVideoDetail {
  video_id: string;
  channel_id: string;
  title: string | null;
  channel_title: string | null;
  published_at: string;
  content_format: string | null;
  views: number | null;
  subscribers: number | null;
  vph: number | null;
  views_per_subscriber: number | null;
  age_hours: number | null;
  tier: string;
  monitoring_status: string;
  checkpoints: MonitoringCheckpoint[];
  next_checkpoint_hours: number | null;
  stop_reason: string | null;
  channel_baseline: MonitoringChannelBaseline | null;
}

export interface MonitoringSnapshot {
  captured_at: string;
  age_hours: number | null;
  views: number | null;
  likes: number | null;
  comments: number | null;
  subscribers: number | null;
  vph: number | null;
  views_per_subscriber: number | null;
  source: string;
  run_id: string;
  fetch_status: string | null;
}

export interface MonitoringCycle {
  run_id: string;
  started_at: string;
  finished_at: string | null;
  runtime_seconds: number;
  cycle_status: string;
  loaded: number;
  tier_a: number;
  tier_b: number;
  tier_c: number;
  due: number;
  overdue: number;
  selected: number;
  deferred: number;
  inserted: number;
  missing: number;
  fetch_failed: number;
  validation_failed: number;
  persistence_failed: number;
  duplicate_snapshot_count: number;
}

export interface MonitoringCycleListResponse {
  items: MonitoringCycle[];
  limit: number;
}

export interface MonitoringSnapshotsParams {
  limit?: number;
  from?: string;
  to?: string;
}

export interface MonitoringCyclesParams {
  limit?: number;
  status?: string;
}
