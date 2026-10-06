"use client";

import { useCallback, useEffect, useState } from "react";

import { ErrorState, LoadingState, PageHeader, PageShell, SectionPanel } from "@/components/design-system";
import { Input } from "@/components/ui/input";
import { getValidationReport } from "@/lib/api";
import { FINDING_RATING_LABELS, SAVED_TOPIC_STATUS_LABELS } from "@/lib/saved-topics";
import type { ValidationReport } from "@/lib/validation-types";

function formatMap(title: string, data: Record<string, number>, labels?: Record<string, string>) {
  const entries = Object.entries(data).filter(([, value]) => value > 0);
  if (!entries.length) return null;
  return (
    <div>
      <p className="text-sm font-medium">{title}</p>
      <ul className="mt-1 space-y-1 text-sm text-muted-foreground">
        {entries.map(([key, value]) => (
          <li key={key}>
            {labels?.[key] ?? key}: {value}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ValidationReportView() {
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [state, setState] = useState<"loading" | "error" | "ready">("loading");
  const [message, setMessage] = useState("");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");

  const load = useCallback(async () => {
    setState("loading");
    try {
      const data = await getValidationReport({
        period_start: periodStart ? new Date(periodStart).toISOString() : undefined,
        period_end: periodEnd ? new Date(periodEnd).toISOString() : undefined,
      });
      setReport(data);
      setState("ready");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Не удалось загрузить отчёт");
      setState("error");
    }
  }, [periodStart, periodEnd]);

  useEffect(() => {
    void load();
  }, [load]);

  if (state === "loading") return <LoadingState title="Загрузка отчёта…" />;
  if (state === "error") return <ErrorState title={message} onRetry={() => void load()} />;
  if (!report) return null;

  return (
    <PageShell>
      <PageHeader
        title="Validation"
        lead="Read-only сводка по сохранённым темам, решениям и feedback. Без пересчёта Attention и без success probability."
      />
      <SectionPanel title="Период (по дате сохранения темы)">
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input type="datetime-local" value={periodStart} onChange={(event) => setPeriodStart(event.target.value)} />
          <Input type="datetime-local" value={periodEnd} onChange={(event) => setPeriodEnd(event.target.value)} />
        </div>
      </SectionPanel>
      <SectionPanel title="Сводка">
        <p className="text-2xl font-semibold tabular-nums">{report.topics_saved_in_period}</p>
        <p className="text-sm text-muted-foreground">тем сохранено за период</p>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          {formatMap("Текущие статусы (сейчас)", report.current_status_counts, {
            ...SAVED_TOPIC_STATUS_LABELS,
            ARCHIVED: "В архиве",
          })}
          {formatMap("События перехода статуса (за период)", report.status_transition_events, {
            to_WANT_TO_TEST: "→ Хочу протестировать",
            to_TESTING: "→ Тестирую",
            to_DROPPED: "→ Отложил",
          })}
          {formatMap("Последние оценки находки", report.latest_finding_rating_distribution, FINDING_RATING_LABELS)}
        </div>
        <ul className="mt-4 space-y-1 text-sm">
          <li>Тем с feedback: {report.topics_with_latest_feedback}</li>
          <li>С ссылкой на своё тестовое видео: {report.topics_with_own_test_video_url}</li>
          <li>С известным результатом теста: {report.topics_with_known_own_test_outcome}</li>
        </ul>
      </SectionPanel>
      <SectionPanel title="Последняя Attention-выборка (observations)">
        <ul className="space-y-1 text-sm text-muted-foreground">
          <li>Присутствует в выборке: {report.latest_observation_presence.present_in_latest_sample ?? 0}</li>
          <li>Не представлена (не провал темы): {report.latest_observation_presence.not_in_latest_sample ?? 0}</li>
          <li>Нет observation: {report.latest_observation_presence.no_observation ?? 0}</li>
          <li>С сопоставимой разницей counts: {report.topics_with_comparable_count_deltas}</li>
        </ul>
      </SectionPanel>
      <SectionPanel title="Frozen snapshot (источники при сохранении)">
        <div className="grid gap-4 sm:grid-cols-2">
          {formatMap("support_sources", report.frozen_support_source_breakdown)}
          {formatMap("family_kind", report.frozen_family_kind_breakdown)}
        </div>
      </SectionPanel>
      <SectionPanel title="Как читать отчёт">
        <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
          {report.interpretation_notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      </SectionPanel>
    </PageShell>
  );
}
