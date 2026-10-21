import type { KeywordPerformanceListResponse, KeywordPerformanceMetrics } from "@/lib/keyword-performance-types";
import { formatDateTimeLocal } from "@/lib/monitoring-format";

export function formatKeywordPerformancePeriod(
  windowFrom: string | null | undefined,
  windowTo: string | null | undefined,
): string {
  if (windowFrom || windowTo) {
    const from = windowFrom ? formatDateTimeLocal(windowFrom) : "…";
    const to = windowTo ? formatDateTimeLocal(windowTo) : "…";
    return `период ${from} — ${to}`;
  }
  return "накопительно за всё время наблюдения";
}

export function formatKeywordPerformanceDataSource(source: string | null | undefined): string {
  switch (source) {
    case "snapshot":
      return "предрасчётный снимок";
    case "live_evaluation":
      return "оценка на лету";
    case "unavailable":
      return "снимок недоступен";
    default:
      return source?.trim() ? source : "неизвестный источник";
  }
}

export function keywordPerformanceListContextLines(
  response: Pick<
    KeywordPerformanceListResponse,
    | "data_source"
    | "evaluated_at"
    | "window_from"
    | "window_to"
    | "ranking_version"
    | "attribution_mode"
  >,
): string[] {
  const lines: string[] = [];
  const period = formatKeywordPerformancePeriod(response.window_from, response.window_to);
  const source = formatKeywordPerformanceDataSource(response.data_source);

  if (response.data_source === "unavailable") {
    lines.push(
      "Метрики недоступны: снимок отдачи запросов ещё не построен. Запустите обновление read-model (без перезапуска workers).",
    );
    return lines;
  }

  lines.push(
    `Показатели ${period} · источник: ${source}${
      response.evaluated_at
        ? ` · обновлено ${formatDateTimeLocal(response.evaluated_at)}`
        : ""
    }.`,
  );

  if (response.data_source === "snapshot") {
    lines.push(
      "Кнопка «Обновить» перечитывает снимок с сервера; пересчёт метрик выполняется отдельным job read-model.",
    );
  }

  if (response.attribution_mode === "first_discovery") {
    lines.push(
      "Колонка «В атрибуции» — видео, засчитанные режиму «Первый источник»; «Новых для базы» по-прежнему считается по всем hit'ам ключа.",
    );
  } else if (response.attribution_mode === "all_hits") {
    lines.push(
      "Колонка «В атрибуции» совпадает с числом уникальных video_id по hit'ам ключа (режим «Все находки»).",
    );
  }

  if (response.ranking_version) {
    lines.push(`Версия breakout-рейтинга: ${response.ranking_version}.`);
  }

  return lines;
}

export function keywordDetailLeadSummary(metrics: KeywordPerformanceMetrics): string {
  const scans = metrics.scan_count ?? 0;
  const attributed = metrics.attributed_video_count ?? metrics.unique_video_count ?? 0;
  const mode =
    metrics.attribution_mode === "first_discovery"
      ? "первый источник"
      : metrics.attribution_mode === "all_hits"
        ? "все находки"
        : "атрибуция не указана";

  if (scans === 0) {
    return `Запрос ещё не сканировался радаром · атрибуция: ${mode}.`;
  }

  const evidence = metrics.evidence_status;
  let evidencePhrase = "объём данных на ранней стадии";
  if (evidence === "sufficient") {
    evidencePhrase = "достаточно наблюдений для устойчивых выводов";
  } else if (evidence === "early") {
    evidencePhrase = "данные пока ранние, интерпретируйте осторожно";
  } else if (evidence === "insufficient") {
    evidencePhrase = "мало сканов или находок для уверенных выводов";
  }

  const lastScan = metrics.last_scan_at
    ? `последний скан ${formatDateTimeLocal(metrics.last_scan_at)}`
    : "сканов в метриках нет";

  return `${formatOptionalShort(attributed)} видео в атрибуции «${mode}», ${scans} скан(ов), ${lastScan} · ${evidencePhrase}.`;
}

function formatOptionalShort(n: number): string {
  return Number.isFinite(n) ? String(n) : "—";
}

export function attributionModesEquivalentForDisplay(
  allHits: KeywordPerformanceMetrics,
  firstDiscovery: KeywordPerformanceMetrics,
): boolean {
  return (
    (allHits.attributed_video_count ?? allHits.unique_video_count) ===
      (firstDiscovery.attributed_video_count ?? firstDiscovery.unique_video_count) &&
    allHits.median_vph_at_discovery === firstDiscovery.median_vph_at_discovery &&
    (allHits.new_to_corpus_video_count ?? 0) === (firstDiscovery.new_to_corpus_video_count ?? 0)
  );
}

export function attributionEquivalenceExplanation(metrics: KeywordPerformanceMetrics): string | null {
  const shared = metrics.shared_video_count ?? 0;
  const attributed = metrics.attributed_video_count ?? 0;
  const unique = metrics.unique_video_count ?? 0;

  if (metrics.attribution_mode !== "first_discovery" && metrics.attribution_mode !== "all_hits") {
    return null;
  }

  if (shared === 0 && attributed === unique) {
    return "Для этого ключа нет пересечений с другими ключами по видео — режимы «Все находки» и «Первый источник» дают одинаковые числа в колонках, зависящих от атрибуции.";
  }

  if (metrics.attribution_mode === "first_discovery" && attributed < unique) {
    return `Часть hit'ов (${unique - attributed} video_id) не засчитывается этому ключу как первому источнику — смотрите «В атрибуции» и блок пересечений ниже.`;
  }

  return null;
}
