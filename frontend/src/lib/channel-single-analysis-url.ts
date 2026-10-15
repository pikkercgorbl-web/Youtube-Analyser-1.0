export function buildChannelSingleAnalysisUrl(params: {
  channelId: string;
  focusVideoId?: string;
}): string {
  const search = new URLSearchParams();
  search.set("channel_id", params.channelId);
  if (params.focusVideoId?.trim()) {
    search.set("focus_video_id", params.focusVideoId.trim());
  }
  return `/mass-analysis/channel?${search.toString()}`;
}

export function buildChannelSingleAnalysisFromRefUrl(channelRef: string): string {
  const search = new URLSearchParams();
  search.set("channel_ref", channelRef.trim());
  return `/mass-analysis/channel?${search.toString()}`;
}
