import { describe, expect, it } from "vitest";

import {
  detailLead,
  formatObservationTimelineLine,
  historyEmptyMessage,
  listCardSummary,
} from "@/lib/saved-topic-watch";
import type { SavedTopicDetail, SavedTopicListItem } from "@/lib/saved-topics-types";

describe("saved-topic-watch", () => {
  it("formats absence without zero metrics", () => {
    expect(
      formatObservationTimelineLine({
        present_in_snapshot: false,
        absence_message: "Тема не представлена",
      }),
    ).toMatch(/не представлена/i);
  });

  it("list card uses watch headline", () => {
    const item = {
      watch_headline: "Не в последней выборке",
    } as SavedTopicListItem;
    expect(listCardSummary(item)).toBe("Не в последней выборке");
  });

  it("history empty explains single snapshot", () => {
    const detail = {
      watch_summary: { observation_count: 1 },
    } as SavedTopicDetail;
    expect(historyEmptyMessage(detail)).toMatch(/не восстанавливаем историю/i);
  });

  it("detail lead combines headline and stale message", () => {
    const detail = {
      watch_summary: {
        headline: "Ждём следующий анализ",
        stale_message: "Нет новых наблюдений с 01.01.2026",
      },
    } as SavedTopicDetail;
    expect(detailLead(detail)).toContain("Ждём следующий анализ");
    expect(detailLead(detail)).toContain("Нет новых наблюдений");
  });
});
