import type { SavedResearchAnalystVerdict } from "./saved-research-analyst-feedback-types";
import type { SavedResearchStatus } from "./saved-research-types";

export const SAVED_RESEARCH_STATUS_LABELS: Record<SavedResearchStatus, string> = {
  WATCHING: "Наблюдаю",
  WANT_TO_TEST: "Хочу протестировать",
  TESTING: "Тестирую",
  DROPPED: "Отбросил",
};

export const VIDEO_ABSENCE_MESSAGE =
  "Видео не входит в текущую выборку Attention Engine.";

export const FAMILY_ABSENCE_MESSAGE =
  "Тема не попала в текущую выборку Attention Engine.";

export const CHANNEL_BASELINE_UNAVAILABLE =
  "Недостаточно сопоставимой истории канала";

export const MANUAL_SAVED_VIDEO_REFRESH_SOURCE = "manual_saved_video_refresh";

export const DAILY_INTELLIGENCE_SAVE_ANCHOR_KIND = "daily_intelligence_save_anchor";

/** SavedFamily historical anchor (Daily Intelligence save). */
export const FAMILY_HISTORICAL_ANCHOR_SAVE_LABEL = "Сохранено из исторического отчёта";

export const OBSERVATION_SOURCE_LABELS: Record<string, string> = {
  [MANUAL_SAVED_VIDEO_REFRESH_SOURCE]: "YouTube Data API (ручное обновление)",
  [DAILY_INTELLIGENCE_SAVE_ANCHOR_KIND]: "Якорь Daily Intelligence (historical edition)",
  attention_refresh: "Attention refresh",
};

export const DELAYED_OUTCOME_LABELS: Record<string, string> = {
  pending: "72ч: ожидание",
  confirmed: "72ч: подтверждено",
  not_confirmed: "72ч: не подтверждено",
  missing: "72ч: нет снимка",
  unavailable: "72ч: недоступно",
};

export const EVIDENCE_STATE_LABELS: Record<string, string> = {
  validated: "Есть данные для сравнения",
  pending: "Нужно больше наблюдений",
  insufficient: "Недостаточно наблюдений",
};

export const ANALYST_VERDICT_LABELS: Record<SavedResearchAnalystVerdict, string> = {
  USEFUL: "Полезно",
  NOT_RELEVANT: "Не релевантно",
  NOISE_OR_DUPLICATE: "Шум / дубликат",
  TOO_BROAD: "Слишком широко",
  NEEDS_RESEARCH: "Нужно больше исследования",
};

export const ANALYST_VERDICT_OPTIONS: SavedResearchAnalystVerdict[] = [
  "USEFUL",
  "NOT_RELEVANT",
  "NOISE_OR_DUPLICATE",
  "TOO_BROAD",
  "NEEDS_RESEARCH",
];
