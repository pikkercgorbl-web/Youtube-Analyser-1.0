/** Human copy for Keyword Performance UI (Stage 1.21E). */

export function keywordEvidenceStatusLabel(status: string | null | undefined): string {
  if (!status) {
    return "—";
  }
  switch (status) {
    case "insufficient":
      return "Недостаточно данных";
    case "early":
      return "Ранняя стадия";
    case "established":
      return "Данных достаточно";
    default:
      return status;
  }
}

export function sourceTypeLabel(sourceType: string | null | undefined): string {
  if (!sourceType) {
    return "—";
  }
  switch (sourceType) {
    case "seed":
      return "Исходный";
    case "manual":
      return "Ручной";
    case "suggestion":
      return "Suggestion";
    case "related":
      return "Related";
    case "channel":
      return "Тема канала";
    case "llm":
      return "LLM";
    default:
      return sourceType;
  }
}

export const NEW_TO_CORPUS_HELP =
  "Показывает, сколько найденных видео система раньше не знала. Высокое значение не означает автоматически «хороший» keyword.";

export const VPH_AT_DISCOVERY_TOOLTIP =
  "Сколько просмотров в час видео набирало в момент, когда keyword его обнаружил.";

export const EVIDENCE_NOT_QUALITY =
  "Evidence показывает объём наблюдений, а не качество keyword.";

export const LIFECYCLE_NOT_QUALITY =
  "Lifecycle определяет режим сканирования keyword. Это не оценка его качества.";

export const BREAKOUT_TOP_DECILE_HELP =
  "Top-decile breakout показывает долю найденных видео, попавших в верхние 10% глобального breakout-рейтинга на момент оценки. Относительная метрика, не абсолютное качество.";

export const OUTCOME_72H_TOOLTIP =
  "72 ч исход сравнивает просмотры при находке видео с подходящим снимком около +72 часов.";

export const MISSING_72H_HELP =
  "Для части наблюдений отсутствует подходящий снимок около точки +72 ч.";

export const CROSS_KEYWORD_DUP_HELP =
  "Видео также было найдено другими keywords. Пересечения не означают, что keyword «плохой».";

export const ATTRIBUTION_ALL_HITS =
  "Keyword получает связь с каждым видео, которое он обнаружил.";

export const ATTRIBUTION_FIRST_DISCOVERY =
  "Видео относится только к keyword, который обнаружил его первым. Зависит от порядка сканов; это не causal attribution.";
