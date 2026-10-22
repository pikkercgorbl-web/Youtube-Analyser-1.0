/** YouTube video_id from Radar DB (11-char id). */
const YOUTUBE_VIDEO_ID_RE = /^[a-zA-Z0-9_-]{11}$/;

export function isValidYoutubeVideoId(videoId: string | null | undefined): boolean {
  if (!videoId) {
    return false;
  }
  return YOUTUBE_VIDEO_ID_RE.test(videoId.trim());
}

export function dailyIntelligenceThumbnailUrl(videoId: string): string | null {
  const id = videoId.trim();
  if (!isValidYoutubeVideoId(id)) {
    return null;
  }
  return `https://i.ytimg.com/vi/${id}/mqdefault.jpg`;
}
