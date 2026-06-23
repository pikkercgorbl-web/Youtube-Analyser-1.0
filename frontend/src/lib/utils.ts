import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat("ru-RU").format(value);
}

export function formatCompactNumber(value: number): string {
  return new Intl.NumberFormat("ru-RU", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

export function formatPercent(value: number, digits = 0): string {
  return `${value.toFixed(digits)}%`;
}

export function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function youtubeThumbnail(videoId: string): string {
  return `https://img.youtube.com/vi/${videoId}/mqdefault.jpg`;
}

export function youtubeVideoUrl(videoId: string): string {
  return `https://www.youtube.com/watch?v=${videoId}`;
}

export function parseChannelRefs(raw: string): string[] {
  return raw
    .split(/[\n,]+/)
    .map((line) => line.trim())
    .filter(Boolean);
}

export function viralityColor(percent: number): string {
  if (percent >= 2000) return "from-rose-500 to-orange-500";
  if (percent >= 1000) return "from-amber-500 to-yellow-400";
  if (percent >= 500) return "from-emerald-500 to-teal-400";
  return "from-blue-500 to-cyan-400";
}

export function scoreColor(score: number): string {
  if (score >= 75) return "text-emerald-400";
  if (score >= 50) return "text-amber-400";
  return "text-rose-400";
}

export type KeywordScoreVariant = "volume" | "competition" | "overall";

export function keywordScoreBarColor(score: number, variant: KeywordScoreVariant): string {
  if (variant === "competition") {
    if (score <= 30) return "bg-emerald-500";
    if (score <= 70) return "bg-amber-400";
    return "bg-rose-500";
  }

  if (variant === "overall") {
    if (score <= 40) return "bg-rose-500";
    if (score <= 70) return "bg-amber-400";
    return "bg-emerald-500";
  }

  if (score <= 30) return "bg-rose-500";
  if (score <= 70) return "bg-amber-400";
  return "bg-emerald-500";
}

export function keywordScoreTextColor(score: number, variant: KeywordScoreVariant): string {
  if (variant === "competition") {
    if (score <= 30) return "text-emerald-400";
    if (score <= 70) return "text-amber-400";
    return "text-rose-400";
  }

  if (variant === "overall") {
    if (score <= 40) return "text-rose-400";
    if (score <= 70) return "text-amber-400";
    return "text-emerald-400";
  }

  if (score <= 30) return "text-rose-400";
  if (score <= 70) return "text-amber-400";
  return "text-emerald-400";
}

export function parseCommaWords(raw: string): string[] {
  return raw
    .split(",")
    .map((word) => word.trim().toLowerCase())
    .filter(Boolean);
}

export function competitionLevelLabel(score: number): {
  label: string;
  variant: "success" | "warning" | "danger";
} {
  if (score <= 30) return { label: "Низкая", variant: "success" };
  if (score <= 70) return { label: "Средняя", variant: "warning" };
  return { label: "Высокая", variant: "danger" };
}

export function overallLevelLabel(score: number): {
  label: string;
  variant: "success" | "warning" | "danger";
} {
  if (score <= 40) return { label: "Низкая", variant: "danger" };
  if (score <= 70) return { label: "Средняя", variant: "warning" };
  return { label: "Высокая", variant: "success" };
}

const QUESTION_PREFIX =
  /^(как|что|где|когда|почему|зачем|сколько|можно ли|нужно ли|что такое|who|what|how|why|where|when)\b/i;

export function isQuestionQuery(keyword: string): boolean {
  const trimmed = keyword.trim();
  return trimmed.includes("?") || QUESTION_PREFIX.test(trimmed);
}

export function getMainQueryWords(mainKeyword: string): string[] {
  return mainKeyword
    .toLowerCase()
    .split(/\s+/)
    .map((word) => word.trim())
    .filter((word) => word.length > 2);
}
