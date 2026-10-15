import type { ChannelSingleAnalysisPublication } from "@/lib/types";

export type RegularSortMode = "newest" | "most_views";

export interface ViewsRankResult {
  rank: number | null;
  groupSize: number;
  regularTotal: number;
  focusInGroup: boolean;
}

export function confirmedRegularPublications(
  publications: ChannelSingleAnalysisPublication[],
): ChannelSingleAnalysisPublication[] {
  return publications.filter((p) => p.kind === "regular" && p.published_at);
}

export function regularWithKnownViews(
  publications: ChannelSingleAnalysisPublication[],
): ChannelSingleAnalysisPublication[] {
  return confirmedRegularPublications(publications).filter((p) => p.views_count > 0);
}

/** Descriptive rank by current views; equal views share the same place. */
export function computeViewsRank(
  focusVideoId: string,
  publications: ChannelSingleAnalysisPublication[],
): ViewsRankResult {
  const regularAll = confirmedRegularPublications(publications);
  const group = regularWithKnownViews(publications);
  const groupSize = group.length;
  const regularTotal = regularAll.length;

  if (!focusVideoId || groupSize === 0) {
    return { rank: null, groupSize, regularTotal, focusInGroup: false };
  }

  const focusInGroup = group.some((p) => p.video_id === focusVideoId);
  if (!focusInGroup) {
    return { rank: null, groupSize, regularTotal, focusInGroup: false };
  }

  const sorted = [...group].sort((a, b) => {
    if (b.views_count !== a.views_count) {
      return b.views_count - a.views_count;
    }
    return a.video_id.localeCompare(b.video_id);
  });

  let rank = 1;
  let prevViews: number | null = null;
  let focusRank: number | null = null;
  for (let i = 0; i < sorted.length; i += 1) {
    const pub = sorted[i];
    if (prevViews === null || pub.views_count < prevViews) {
      rank = i + 1;
      prevViews = pub.views_count;
    }
    if (pub.video_id === focusVideoId) {
      focusRank = rank;
      break;
    }
  }

  return { rank: focusRank, groupSize, regularTotal, focusInGroup: true };
}

export function sortRegularPublications(
  publications: ChannelSingleAnalysisPublication[],
  mode: RegularSortMode,
): ChannelSingleAnalysisPublication[] {
  const regular = confirmedRegularPublications(publications);
  if (mode === "most_views") {
    return [...regular].sort((a, b) => {
      if (b.views_count !== a.views_count) {
        return b.views_count - a.views_count;
      }
      return a.video_id.localeCompare(b.video_id);
    });
  }
  return [...regular].sort((a, b) => {
    const ta = a.published_at ? Date.parse(a.published_at) : 0;
    const tb = b.published_at ? Date.parse(b.published_at) : 0;
    if (tb !== ta) {
      return tb - ta;
    }
    return a.video_id.localeCompare(b.video_id);
  });
}

export function samplePeriodLabel(publications: ChannelSingleAnalysisPublication[]): string | null {
  const dates = publications
    .map((p) => (p.published_at ? Date.parse(p.published_at) : NaN))
    .filter((t) => !Number.isNaN(t));
  if (dates.length === 0) {
    return null;
  }
  const min = new Date(Math.min(...dates));
  const max = new Date(Math.max(...dates));
  const fmt = (d: Date) =>
    d.toLocaleDateString("ru-RU", { day: "numeric", month: "short", year: "numeric" });
  if (min.toDateString() === max.toDateString()) {
    return fmt(min);
  }
  return `${fmt(min)} — ${fmt(max)}`;
}

export function formatViewsRankCaption(result: ViewsRankResult): string | null {
  if (result.rank == null || !result.focusInGroup) {
    return null;
  }
  const base = `По текущим просмотрам: ${result.rank} из ${result.groupSize} в загруженной выборке`;
  if (result.regularTotal > result.groupSize) {
    return `${base} (учтено ${result.groupSize} из ${result.regularTotal} обычных с известными просмотрами)`;
  }
  return base;
}

export function formatAgeHoursLabel(hours: number): string {
  if (hours < 48) {
    return `${Math.round(hours)} ч`;
  }
  const days = hours / 24;
  if (days < 14) {
    return `${Math.round(days)} д`;
  }
  return `${Math.round(days)} д (~${Math.round(hours)} ч)`;
}

export function formatAgeWindowLabel(lowHours: number, highHours: number): string {
  return `${formatAgeHoursLabel(lowHours)} – ${formatAgeHoursLabel(highHours)}`;
}

export function mergePublicationsByVideoId(
  existing: ChannelSingleAnalysisPublication[],
  incoming: ChannelSingleAnalysisPublication[],
): ChannelSingleAnalysisPublication[] {
  const byId = new Map(existing.map((p) => [p.video_id, p]));
  for (const pub of incoming) {
    if (!byId.has(pub.video_id)) {
      byId.set(pub.video_id, pub);
    }
  }
  return Array.from(byId.values());
}
