/**
 * Legacy product routes (outside v1 sidebar). See docs/acceptance/app_inventory.md §1.15.
 * Backend APIs remain; this module only documents UX replacements.
 */

export type LegacyRouteId =
  | "explosive-channels"
  | "leaders"
  | "anomalies"
  | "keyword-analyze"
  | "keyword-research"
  | "saved-keywords"
  | "saved-topics";

/** Permanent UX redirects (also declared in next.config.mjs). */
export const LEGACY_ROUTE_REDIRECTS: Partial<Record<LegacyRouteId, string>> = {
  "explosive-channels": "/opportunities#section=channels",
  leaders: "/opportunities#section=channels",
  anomalies: "/",
  "keyword-analyze": "/keyword-performance",
};

/** Routes kept for bookmarks / legacy data — no automatic redirect. */
export const LEGACY_ROUTES_ARCHIVED_UI: LegacyRouteId[] = [
  "keyword-research",
  "saved-keywords",
  "saved-topics",
];

export const LEGACY_ARCHIVED_BANNER_TITLE = "Устаревший раздел";

export function legacyArchivedBannerLead(route: LegacyRouteId): string {
  switch (route) {
    case "keyword-research":
      return "SEO-подбор идей ключей. Актуальный цикл discovery и отдача — в «Поисковые запросы» и «Отдача запросов».";
    case "saved-keywords":
      return "Закладки идей из старого keyword-research. Новые исследования сохраняйте через «Сохранённое» (видео и темы).";
    case "saved-topics":
      return "Старый формат закладок тем (saved_topics). Новые темы сохраняйте в «Сохранённое» → вкладка «Темы» (/saved).";
    default:
      return "Этот раздел не входит в основной продукт Radar v1.";
  }
}
