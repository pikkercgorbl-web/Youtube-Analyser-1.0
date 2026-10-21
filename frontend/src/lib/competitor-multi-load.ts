import { resolveChannelDisplayName, type CompetitorPreviewUserError } from "@/lib/competitor-multi-display";
import { competitorPreviewErrorFromUnknown } from "@/lib/competitor-multi-errors";
import type { CompetitorChannelPreviewResponse } from "@/lib/types";

export const COMPETITOR_MIN_CHANNELS = 2;
export const COMPETITOR_MAX_CHANNELS = 5;
export const COMPETITOR_LOAD_CONCURRENCY = 2;

export type ChannelJobStatus = "queued" | "loading" | "ready" | "partial" | "error";

export interface ChannelLoadJob {
  inputRef: string;
  status: ChannelJobStatus;
  /** Technical detail for logs / disclosure (not shown as primary copy). */
  errorMessage: string | null;
  userError: CompetitorPreviewUserError | null;
  retryLoading: boolean;
  response: CompetitorChannelPreviewResponse | null;
  /** Set when merged into an earlier channel_id slot */
  mergedIntoChannelId: string | null;
}

export interface UniqueChannelView {
  channelId: string;
  /** Raw title from API (may equal channel_id). */
  title: string;
  /** User-facing label for filter and cards. */
  displayTitle: string;
  avatarUrl: string;
  subscribersCount: number | null;
  feedLoadedCount: number;
  regularConfirmedCount: number;
  publications: CompetitorChannelPreviewResponse["publications"];
  loadStatus: "ready" | "partial" | "error";
  enrichmentError: string | null;
  aliasInputRefs: string[];
  periodSourcePubs: CompetitorChannelPreviewResponse["publications"];
}

export function normalizeRefDedupeKey(ref: string): string {
  const trimmed = ref.trim();
  if (!trimmed) {
    return "";
  }
  if (trimmed.startsWith("@")) {
    return trimmed.toLowerCase();
  }
  if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
    try {
      const url = new URL(trimmed);
      url.hash = "";
      return url.href.toLowerCase();
    } catch {
      return trimmed.toLowerCase();
    }
  }
  return trimmed;
}

export function dedupeIdenticalChannelRefs(refs: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of refs) {
    const trimmed = raw.trim();
    if (!trimmed) {
      continue;
    }
    const key = normalizeRefDedupeKey(trimmed);
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    out.push(trimmed);
  }
  return out;
}

export function createInitialJobs(inputRefs: string[]): ChannelLoadJob[] {
  return inputRefs.map((inputRef) => ({
    inputRef,
    status: "queued",
    errorMessage: null,
    userError: null,
    retryLoading: false,
    response: null,
    mergedIntoChannelId: null,
  }));
}

export function buildUniqueChannelViews(jobs: ChannelLoadJob[]): UniqueChannelView[] {
  const byChannelId = new Map<string, UniqueChannelView>();

  for (const job of jobs) {
    if (!job.response) {
      continue;
    }
    const data = job.response;
    const existing = byChannelId.get(data.channel_id);
    if (existing) {
      if (!existing.aliasInputRefs.includes(job.inputRef)) {
        existing.aliasInputRefs.push(job.inputRef);
      }
      existing.publications = mergePubs(existing.publications, data.publications);
      existing.periodSourcePubs = existing.publications;
      if (data.load_status === "partial") {
        existing.loadStatus = "partial";
        existing.enrichmentError = data.enrichment_error ?? existing.enrichmentError;
      }
      existing.regularConfirmedCount = countRegular(existing.publications);
      continue;
    }
    byChannelId.set(data.channel_id, {
      channelId: data.channel_id,
      title: data.channel_title,
      displayTitle: "",
      avatarUrl: data.channel_avatar_url,
      subscribersCount: data.subscribers_count,
      feedLoadedCount: data.feed_loaded_count,
      regularConfirmedCount: data.regular_confirmed_count,
      publications: data.publications,
      loadStatus: data.load_status === "partial" ? "partial" : "ready",
      enrichmentError: data.enrichment_error,
      aliasInputRefs: [job.inputRef],
      periodSourcePubs: data.publications,
    });
  }

  return Array.from(byChannelId.values()).map((view) => ({
    ...view,
    displayTitle: resolveChannelDisplayName({
      channelTitle: view.title,
      channelId: view.channelId,
      inputRefs: view.aliasInputRefs,
    }),
  }));
}

function mergePubs(
  a: CompetitorChannelPreviewResponse["publications"],
  b: CompetitorChannelPreviewResponse["publications"],
) {
  const byId = new Map(a.map((p) => [p.video_id, p]));
  for (const pub of b) {
    if (!byId.has(pub.video_id)) {
      byId.set(pub.video_id, pub);
    }
  }
  return Array.from(byId.values());
}

function countRegular(pubs: CompetitorChannelPreviewResponse["publications"]) {
  return pubs.filter((p) => p.kind === "regular" && p.published_at).length;
}

/** Apply successful preview to jobs list; merge duplicate channel_id into first job. */
export function applyChannelPreviewSuccess(
  jobs: ChannelLoadJob[],
  inputRef: string,
  response: CompetitorChannelPreviewResponse,
): ChannelLoadJob[] {
  const status: ChannelJobStatus = response.load_status === "partial" ? "partial" : "ready";
  const firstIndex = jobs.findIndex(
    (j) => j.response?.channel_id === response.channel_id && !j.mergedIntoChannelId,
  );

  return jobs.map((job) => {
    if (job.inputRef !== inputRef) {
      return job;
    }
    if (firstIndex >= 0 && jobs[firstIndex].inputRef !== inputRef) {
      return {
        ...job,
        status: "ready",
        errorMessage: null,
        userError: null,
        retryLoading: false,
        response,
        mergedIntoChannelId: response.channel_id,
      };
    }
    return {
      ...job,
      status,
      errorMessage: null,
      userError: null,
      retryLoading: false,
      response,
      mergedIntoChannelId: null,
    };
  });
}

export function applyChannelPreviewError(
  jobs: ChannelLoadJob[],
  inputRef: string,
  userError: CompetitorPreviewUserError,
  keepResponse: boolean,
): ChannelLoadJob[] {
  return jobs.map((job) => {
    if (job.inputRef !== inputRef) {
      return job;
    }
    return {
      ...job,
      status: "error",
      errorMessage: userError.technicalDetail,
      userError,
      retryLoading: false,
      response: keepResponse ? job.response : null,
    };
  });
}

/**
 * Runs up to COMPETITOR_LOAD_CONCURRENCY fetches; supports AbortSignal and generation guard.
 */
export async function runCompetitorLoadPool(params: {
  inputRefs: string[];
  generation: number;
  isGenerationCurrent: (generation: number) => boolean;
  getJobGeneration: (inputRef: string) => number;
  fetchOne: (
    inputRef: string,
    signal: AbortSignal,
  ) => Promise<CompetitorChannelPreviewResponse>;
  onJobStart: (inputRef: string) => void;
  onJobSuccess: (inputRef: string, response: CompetitorChannelPreviewResponse) => void;
  onJobError: (inputRef: string, userError: CompetitorPreviewUserError, aborted: boolean) => void;
  abortControllers: Map<string, AbortController>;
}): Promise<void> {
  const queue = [...params.inputRefs];
  let active = 0;

  await new Promise<void>((resolve) => {
    const pump = () => {
      if (!params.isGenerationCurrent(params.generation)) {
        for (const controller of params.abortControllers.values()) {
          controller.abort();
        }
        if (active === 0) {
          resolve();
        }
        return;
      }
      while (active < COMPETITOR_LOAD_CONCURRENCY && queue.length > 0) {
        if (!params.isGenerationCurrent(params.generation)) {
          pump();
          return;
        }
        const inputRef = queue.shift()!;
        const controller = new AbortController();
        params.abortControllers.set(inputRef, controller);
        active += 1;
        params.onJobStart(inputRef);

        void params
          .fetchOne(inputRef, controller.signal)
          .then((response) => {
            if (
              !params.isGenerationCurrent(params.generation) ||
              params.getJobGeneration(inputRef) !== params.generation
            ) {
              return;
            }
            params.onJobSuccess(inputRef, response);
          })
          .catch((err: unknown) => {
            const aborted =
              controller.signal.aborted ||
              (typeof err === "object" &&
                err !== null &&
                "code" in err &&
                (err as { code?: string }).code === "ERR_CANCELED");
            if (
              !params.isGenerationCurrent(params.generation) ||
              params.getJobGeneration(inputRef) !== params.generation
            ) {
              return;
            }
            params.onJobError(inputRef, competitorPreviewErrorFromUnknown(err), aborted);
          })
          .finally(() => {
            params.abortControllers.delete(inputRef);
            active -= 1;
            if (queue.length === 0 && active === 0) {
              resolve();
            } else {
              pump();
            }
          });
      }
      if (queue.length === 0 && active === 0) {
        resolve();
      }
    };
    pump();
  });
}
