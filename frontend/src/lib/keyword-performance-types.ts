/** Keyword performance read API (Stage 1.18B / 1.18D1). Descriptive only — no keyword score. */

export type KeywordAttributionMode = "all_hits" | "first_discovery";

export type KeywordPerformanceMetricFamily = "discovery" | "breakout" | "outcomes" | "full";

export interface KeywordPerformanceEvidenceDetail {
  scan_count: number;
  unique_video_count: number;
  breakout_eligible_video_count: number;
  observed_72h_video_count: number;
}

export interface KeywordPerformanceMetrics {
  keyword_id: number;
  keyword: string;
  lifecycle_status: string | null;
  source_type: string | null;
  last_checked: string | null;
  next_scan_at: string | null;
  scan_interval_seconds: number | null;
  is_due: boolean | null;
  overdue_seconds: number | null;
  scheduling_hint: string | null;
  scan_count: number;
  first_scan_at: string | null;
  last_scan_at: string | null;
  discovery_hit_count: number;
  unique_video_count: number;
  unique_channel_count: number;
  within_keyword_duplicate_hit_count: number;
  cross_keyword_duplicate_count: number;
  already_known_video_count: number;
  duplicate_hit_count: number;
  duplicate_rate: number | null;
  regular_video_count: number;
  short_count: number;
  live_count: number;
  qualification_passed_count: number;
  qualification_rejected_count: number;
  qualification_pass_rate: number | null;
  persisted_for_monitoring_count: number;
  monitored_video_count: number;
  videos_with_snapshot_count: number;
  videos_with_snapshot_24h_count: number;
  videos_with_snapshot_48h_count: number;
  videos_with_snapshot_72h_count: number;
  t24_outcome_count: number;
  t48_outcome_count: number;
  t72_outcome_count: number;
  /** Legacy alias — display as top-decile breakout only. */
  confirmed_breakout_count: number;
  videos_per_scan: number | null;
  unique_videos_per_scan: number | null;
  evaluated_at: string | null;
  attribution_mode: string | null;
  ranking_version: string | null;
  global_eligible_video_count: number | null;
  horizon_hours: number | null;
  horizon_snapshot_tolerance_hours: number | null;
  new_to_corpus_video_count: number | null;
  shared_video_count: number | null;
  exclusive_first_discovery_count: number | null;
  attributed_video_count: number | null;
  monitorable_video_count: number | null;
  breakout_eligible_video_count: number | null;
  breakout_ranked_video_count: number | null;
  top_decile_breakout_count: number | null;
  top_decile_breakout_rate: number | null;
  median_vph_at_discovery: number | null;
  p90_vph_at_discovery: number | null;
  median_current_vph: number | null;
  observed_72h_video_count: number | null;
  missing_72h_video_count: number | null;
  median_absolute_view_growth_72h: number | null;
  evidence_status: string | null;
  evidence_detail: KeywordPerformanceEvidenceDetail | null;
}

export interface KeywordPerformanceListResponse {
  items: KeywordPerformanceMetrics[];
  limit: number;
  evaluated_at: string | null;
  attribution_mode: string | null;
  window_from: string | null;
  window_to: string | null;
  ranking_version: string | null;
  global_eligible_video_count: number | null;
  horizon_hours: number | null;
  horizon_snapshot_tolerance_hours: number | null;
}

export interface KeywordPerformanceListParams {
  limit?: number;
  attribution_mode?: KeywordAttributionMode;
  include_breakout?: boolean;
  include_delayed?: boolean;
  from_timestamp?: string;
  to_timestamp?: string;
}

export function metricFamilyFetchFlags(
  family: KeywordPerformanceMetricFamily,
): Pick<KeywordPerformanceListParams, "include_breakout" | "include_delayed"> {
  switch (family) {
    case "discovery":
      return { include_breakout: false, include_delayed: false };
    case "breakout":
      return { include_breakout: true, include_delayed: false };
    case "outcomes":
      return { include_breakout: false, include_delayed: true };
    case "full":
      return { include_breakout: true, include_delayed: true };
  }
}

export function cacheKeyForPerformance(
  family: KeywordPerformanceMetricFamily,
  attribution: KeywordAttributionMode,
  limit: number,
): string {
  return `${family}:${attribution}:${limit}`;
}
