/** Russian labels for YouTube relative publish strings on manual search cards. */

const STREAM_MARKERS = ["streamed", "streaming", "was live", "live now", "premiere", "прямой эфир", "трансляция"];

export function parseDurationSeconds(durationText: string | undefined): number {
  const text = (durationText ?? "").trim();
  if (!text) return 0;
  const parts = text.split(":");
  try {
    if (parts.length === 3) {
      const [h, m, s] = parts.map((p) => parseInt(p, 10));
      return h * 3600 + m * 60 + s;
    }
    if (parts.length === 2) {
      const [m, s] = parts.map((p) => parseInt(p, 10));
      return m * 60 + s;
    }
    if (parts.length === 1) {
      return parseInt(parts[0], 10);
    }
  } catch {
    return 0;
  }
  return 0;
}

function pluralRu(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few;
  return many;
}

/** Reformat known relative patterns; otherwise return source text unchanged. */
export function formatManualSearchAgeLabel(publishedText: string | undefined): string | null {
  const raw = (publishedText ?? "").trim();
  if (!raw) return null;

  const normalized = raw
    .replace(/\u00a0/g, " ")
    .replace(/\u202f/g, " ")
    .trim()
    .toLowerCase();

  if (normalized === "just now" || normalized === "moments ago" || normalized === "только что" || normalized === "сейчас") {
    return "только что";
  }

  const amountPatterns: Array<{ re: RegExp; unit: "minute" | "hour" | "day" | "week" | "month" | "year" }> = [
    { re: /(\d+)\s*(?:minutes?|минут(?:а|ы|у)?|мин\.?)\b/i, unit: "minute" },
    { re: /(\d+)\s*(?:hours?|час(?:а|ов)?)\b/i, unit: "hour" },
    { re: /(\d+)\s*(?:days?|день|дня|дней)\b/i, unit: "day" },
    { re: /(\d+)\s*(?:weeks?|недел(?:я|и|ь|ю|ей)?|недель)\b/i, unit: "week" },
    { re: /(\d+)\s*(?:months?|месяц(?:а|ев)?)\b/i, unit: "month" },
    { re: /(\d+)\s*(?:years?|год(?:а|у)?|лет)\b/i, unit: "year" },
  ];

  for (const { re, unit } of amountPatterns) {
    const match = normalized.match(re);
    if (!match) continue;
    const n = parseInt(match[1], 10);
    if (!Number.isFinite(n)) continue;
    switch (unit) {
      case "minute":
        return `${n} ${pluralRu(n, "минуту", "минуты", "минут")} назад`;
      case "hour":
        return `${n} ${pluralRu(n, "час", "часа", "часов")} назад`;
      case "day":
        return `${n} ${pluralRu(n, "день", "дня", "дней")} назад`;
      case "week":
        return `${n} ${pluralRu(n, "неделю", "недели", "недель")} назад`;
      case "month":
        return `${n} ${pluralRu(n, "месяц", "месяца", "месяцев")} назад`;
      case "year":
        return `${n} ${pluralRu(n, "год", "года", "лет")} назад`;
    }
  }

  const singular: Array<{ re: RegExp; label: string }> = [
    { re: /\b(?:an?|one|один|одна|одну)\s+(?:minute|минут(?:а|у)?)\b/i, label: "1 минуту назад" },
    { re: /\b(?:an?|one|один|одна|одну)\s+(?:hour|час(?:а)?)\b/i, label: "1 час назад" },
    { re: /\b(?:an?|one|один|одна|одну)\s+(?:day|день)\b/i, label: "1 день назад" },
    { re: /\b(?:an?|one|один|одна|одну)\s+(?:week|недел(?:ю|я))\b/i, label: "1 неделю назад" },
    { re: /\b(?:an?|one|один|одна|одну)\s+(?:month|месяц)\b/i, label: "1 месяц назад" },
    { re: /\b(?:an?|one|один|одна|одну)\s+(?:year|год)\b/i, label: "1 год назад" },
  ];
  for (const { re, label } of singular) {
    if (re.test(normalized)) return label;
  }

  return raw;
}

export function formatViewsAndAgeLine(
  viewsCount: number | undefined,
  publishedText: string | undefined,
): string | null {
  const views =
    viewsCount != null && viewsCount > 0
      ? `${new Intl.NumberFormat("ru-RU", { notation: "compact", maximumFractionDigits: 1 }).format(viewsCount)} просмотров`
      : null;
  const age = formatManualSearchAgeLabel(publishedText);
  if (views && age) return `${views} · ${age}`;
  if (views) return views;
  if (age) return age;
  return null;
}

export function isStreamPublishedText(publishedText: string | undefined, title: string | undefined): boolean {
  const published = (publishedText ?? "").toLowerCase();
  const t = (title ?? "").toLowerCase();
  if (STREAM_MARKERS.some((m) => published.includes(m))) return true;
  return t.includes(" live") || t.endsWith(" live");
}
