import axios from "axios";

import type {
  MonitoringCycleListResponse,
  MonitoringCyclesParams,
  MonitoringOverview,
  MonitoringSnapshotsParams,
  MonitoringVideoDetail,
  MonitoringVideoListResponse,
  MonitoringVideosParams,
  MonitoringWorkerStatus,
  MonitoringSnapshot,
} from "./monitoring-types";
import type {  AnomalySearchParams,
  EnrichedVideoModel,
  ExplosiveChannelFilters,
  ExplosiveChannelItem,
  ExtendedSearchResponse,
  ForceRadarScanResponse,
  ClearExplosiveChannelsResponse,
  KeywordAnalyzeResponse,
  KeywordResearchResponse,
  MassAnalysisResponse,
  RadarResetResponse,
  RadarGenerateIdeasResponse,
  RadarContentFormatOptions,
  RadarStatsResponse,
  RadarStatusResponse,
  SavedKeywordItem,
  SavedKeywordPayload,
  YouTubeLeadersResponse,
} from "./types";
import type {
  KeywordPerformanceListParams,
  KeywordPerformanceListResponse,
  KeywordPerformanceMetrics,
} from "./keyword-performance-types";
import type { KeywordPoolSummary, TargetKeywordItem } from "./keyword-pool-types";
import type {
  OperationsOverviewParams,
  OperationsOverviewResponse,
} from "./operations-types";
import type { SearchRequestPayload } from "./search-filters";
import type {
  AttentionChannelListResponse,
  AttentionPatternDetailResponse,
  AttentionPatternFamilyDetailResponse,
  AttentionPatternFamilyListResponse,
  AttentionPatternListResponse,
  AttentionSummaryApiResponse,
  AttentionVideoDetailResponse,
  AttentionVideoListResponse,
} from "./attention-types";
import type {
  SavedTopicDetail,
  SavedTopicFeedback,
  SavedTopicFeedbackPayload,
  SavedTopicHistoryResponse,
  SavedTopicListResponse,
  SavedTopicPatchPayload,
  SavedTopicSaveResponse,
  SavedTopicTimelineResponse,
} from "./saved-topics-types";
import type { ValidationReport } from "./validation-types";
import type {
  SavedFamilyDetail,
  SavedFamilyHistoryResponse,
  SavedFamilyListItem,
  SavedFamilyTopicFindingsList,
  SavedFamilyTopicWatch,
  SavedResearchStatus,
  SavedVideoDetail,
  SavedVideoHistoryResponse,
  SavedVideoListItem,
  SavedVideoManualRefreshResponse,
} from "./saved-research-types";
import type { SavedResearchFeedbackOverview } from "./saved-research-feedback-types";
import type {
  SavedResearchFeedbackHistory,
  SavedResearchFeedbackPayload,
} from "./saved-research-analyst-feedback-types";
import type {
  DailyIntelligenceDateListResponse,
  DailyIntelligenceFamilyDetail,
  DailyIntelligenceFamilyListResponse,
  DailyIntelligenceReportSummary,
  DailyIntelligenceRunListResponse,
  DailyIntelligenceVideoAppearanceListResponse,
  DailyIntelligenceWinnerDetail,
  DailyIntelligenceWinnerListResponse,
} from "./daily-intelligence-types";
import type {
  DailyIntelligenceOutcomeCoverageResponse,
  DailyIntelligenceWinnerOutcomeFollowUp,
} from "./daily-intelligence-outcome-types";

/** Browser calls hit the backend directly to avoid Next.js rewrite proxy timeouts on long searches. */
function resolveClientApiBaseUrl(): string {
  const configured = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/$/, "");
  if (typeof window !== "undefined" && configured) {
    return configured;
  }
  return "";
}

const api = axios.create({
  baseURL: resolveClientApiBaseUrl(),
  timeout: 60_000,
  headers: {
    "Content-Type": "application/json",
    "ngrok-skip-browser-warning": "true",
  },
});
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const message =
      error.response?.data?.detail ??
      error.message ??
      "Произошла ошибка при запросе к серверу";
    return Promise.reject(new Error(typeof message === "string" ? message : JSON.stringify(message)));
  },
);

export async function searchAnomalies(params: AnomalySearchParams): Promise<ExtendedSearchResponse> {
  const { data } = await api.get<ExtendedSearchResponse>("/api/youtube-search/extended", { params });
  return data;
}

export type ManualSearchApiResponse = {
  items: EnrichedVideoModel[];
  needs_channel_enrichment: boolean;
  timing?: Record<string, unknown> | null;
};

export async function searchVideos(
  payload: SearchRequestPayload,
  options?: { phase?: "basic" | "full"; includeTiming?: boolean },
): Promise<ManualSearchApiResponse> {
  const { data } = await api.post<ManualSearchApiResponse>("/api/search", {
    ...payload,
    phase: options?.phase,
    include_timing: options?.includeTiming ?? false,
  }, {
    timeout: 180_000,
  });
  return data;
}

export async function enrichSearchVideos(
  payload: SearchRequestPayload & { items: EnrichedVideoModel[] },
): Promise<ManualSearchApiResponse> {
  const { items, ...rest } = payload;
  const { data } = await api.post<ManualSearchApiResponse>(
    "/api/search/enrich",
    { items, filters: rest.filters, sort_by: rest.sort_by },
    { timeout: 180_000 },
  );
  return data;
}

export async function fetchSuggestions(query: string): Promise<string[]> {
  const { data } = await api.get<string[]>("/api/suggestions", {
    params: { query },
  });
  return data;
}

export async function fetchCompetitorChannelPreview(
  payload: {
    input_ref?: string;
    channel_ref?: string;
    channel_id?: string;
  },
  signal?: AbortSignal,
): Promise<import("@/lib/types").CompetitorChannelPreviewResponse> {
  const { data } = await api.post<import("@/lib/types").CompetitorChannelPreviewResponse>(
    "/api/analysis/competitors/channel",
    {
      input_ref: payload.input_ref ?? null,
      channel_ref: payload.channel_ref ?? null,
      channel_id: payload.channel_id ?? null,
    },
    { timeout: 120_000, signal },
  );
  return data;
}

export async function runMassAnalysis(
  channelRefs: string[],
  videosPerChannel = 30,
): Promise<MassAnalysisResponse> {
  const { data } = await api.post<MassAnalysisResponse>("/api/analysis/mass", {
    channel_refs: channelRefs,
    videos_per_channel: videosPerChannel,
  }, {
    timeout: 300_000,
  });
  return data;
}

export async function fetchChannelSingleShelf(payload: {
  channel_id?: string;
  channel_ref?: string;
}): Promise<import("@/lib/types").ChannelSingleAnalysisShelfResponse> {
  const { data } = await api.post<import("@/lib/types").ChannelSingleAnalysisShelfResponse>(
    "/api/analysis/channel/shelf",
    payload,
    { timeout: 120_000 },
  );
  return data;
}

export async function enrichChannelSingle(payload: {
  channel_id: string;
  focus_video_id?: string;
  publications: import("@/lib/types").ChannelSingleAnalysisPublication[];
}): Promise<import("@/lib/types").ChannelSingleAnalysisEnrichResponse> {
  const { data } = await api.post<import("@/lib/types").ChannelSingleAnalysisEnrichResponse>(
    "/api/analysis/channel/enrich",
    {
      channel_id: payload.channel_id,
      focus_video_id: payload.focus_video_id ?? null,
      publications: payload.publications,
    },
    { timeout: 120_000 },
  );
  return data;
}

export async function fetchChannelSingleShelfMore(payload: {
  channel_id: string;
  existing_video_ids: string[];
  max_total?: number;
}): Promise<import("@/lib/types").ChannelSingleAnalysisShelfMoreResponse> {
  const { data } = await api.post<import("@/lib/types").ChannelSingleAnalysisShelfMoreResponse>(
    "/api/analysis/channel/shelf/more",
    {
      channel_id: payload.channel_id,
      existing_video_ids: payload.existing_video_ids,
      max_total: payload.max_total ?? 100,
    },
    { timeout: 120_000 },
  );
  return data;
}

export async function compareChannelSingleFocus(payload: {
  channel_id: string;
  focus_video_id?: string;
  publications: import("@/lib/types").ChannelSingleAnalysisPublication[];
}): Promise<import("@/lib/types").ChannelSingleCompareResponse> {
  const { data } = await api.post<import("@/lib/types").ChannelSingleCompareResponse>(
    "/api/analysis/channel/compare",
    {
      channel_id: payload.channel_id,
      focus_video_id: payload.focus_video_id ?? null,
      publications: payload.publications,
    },
    { timeout: 45_000 },
  );
  return data;
}

export async function analyzeKeyword(keyword: string): Promise<KeywordAnalyzeResponse> {
  const { data } = await api.get<KeywordAnalyzeResponse>("/api/keywords/analyze", {
    params: { keyword },
  });
  return data;
}

export async function fetchKeywordResearch(query: string): Promise<KeywordResearchResponse> {
  const { data } = await api.get<KeywordResearchResponse>("/api/keyword-research", {
    params: { query },
    timeout: 120_000,
  });
  return data;
}

export async function fetchSavedKeywords(): Promise<SavedKeywordItem[]> {
  const { data } = await api.get<SavedKeywordItem[]>("/api/saved-keywords");
  return data;
}

export async function saveSavedKeyword(payload: SavedKeywordPayload): Promise<SavedKeywordItem> {
  const { data } = await api.post<SavedKeywordItem>("/api/saved-keywords", payload);
  return data;
}

export async function deleteSavedKeyword(id: number): Promise<void> {
  await api.delete(`/api/saved-keywords/${id}`);
}

export async function fetchExplosiveChannels(
  filters: ExplosiveChannelFilters = {},
): Promise<ExplosiveChannelItem[]> {
  const { data } = await api.get<ExplosiveChannelItem[]>("/api/explosive-channels", {
    params: {
      min_views: filters.min_views ?? 50_000,
      min_viral_coeff: filters.min_viral_coeff ?? 3.0,
    },
  });
  return data;
}

export async function forceRadarScan(): Promise<ForceRadarScanResponse> {
  const { data } = await api.post<ForceRadarScanResponse>("/api/force-radar-scan", undefined, {
    timeout: 180_000,
  });
  return data;
}

export async function fetchRadarStatus(): Promise<RadarStatusResponse> {
  const { data } = await api.get<RadarStatusResponse>("/api/radar/status");
  return data;
}

export async function updateRadarSettings(
  uploadPeriod: RadarStatusResponse["upload_period"],
): Promise<RadarStatusResponse> {
  const { data } = await api.put<RadarStatusResponse>("/api/radar/settings", {
    upload_period: uploadPeriod,
  });
  return data;
}

export async function toggleRadar(
  uploadPeriod?: RadarStatusResponse["upload_period"],
  searchQuery?: string,
  blacklistWords?: string[],
  contentFormat?: RadarContentFormatOptions,
): Promise<RadarStatusResponse> {
  const body: {
    upload_period?: RadarStatusResponse["upload_period"];
    search_query?: string;
    blacklist_words?: string[];
    exclude_streams?: boolean;
    exclude_shorts?: boolean;
    exclude_videos?: boolean;
  } = {};

  if (uploadPeriod) {
    body.upload_period = uploadPeriod;
  }

  const trimmedQuery = searchQuery?.trim();
  if (trimmedQuery) {
    body.search_query = trimmedQuery;
  }

  if (blacklistWords && blacklistWords.length > 0) {
    body.blacklist_words = blacklistWords;
  }

  if (contentFormat?.exclude_streams) {
    body.exclude_streams = true;
  }
  if (contentFormat?.exclude_shorts) {
    body.exclude_shorts = true;
  }
  if (contentFormat?.exclude_videos) {
    body.exclude_videos = true;
  }

  const { data } = await api.post<RadarStatusResponse>("/api/radar/toggle", body);
  return data;
}

export async function stopRadarSearch(): Promise<RadarStatusResponse> {
  const { data } = await api.post<RadarStatusResponse>("/api/radar/stop-search");
  return data;
}

export async function clearExplosiveChannels(): Promise<ClearExplosiveChannelsResponse> {
  const { data } = await api.delete<ClearExplosiveChannelsResponse>("/api/explosive-channels");
  return data;
}

export async function resetRadarQueue(): Promise<RadarResetResponse> {
  const { data } = await api.post<RadarResetResponse>("/api/radar/reset");
  return data;
}

export async function fetchRadarStats(): Promise<RadarStatsResponse> {
  const { data } = await api.get<RadarStatsResponse>("/api/radar-stats");
  return data;
}

export async function generateRadarIdeas(
  videoTitles: string[],
): Promise<RadarGenerateIdeasResponse> {
  const { data } = await api.post<RadarGenerateIdeasResponse>("/api/radar/generate-ideas", {
    video_titles: videoTitles,
  });
  return data;
}

export async function fetchYouTubeLeaders(
  windowDays = 7,
  limit = 10,
): Promise<YouTubeLeadersResponse> {
  const { data } = await api.get<YouTubeLeadersResponse>("/api/analysis/leaders", {
    params: { window_days: windowDays, limit },
  });
  return data;
}

export async function getMonitoringStatus(): Promise<MonitoringWorkerStatus> {
  const { data } = await api.get<MonitoringWorkerStatus>("/api/monitoring/status");
  return data;
}

export async function getMonitoringOverview(): Promise<MonitoringOverview> {
  const { data } = await api.get<MonitoringOverview>("/api/monitoring/overview");
  return data;
}

export async function getMonitoringVideos(
  params: MonitoringVideosParams = {},
): Promise<MonitoringVideoListResponse> {
  const { data } = await api.get<MonitoringVideoListResponse>("/api/monitoring/videos", {
    params,
  });
  return data;
}

export async function getMonitoringVideo(videoId: string): Promise<MonitoringVideoDetail> {
  const { data } = await api.get<MonitoringVideoDetail>(`/api/monitoring/videos/${videoId}`);
  return data;
}

export async function getMonitoringSnapshots(
  videoId: string,
  params: MonitoringSnapshotsParams = {},
): Promise<MonitoringSnapshot[]> {
  const { data } = await api.get<MonitoringSnapshot[]>(
    `/api/monitoring/videos/${videoId}/snapshots`,
    { params },
  );
  return data;
}

export async function getMonitoringCycles(
  params: MonitoringCyclesParams = {},
): Promise<MonitoringCycleListResponse> {
  const { data } = await api.get<MonitoringCycleListResponse>("/api/monitoring/cycles", {
    params,
  });
  return data;
}

export type TargetKeywordsListParams = {
  lifecycle_status?: string;
  source_type?: string;
  due_only?: boolean;
};

export async function fetchTargetKeywords(
  params: TargetKeywordsListParams = {},
): Promise<TargetKeywordItem[]> {
  const { data } = await api.get<TargetKeywordItem[]>("/api/keywords", { params });
  return data;
}

export async function fetchKeywordPoolSummary(): Promise<KeywordPoolSummary> {
  const { data } = await api.get<KeywordPoolSummary>("/api/keywords/pool-summary");
  return data;
}

export async function fetchKeywordPerformanceList(
  params: KeywordPerformanceListParams = {},
): Promise<KeywordPerformanceListResponse> {
  const { data } = await api.get<KeywordPerformanceListResponse>("/api/keywords/performance", {
    params,
    timeout: 120_000,
  });
  return data;
}

export async function fetchKeywordPerformanceDetail(
  keywordId: number,
  params: Omit<KeywordPerformanceListParams, "limit"> = {},
): Promise<KeywordPerformanceMetrics> {
  const { data } = await api.get<KeywordPerformanceMetrics>(
    `/api/keywords/${keywordId}/performance`,
    { params, timeout: 120_000 },
  );
  return data;
}

export async function getOperationsOverview(
  params: OperationsOverviewParams = {},
): Promise<OperationsOverviewResponse> {
  const { data } = await api.get<OperationsOverviewResponse>("/api/operations/overview", {
    params: {
      include_live_monitoring_planner: params.include_live_monitoring_planner ?? false,
      outcome_attribution_mode: params.outcome_attribution_mode ?? "all_hits",
      discovery_history_limit: params.discovery_history_limit ?? 10,
      monitoring_history_limit: params.monitoring_history_limit ?? 10,
    },
    timeout: params.include_live_monitoring_planner ? 120_000 : 90_000,
  });
  return data;
}

export async function getAttentionSummary(): Promise<AttentionSummaryApiResponse> {
  const { data } = await api.get<AttentionSummaryApiResponse>("/api/attention/summary");
  return data;
}

export async function getAttentionVideos(params: { limit?: number; offset?: number } = {}): Promise<AttentionVideoListResponse> {
  const { data } = await api.get<AttentionVideoListResponse>("/api/attention/videos", {
    params: { limit: params.limit ?? 50, offset: params.offset ?? 0 },
  });
  return data;
}

export async function getAttentionVideo(videoId: string): Promise<AttentionVideoDetailResponse> {
  const { data } = await api.get<AttentionVideoDetailResponse>(
    `/api/attention/videos/${encodeURIComponent(videoId)}`,
  );
  return data;
}

export async function getAttentionPatterns(params: { limit?: number; offset?: number } = {}): Promise<AttentionPatternListResponse> {
  const { data } = await api.get<AttentionPatternListResponse>("/api/attention/patterns", {
    params: { limit: params.limit ?? 100, offset: params.offset ?? 0 },
  });
  return data;
}

export async function getAttentionChannels(params: { limit?: number; offset?: number } = {}): Promise<AttentionChannelListResponse> {
  const { data } = await api.get<AttentionChannelListResponse>("/api/attention/channels", {
    params: { limit: params.limit ?? 50, offset: params.offset ?? 0 },
  });
  return data;
}

export async function getAttentionPatternDetail(patternKey: string): Promise<AttentionPatternDetailResponse> {
  const { data } = await api.get<AttentionPatternDetailResponse>(
    `/api/attention/patterns/${encodeURIComponent(patternKey)}`,
  );
  return data;
}

export async function getAttentionPatternFamilies(
  params: { limit?: number; offset?: number } = {},
): Promise<AttentionPatternFamilyListResponse> {
  const { data } = await api.get<AttentionPatternFamilyListResponse>("/api/attention/pattern-families", {
    params: { limit: params.limit ?? 100, offset: params.offset ?? 0 },
  });
  return data;
}

export async function getAttentionPatternFamilyDetail(
  familyKey: string,
): Promise<AttentionPatternFamilyDetailResponse> {
  const { data } = await api.get<AttentionPatternFamilyDetailResponse>(
    `/api/attention/pattern-families/${encodeURIComponent(familyKey)}`,
  );
  return data;
}

export async function saveSavedTopic(familyKey: string): Promise<SavedTopicSaveResponse> {
  const { data } = await api.post<SavedTopicSaveResponse>("/api/saved-topics", { family_key: familyKey });
  return data;
}

export async function listSavedTopics(params?: {
  archived?: "active" | "archived" | "all";
  q?: string;
  family_key?: string;
}): Promise<SavedTopicListResponse> {
  const { data } = await api.get<SavedTopicListResponse>("/api/saved-topics", { params });
  return data;
}

export async function getSavedTopic(topicId: number): Promise<SavedTopicDetail> {
  const { data } = await api.get<SavedTopicDetail>(`/api/saved-topics/${topicId}`);
  return data;
}

export async function patchSavedTopic(topicId: number, payload: SavedTopicPatchPayload): Promise<SavedTopicDetail> {
  const { data } = await api.patch<SavedTopicDetail>(`/api/saved-topics/${topicId}`, payload);
  return data;
}

export async function archiveSavedTopic(topicId: number): Promise<SavedTopicDetail> {
  const { data } = await api.post<SavedTopicDetail>(`/api/saved-topics/${topicId}/archive`);
  return data;
}

export async function restoreSavedTopic(topicId: number): Promise<SavedTopicDetail> {
  const { data } = await api.post<SavedTopicDetail>(`/api/saved-topics/${topicId}/restore`);
  return data;
}

export async function getSavedTopicHistory(
  topicId: number,
  params?: { limit?: number; offset?: number },
): Promise<SavedTopicHistoryResponse> {
  const { data } = await api.get<SavedTopicHistoryResponse>(`/api/saved-topics/${topicId}/history`, { params });
  return data;
}

export async function getSavedTopicTimeline(
  topicId: number,
  params?: { limit?: number; offset?: number },
): Promise<SavedTopicTimelineResponse> {
  const { data } = await api.get<SavedTopicTimelineResponse>(`/api/saved-topics/${topicId}/timeline`, { params });
  return data;
}

export async function addSavedTopicFeedback(
  topicId: number,
  payload: SavedTopicFeedbackPayload,
): Promise<SavedTopicFeedback> {
  const { data } = await api.post<SavedTopicFeedback>(`/api/saved-topics/${topicId}/feedback`, payload);
  return data;
}

export async function getValidationReport(params?: {
  period_start?: string;
  period_end?: string;
}): Promise<ValidationReport> {
  const { data } = await api.get<ValidationReport>("/api/validation/report", { params });
  return data;
}

export async function saveSavedVideo(videoId: string): Promise<{ item: SavedVideoDetail; created: boolean; idempotent: boolean }> {
  const { data } = await api.post("/api/saved-videos", { video_id: videoId });
  return data;
}

export type ManualSearchVideoContextItem = {
  video_id: string;
  in_corpus: boolean;
  saved_video_id: number | null;
  snapshot_count: number;
  latest_snapshot_at: string | null;
};

export async function fetchManualSearchVideoContext(
  videoIds: string[],
): Promise<{ items: ManualSearchVideoContextItem[] }> {
  const { data } = await api.post<{ items: ManualSearchVideoContextItem[] }>(
    "/api/manual-search/video-context",
    { video_ids: videoIds },
  );
  return data;
}

export async function saveManualSearchVideo(
  videoId: string,
): Promise<{ item: SavedVideoDetail; created: boolean; idempotent: boolean }> {
  const { data } = await api.post("/api/manual-search/save-video", { video_id: videoId });
  return data;
}

export async function listSavedVideos(params?: {
  archived?: "active" | "archived" | "all";
  status?: string;
  tag?: string;
}): Promise<{ items: SavedVideoListItem[]; total: number }> {
  const { data } = await api.get("/api/saved-videos", { params });
  return data;
}

export async function getSavedVideo(id: number): Promise<SavedVideoDetail> {
  const { data } = await api.get(`/api/saved-videos/${id}`);
  return data;
}

export async function patchSavedVideo(
  id: number,
  payload: { status?: SavedResearchStatus; notes?: string; tags?: string[] },
): Promise<SavedVideoDetail> {
  const { data } = await api.patch(`/api/saved-videos/${id}`, payload);
  return data;
}

export async function archiveSavedVideo(id: number): Promise<SavedVideoDetail> {
  const { data } = await api.post(`/api/saved-videos/${id}/archive`);
  return data;
}

export async function restoreSavedVideo(id: number): Promise<SavedVideoDetail> {
  const { data } = await api.post(`/api/saved-videos/${id}/restore`);
  return data;
}

export async function getSavedVideoHistory(
  id: number,
  params?: { limit?: number; offset?: number },
): Promise<SavedVideoHistoryResponse> {
  const { data } = await api.get<SavedVideoHistoryResponse>(`/api/saved-videos/${id}/history`, {
    params,
  });
  return data;
}

export async function getSavedVideoValidation(id: number): Promise<{
  video_id: string;
  saved_at: string;
  status: SavedResearchStatus;
  validation: Record<string, unknown>;
}> {
  const { data } = await api.get(`/api/saved-videos/${id}/validation`);
  return data;
}

export async function getSavedVideoFeedback(
  id: number,
  params?: { limit?: number; offset?: number },
): Promise<SavedResearchFeedbackHistory> {
  const { data } = await api.get<SavedResearchFeedbackHistory>(`/api/saved-videos/${id}/feedback`, {
    params,
  });
  return data;
}

export async function postSavedVideoFeedback(
  id: number,
  payload: SavedResearchFeedbackPayload,
): Promise<SavedResearchFeedbackHistory["latest"]> {
  const { data } = await api.post(`/api/saved-videos/${id}/feedback`, payload);
  return data;
}

export async function getSavedFamilyValidation(id: number): Promise<{
  family_key: string;
  saved_at: string;
  status: SavedResearchStatus;
  validation: Record<string, unknown>;
}> {
  const { data } = await api.get(`/api/saved-families/${id}/validation`);
  return data;
}

export async function getSavedFamilyFeedback(
  id: number,
  params?: { limit?: number; offset?: number },
): Promise<SavedResearchFeedbackHistory> {
  const { data } = await api.get<SavedResearchFeedbackHistory>(`/api/saved-families/${id}/feedback`, {
    params,
  });
  return data;
}

export async function postSavedFamilyFeedback(
  id: number,
  payload: SavedResearchFeedbackPayload,
): Promise<SavedResearchFeedbackHistory["latest"]> {
  const { data } = await api.post(`/api/saved-families/${id}/feedback`, payload);
  return data;
}

export async function getSavedResearchFeedbackOverview(params?: {
  archived?: "active" | "archived" | "all";
  video_limit?: number;
  video_offset?: number;
  family_limit?: number;
  family_offset?: number;
}): Promise<SavedResearchFeedbackOverview> {
  const { data } = await api.get<SavedResearchFeedbackOverview>(
    "/api/saved-research/feedback-overview",
    { params },
  );
  return data;
}

export async function refreshSavedVideoMetrics(
  id: number,
  body?: { capture_run_id?: string },
): Promise<SavedVideoManualRefreshResponse> {
  const { data } = await api.post(`/api/saved-videos/${id}/refresh-metrics`, body ?? {});
  return data;
}

export async function getSavedVideoSimilarWatch(id: number): Promise<import("./saved-research-types").SavedVideoSimilarWatch> {
  const { data } = await api.get(`/api/saved-videos/${id}/similar-watch`);
  return data;
}

export async function confirmSavedVideoSimilarWatch(
  id: number,
  queries: string[],
): Promise<import("./saved-research-types").SavedVideoSimilarWatch> {
  const { data } = await api.post(`/api/saved-videos/${id}/similar-watch/confirm`, { queries });
  return data;
}

export async function runSavedVideoSimilarWatchNow(id: number): Promise<{
  scan_id: number;
  display_state: string;
}> {
  const { data } = await api.post(`/api/saved-videos/${id}/similar-watch/run-now`);
  return data;
}

export async function pauseSavedVideoSimilarWatch(id: number): Promise<import("./saved-research-types").SavedVideoSimilarWatch> {
  const { data } = await api.post(`/api/saved-videos/${id}/similar-watch/pause`);
  return data;
}

export async function resumeSavedVideoSimilarWatch(id: number): Promise<import("./saved-research-types").SavedVideoSimilarWatch> {
  const { data } = await api.post(`/api/saved-videos/${id}/similar-watch/resume`);
  return data;
}

export async function getSavedVideoSimilarFindings(
  id: number,
  params?: { primary_limit?: number; other_limit?: number },
): Promise<import("./saved-research-types").SavedVideoSimilarFindingsList> {
  const { data } = await api.get(`/api/saved-videos/${id}/similar-watch/findings`, { params });
  return data;
}

export async function saveSimilarFinding(
  savedVideoId: number,
  findingId: number,
): Promise<{ item: import("./saved-research-types").SavedVideoDetail; created: boolean; idempotent: boolean }> {
  const { data } = await api.post(
    `/api/saved-videos/${savedVideoId}/similar-watch/findings/${findingId}/save`,
  );
  return data;
}

export async function setSimilarFindingFeedback(
  savedVideoId: number,
  findingId: number,
  verdict: "fit" | "not_fit",
): Promise<import("./saved-research-types").SavedVideoSimilarFinding> {
  const { data } = await api.post(
    `/api/saved-videos/${savedVideoId}/similar-watch/findings/${findingId}/feedback`,
    { verdict },
  );
  return data;
}

export async function saveSavedFamily(familyKey: string): Promise<{ item: SavedFamilyDetail; created: boolean; idempotent: boolean }> {
  const { data } = await api.post("/api/saved-families", { family_key: familyKey });
  return data;
}

export async function listSavedFamilies(params?: {
  archived?: "active" | "archived" | "all";
  status?: string;
  tag?: string;
}): Promise<{ items: SavedFamilyListItem[]; total: number }> {
  const { data } = await api.get("/api/saved-families", { params });
  return data;
}

export async function getSavedFamily(id: number): Promise<SavedFamilyDetail> {
  const { data } = await api.get(`/api/saved-families/${id}`);
  return data;
}

export async function patchSavedFamily(
  id: number,
  payload: { status?: SavedResearchStatus; notes?: string; tags?: string[] },
): Promise<SavedFamilyDetail> {
  const { data } = await api.patch(`/api/saved-families/${id}`, payload);
  return data;
}

export async function archiveSavedFamily(id: number): Promise<SavedFamilyDetail> {
  const { data } = await api.post(`/api/saved-families/${id}/archive`);
  return data;
}

export async function restoreSavedFamily(id: number): Promise<SavedFamilyDetail> {
  const { data } = await api.post(`/api/saved-families/${id}/restore`);
  return data;
}

export async function getSavedFamilyTopicWatch(id: number): Promise<SavedFamilyTopicWatch> {
  const { data } = await api.get(`/api/saved-families/${id}/topic-watch`);
  return data;
}

export async function confirmSavedFamilyTopicWatch(
  id: number,
  queries: string[],
): Promise<SavedFamilyTopicWatch> {
  const { data } = await api.post(`/api/saved-families/${id}/topic-watch/confirm`, { queries });
  return data;
}

export async function runSavedFamilyTopicWatchNow(id: number): Promise<{
  scan_id: number;
  display_state: string;
}> {
  const { data } = await api.post(`/api/saved-families/${id}/topic-watch/run-now`);
  return data;
}

export async function pauseSavedFamilyTopicWatch(id: number): Promise<SavedFamilyTopicWatch> {
  const { data } = await api.post(`/api/saved-families/${id}/topic-watch/pause`);
  return data;
}

export async function resumeSavedFamilyTopicWatch(id: number): Promise<SavedFamilyTopicWatch> {
  const { data } = await api.post(`/api/saved-families/${id}/topic-watch/resume`);
  return data;
}

export async function getSavedFamilyTopicFindings(
  id: number,
  params?: { limit?: number; offset?: number },
): Promise<SavedFamilyTopicFindingsList> {
  const { data } = await api.get(`/api/saved-families/${id}/topic-watch/findings`, { params });
  return data;
}

export async function saveFamilyTopicFinding(
  savedFamilyId: number,
  findingId: number,
): Promise<{ item: SavedVideoDetail; created: boolean; idempotent: boolean }> {
  const { data } = await api.post(
    `/api/saved-families/${savedFamilyId}/topic-watch/findings/${findingId}/save`,
  );
  return data;
}

export async function getSavedFamilyHistory(
  id: number,
  params?: { limit?: number; offset?: number },
): Promise<SavedFamilyHistoryResponse> {
  const { data } = await api.get<SavedFamilyHistoryResponse>(`/api/saved-families/${id}/history`, {
    params,
  });
  return data;
}

export async function listDailyIntelligenceDates(params?: {
  limit?: number;
  offset?: number;
}): Promise<DailyIntelligenceDateListResponse> {
  const { data } = await api.get<DailyIntelligenceDateListResponse>("/api/daily-intelligence/dates", {
    params,
  });
  return data;
}

export async function getDailyIntelligenceReport(
  reportDate: string,
): Promise<DailyIntelligenceReportSummary> {
  const { data } = await api.get<DailyIntelligenceReportSummary>(
    `/api/daily-intelligence/reports/${encodeURIComponent(reportDate)}`,
  );
  return data;
}

export async function listDailyIntelligenceWinners(
  reportDate: string,
  params?: { limit?: number; offset?: number },
): Promise<DailyIntelligenceWinnerListResponse> {
  const { data } = await api.get<DailyIntelligenceWinnerListResponse>(
    `/api/daily-intelligence/reports/${encodeURIComponent(reportDate)}/winners`,
    { params },
  );
  return data;
}

export async function listDailyIntelligenceFamilies(
  reportDate: string,
  params?: { limit?: number; offset?: number },
): Promise<DailyIntelligenceFamilyListResponse> {
  const { data } = await api.get<DailyIntelligenceFamilyListResponse>(
    `/api/daily-intelligence/reports/${encodeURIComponent(reportDate)}/families`,
    { params },
  );
  return data;
}

export async function listDailyIntelligenceRuns(
  reportDate: string,
  params?: { limit?: number; offset?: number },
): Promise<DailyIntelligenceRunListResponse> {
  const { data } = await api.get<DailyIntelligenceRunListResponse>(
    `/api/daily-intelligence/reports/${encodeURIComponent(reportDate)}/runs`,
    { params },
  );
  return data;
}

export async function getDailyIntelligenceWinner(
  reportDate: string,
  videoId: string,
): Promise<DailyIntelligenceWinnerDetail> {
  const { data } = await api.get<DailyIntelligenceWinnerDetail>(
    `/api/daily-intelligence/reports/${encodeURIComponent(reportDate)}/winners/${encodeURIComponent(videoId)}`,
  );
  return data;
}

export async function getDailyIntelligenceOutcomeCoverage(
  reportDate: string,
): Promise<DailyIntelligenceOutcomeCoverageResponse> {
  const { data } = await api.get<DailyIntelligenceOutcomeCoverageResponse>(
    `/api/daily-intelligence/reports/${encodeURIComponent(reportDate)}/outcome-coverage`,
  );
  return data;
}

export async function getDailyIntelligenceWinnerOutcomeFollowUp(
  reportDate: string,
  videoId: string,
): Promise<DailyIntelligenceWinnerOutcomeFollowUp> {
  const { data } = await api.get<DailyIntelligenceWinnerOutcomeFollowUp>(
    `/api/daily-intelligence/reports/${encodeURIComponent(reportDate)}/winners/${encodeURIComponent(videoId)}/outcome-follow-up`,
  );
  return data;
}

export async function getDailyIntelligenceFamily(
  reportDate: string,
  familyKey: string,
): Promise<DailyIntelligenceFamilyDetail> {
  const { data } = await api.get<DailyIntelligenceFamilyDetail>(
    `/api/daily-intelligence/reports/${encodeURIComponent(reportDate)}/families/${encodeURIComponent(familyKey)}`,
  );
  return data;
}

export async function listDailyIntelligenceVideoAppearances(
  videoId: string,
  params?: { limit?: number; offset?: number },
): Promise<DailyIntelligenceVideoAppearanceListResponse> {
  const { data } = await api.get<DailyIntelligenceVideoAppearanceListResponse>(
    `/api/daily-intelligence/videos/${encodeURIComponent(videoId)}/appearances`,
    { params },
  );
  return data;
}

export async function saveDailyIntelligenceVideoToResearch(
  reportDate: string,
  videoId: string,
): Promise<{ item: SavedVideoDetail; created: boolean; idempotent: boolean }> {
  const { data } = await api.post(
    `/api/daily-intelligence/reports/${encodeURIComponent(reportDate)}/winners/${encodeURIComponent(videoId)}/save-to-research`,
  );
  return data;
}

export async function saveDailyIntelligenceFamilyToResearch(
  reportDate: string,
  familyKey: string,
): Promise<{ item: SavedFamilyDetail; created: boolean; idempotent: boolean }> {
  const { data } = await api.post(
    `/api/daily-intelligence/reports/${encodeURIComponent(reportDate)}/families/${encodeURIComponent(familyKey)}/save-to-research`,
  );
  return data;
}

export default api;
