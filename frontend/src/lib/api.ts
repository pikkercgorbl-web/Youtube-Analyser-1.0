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
import type { TargetKeywordItem } from "./keyword-pool-types";
import type {
  OperationsOverviewParams,
  OperationsOverviewResponse,
} from "./operations-types";
import type { SearchRequestPayload } from "./search-filters";

const api = axios.create({
  baseURL: "",
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

export async function searchVideos(
  payload: SearchRequestPayload,
): Promise<EnrichedVideoModel[]> {
  // Channel enrichment can take a while, so allow a longer timeout than the default.
  const { data } = await api.post<EnrichedVideoModel[]>("/api/search", payload, {
    timeout: 180_000,
  });
  return data;
}

export async function fetchSuggestions(query: string): Promise<string[]> {
  const { data } = await api.get<string[]>("/api/suggestions", {
    params: { query },
  });
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

export default api;
