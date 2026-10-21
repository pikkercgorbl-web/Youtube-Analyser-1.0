import {
  confirmedRegularPublications,
  type RegularSortMode,
} from "@/lib/channel-single-analysis-overview";
import type { ChannelSingleAnalysisPublication } from "@/lib/types";

export function sortRegularPublicationsUnknownLast(
  publications: ChannelSingleAnalysisPublication[],
  mode: RegularSortMode,
): ChannelSingleAnalysisPublication[] {
  const regular = confirmedRegularPublications(publications);
  if (mode === "most_views") {
    return [...regular].sort((a, b) => {
      const aKnown = a.views_count > 0;
      const bKnown = b.views_count > 0;
      if (aKnown !== bKnown) {
        return aKnown ? -1 : 1;
      }
      if (b.views_count !== a.views_count) {
        return b.views_count - a.views_count;
      }
      return a.video_id.localeCompare(b.video_id);
    });
  }
  return [...regular].sort((a, b) => {
    const ta = a.published_at ? Date.parse(a.published_at) : null;
    const tb = b.published_at ? Date.parse(b.published_at) : null;
    if (ta === null && tb === null) {
      return a.video_id.localeCompare(b.video_id);
    }
    if (ta === null) {
      return 1;
    }
    if (tb === null) {
      return -1;
    }
    if (tb !== ta) {
      return tb - ta;
    }
    return a.video_id.localeCompare(b.video_id);
  });
}

export function mergeChannelPublications(
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
