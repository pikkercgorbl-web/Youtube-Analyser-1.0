export function opportunityWinnerDetailHref(videoId: string): string {
  return `/opportunities/videos/${encodeURIComponent(videoId)}`;
}
