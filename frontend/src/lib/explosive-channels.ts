import type { ExplosiveChannelItem, ExplosiveChannelSortOption } from "./types";

/** CJK, Arabic, Japanese kana, Korean hangul, Devanagari (Hindi). */
const EXCLUDED_SCRIPT_RE =
  /[\p{Script=Han}\p{Script=Arabic}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}\p{Script=Devanagari}]/u;

export function containsExcludedScripts(text: string): boolean {
  return EXCLUDED_SCRIPT_RE.test(text);
}

export function filterRuEnExplosiveChannels(
  items: ExplosiveChannelItem[],
): ExplosiveChannelItem[] {
  return items.filter((item) => !containsExcludedScripts(item.representative_video_title));
}

export function sortExplosiveChannels(
  items: ExplosiveChannelItem[],
  sortBy: ExplosiveChannelSortOption,
): ExplosiveChannelItem[] {
  const sorted = [...items];

  switch (sortBy) {
    case "video_views_desc":
      return sorted.sort(
        (a, b) => b.representative_video_views - a.representative_video_views,
      );
    case "vph_desc":
      return sorted.sort((a, b) => (b.vph ?? 0) - (a.vph ?? 0));
    default:
      return sorted.sort((a, b) => b.viral_coefficient - a.viral_coefficient);
  }
}

export function formatChannelAgeLabel(days: number): string {
  if (days <= 0) {
    return "Возраст неизвестен";
  }

  const mod10 = days % 10;
  const mod100 = days % 100;
  let suffix = "дней";

  if (mod10 === 1 && mod100 !== 11) {
    suffix = "день";
  } else if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) {
    suffix = "дня";
  }

  return `Создан ${days} ${suffix} назад`;
}

export function youtubeChannelUrl(channelId: string): string {
  return `https://www.youtube.com/channel/${channelId}`;
}

export function youtubeVideoUrl(videoId: string): string {
  return `https://www.youtube.com/watch?v=${videoId}`;
}
