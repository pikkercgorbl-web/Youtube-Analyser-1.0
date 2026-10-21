import type {
  SavedTopicDetail,
  SavedTopicListItem,
  SavedTopicTimelineItem,
  SavedTopicWatchMilestone,
} from "@/lib/saved-topics-types";

export const MILESTONE_LABELS: Record<SavedTopicWatchMilestone["kind"], string> = {
  saved: "Сохранена",
  detected_again: "Обнаружена снова",
  not_detected: "Не обнаружена в выборке",
};

export function formatObservationTimelineLine(
  payload: Record<string, unknown> | undefined,
): string {
  if (!payload) return "—";
  if (payload.present_in_snapshot === false) {
    return String(
      payload.absence_message ??
        "Тема не представлена в этой выборке Attention (метрики не пересчитывались).",
    );
  }
  const counts = payload.counts;
  if (!counts || typeof counts !== "object") {
    return "Обнаружена в выборке Attention.";
  }
  const c = counts as Record<string, number>;
  return [
    `видео ${c.video_count ?? "?"}`,
    `каналы ${c.channel_count ?? "?"}`,
    `ключи ${c.keyword_count ?? "?"}`,
  ].join(" · ");
}

export function listCardSummary(item: SavedTopicListItem): string {
  if (item.watch_headline) return item.watch_headline;
  if (item.watch_stale_message) return item.watch_stale_message;
  if (item.present_in_latest_snapshot === false) {
    return "Не в последней выборке Attention.";
  }
  return "Сохранённая тема для наблюдения.";
}

export function detailLead(detail: SavedTopicDetail): string {
  const ws = detail.watch_summary;
  if (!ws) {
    return "Сохранённая тема; сводка наблюдений недоступна.";
  }
  const parts = [ws.headline];
  if (ws.stale_message) parts.push(ws.stale_message);
  return parts.join(" ");
}

export function historyEmptyMessage(detail: SavedTopicDetail): string {
  const count = detail.watch_summary?.observation_count ?? 0;
  if (count <= 1) {
    return "Пока только снимок на момент сохранения. Следующие записи появятся после завершённых анализов Attention — мы не восстанавливаем историю задним числом.";
  }
  return "Нет событий в ленте.";
}

export function timelineObservationLabel(item: SavedTopicTimelineItem): string {
  if (item.kind !== "observation") {
    return "";
  }
  const payload = item.payload;
  if (payload?.present_in_snapshot === false) {
    return MILESTONE_LABELS.not_detected;
  }
  return MILESTONE_LABELS.detected_again;
}
