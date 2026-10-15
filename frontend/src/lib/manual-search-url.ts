export function buildManualSearchFromSavedUrl(params: {
  sourceSavedId: number;
  sourceVideoId: string;
  initialQuery: string;
}): string {
  const search = new URLSearchParams();
  search.set("from_saved", "1");
  search.set("source_saved_id", String(params.sourceSavedId));
  search.set("source_video_id", params.sourceVideoId);
  if (params.initialQuery.trim()) {
    search.set("q", params.initialQuery.trim());
  }
  return `/?${search.toString()}`;
}
