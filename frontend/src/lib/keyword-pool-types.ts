export type TargetKeywordLifecycleStatus = "probation" | "active" | "weak" | "archived" | string;

export type TargetKeywordSourceType =
  | "seed"
  | "manual"
  | "suggestion"
  | "related"
  | "channel"
  | "llm"
  | string;

export type TargetKeywordItem = {
  id: number;
  keyword: string;
  created_at: string;
  last_checked: string | null;
  lifecycle_status: TargetKeywordLifecycleStatus;
  scan_interval_seconds: number | null;
  next_scan_at: string | null;
  status_changed_at: string | null;
  status_reason: string | null;
  source_type: TargetKeywordSourceType;
  parent_keyword_id: number | null;
};

export type PoolDueFilter = "all" | "due" | "next_24h" | "unscheduled_or_archived";

export type PoolLifecycleFilter = "all" | TargetKeywordLifecycleStatus;

export type PoolSourceFilter = "all" | TargetKeywordSourceType;

export type PoolSortKey = "next_scan_at" | "keyword" | "lifecycle" | "last_checked";

export type KeywordPoolSummary = {
  snapshot_at: string;
  due_now: number;
  due_next_1h: number;
  due_next_24h: number;
  not_archived_count: number;
  unique_keywords_scanned_last_24h: number;
  keyword_scan_runs_last_24h: number;
  probation_interval_hours: number;
  active_interval_hours: number;
  weak_interval_hours: number;
  failed_scan_retry_hours: number;
};

export type PoolMetrics = {
  total: number;
  working: number;
  probation: number;
  active: number;
  weak: number;
  archived: number;
  dueNow: number;
  scheduledNext24h: number;
};
