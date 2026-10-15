export type DailyIntelligenceReportStatus =
  | "provisional"
  | "complete"
  | "partial"
  | "unavailable";

export type DailyIntelligenceReportDateItem = {
  report_date: string;
  status: DailyIntelligenceReportStatus | string;
  source_run_id: string | null;
  source_computed_at: string | null;
  source_window_start: string | null;
  source_window_end: string | null;
  source_window_hours: number | null;
  generated_at: string;
  locked_at: string | null;
  publish_attempt: number;
  winner_count: number | null;
  family_count: number | null;
};

export type DailyIntelligenceDateListResponse = {
  items: DailyIntelligenceReportDateItem[];
  total: number;
  limit: number;
  offset: number;
};

export type DailyIntelligenceReportSummary = DailyIntelligenceReportDateItem & {
  coverage_gaps: string[];
  summary: Record<string, unknown>;
};

export type DailyIntelligenceWinnerListItem = {
  video_id: string;
  rank: number;
  title: string;
  channel_id: string;
  channel_title: string;
  youtube_url: string;
  is_repeat_in_prior_reports: boolean;
  discovery_provenance_available: boolean | null;
};

export type DailyIntelligenceWinnerListResponse = {
  items: DailyIntelligenceWinnerListItem[];
  total: number;
  limit: number;
  offset: number;
};

export type DailyIntelligenceFamilyListItem = {
  family_key: string;
  rank: number;
  label: string;
  video_count: number | null;
  channel_count: number | null;
  is_repeat_in_prior_reports: boolean;
};

export type DailyIntelligenceFamilyListResponse = {
  items: DailyIntelligenceFamilyListItem[];
  total: number;
  limit: number;
  offset: number;
};

export type DailyIntelligenceRunSnapshotItem = {
  source_run_id: string;
  source_computed_at: string;
  captured_at: string;
  winner_count: number;
  family_count: number;
};

export type DailyIntelligenceRunListResponse = {
  items: DailyIntelligenceRunSnapshotItem[];
  total: number;
  limit: number;
  offset: number;
};

export type DailyIntelligenceWinnerDetail = DailyIntelligenceWinnerListItem & {
  discovery_provenance: Record<string, unknown>;
  evidence: Record<string, unknown>;
};

export type DailyIntelligenceFamilyDetail = DailyIntelligenceFamilyListItem & {
  evidence: Record<string, unknown>;
};

export type DailyIntelligenceVideoAppearanceItem = {
  source_run_id: string;
  report_date: string;
  source_computed_at: string;
  rank: number;
  video_id: string;
  title: string;
  discovery_provenance: Record<string, unknown>;
};

export type DailyIntelligenceVideoAppearanceListResponse = {
  items: DailyIntelligenceVideoAppearanceItem[];
  total: number;
  limit: number;
  offset: number;
};
