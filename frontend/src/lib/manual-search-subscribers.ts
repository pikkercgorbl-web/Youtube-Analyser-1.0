import type { EnrichedVideoModel } from "@/lib/types";

/** Positive subscriber count from channel browse or search card; null if unknown/hidden. */
export function resolveManualSearchSubscribers(item: EnrichedVideoModel): number | null {
  const fromChannel = item.channel.subscribers_count;
  if (fromChannel != null && fromChannel > 0) {
    return fromChannel;
  }
  const fromVideo = item.video.subscribers_count;
  if (fromVideo != null && fromVideo > 0) {
    return fromVideo;
  }
  return null;
}

export function manualSearchSubscriberSkeleton(item: EnrichedVideoModel, pending: boolean): boolean {
  if (!pending) {
    return false;
  }
  if (resolveManualSearchSubscribers(item) !== null) {
    return false;
  }
  return Boolean(item.video.channel_id?.trim());
}
