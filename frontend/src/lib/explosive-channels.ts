import type { ExplosiveChannelItem, ExplosiveChannelSortOption } from "./types";

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
