/**
 * Stage 1.22C — Saved Topics / Watchlist (backend `family_key`).
 */

export const SAVED_TOPICS_STAGE = "1.22C";

export type SavedTopicDraft = {
  familyKey: string;
  runId: string | null;
};

export function savedTopicAffordance(_draft: SavedTopicDraft): {
  enabled: boolean;
  hint: string;
} {
  return { enabled: true, hint: "Сохранить тему в watchlist" };
}

export const SAVED_TOPIC_STATUS_LABELS: Record<string, string> = {
  WATCHING: "Наблюдаю",
  WANT_TO_TEST: "Хочу протестировать",
  TESTING: "Тестирую",
  DROPPED: "Отложил",
};

export const FAMILY_ABSENCE_MESSAGE =
  "Тема не представлена в текущей выборке Attention Engine";

export const FINDING_RATING_LABELS: Record<string, string> = {
  USEFUL: "Полезно",
  NOT_USEFUL: "Не полезно",
  UNCLEAR: "Пока неясно",
};

export const OWN_TEST_OUTCOME_LABELS: Record<string, string> = {
  UNKNOWN: "Результат неизвестен",
  BETTER: "Лучше ожиданий",
  AS_EXPECTED: "Примерно как ожидалось",
  WORSE: "Хуже ожиданий",
};

export const EVENT_TYPE_LABELS: Record<string, string> = {
  status_changed: "Смена статуса",
  archived: "Архив",
  restored: "Восстановление",
  feedback_added: "Новая оценка",
};
