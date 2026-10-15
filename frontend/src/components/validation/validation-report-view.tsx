"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import {
  ErrorState,
  LoadingState,
  PageHeader,
  PageShell,
  SectionPanel,
} from "@/components/design-system";
import { Input } from "@/components/ui/input";
import { getValidationReport } from "@/lib/api";
import {
  ANALYST_VERDICT_LABELS,
  EVIDENCE_STATE_LABELS,
  SAVED_RESEARCH_STATUS_LABELS,
} from "@/lib/saved-research-labels";
import {
  FINDING_RATING_LABELS,
  SAVED_TOPIC_STATUS_LABELS,
} from "@/lib/saved-topics";
import type { ResearchPortfolioSavedItem, ValidationReport } from "@/lib/validation-types";

function formatMap(
  title: string,
  data: Record<string, number>,
  labels?: Record<string, string>,
) {
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

function savedItemHref(item: ResearchPortfolioSavedItem): string {
  return item.kind === "video" ? `/saved/videos/${item.id}` : `/saved/families/${item.id}`;
}

function statusLabel(status: string): string {
  if (status === "ARCHIVED") return "В архиве";
  return SAVED_RESEARCH_STATUS_LABELS[status as keyof typeof SAVED_RESEARCH_STATUS_LABELS] ?? status;
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

  if (state === "loading") return <LoadingState title="Загрузка итогов…" />;
  if (state === "error") return <ErrorState title={message} onRetry={() => void load()} />;
  if (!report) return null;

  const portfolio = report.research_portfolio;
  const saved = portfolio.saved_in_period;
  const hints = portfolio.portfolio_hints;
  const hasAnySaved = saved.combined_total > 0;

  return (
    <PageShell>
      <PageHeader
        title="Итоги исследований"
        lead="Сводка сохранённых видео и тем: что вы изучаете, какие решения приняли и какие измерения доступны."
      />

      <SectionPanel title="Период">
        <p className="mb-3 text-sm text-muted-foreground">
          Фильтр «сохранено за период» использует дату сохранения видео или темы. Решения и
          смены статуса считаются отдельно — по дате события в выбранном интервале.
        </p>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input
            aria-label="Начало периода"
            type="datetime-local"
            value={periodStart}
            onChange={(event) => setPeriodStart(event.target.value)}
          />
          <Input
            aria-label="Конец периода"
            type="datetime-local"
            value={periodEnd}
            onChange={(event) => setPeriodEnd(event.target.value)}
          />
        </div>
      </SectionPanel>

      {!hasAnySaved ? (
        <div className="rounded-2xl border border-dashed border-border p-8">
          <h2 className="text-xl font-semibold">Пока нет сохранённых исследований</h2>
          <p className="mt-3 max-w-2xl text-muted-foreground">
            Сохраните видео или тему из «Возможностей» или архива отчётов — они появятся здесь и в
            разделе «Сохранённое».
          </p>
          <Link href="/opportunities" className="mt-5 inline-block font-medium text-primary hover:underline">
            Перейти к возможностям →
          </Link>
        </div>
      ) : null}

      {hints.saved_without_decisions_message ? (
        <div className="rounded-2xl border border-border bg-muted/30 p-6">
          <p className="font-medium">{hints.saved_without_decisions_message}</p>
          <p className="mt-2 text-sm text-muted-foreground">
            Откройте карточку в «Сохранённом», обновите статус или добавьте оценку находки.
          </p>
          <Link href="/saved" className="mt-4 inline-block text-sm font-medium text-primary hover:underline">
            Перейти к сохранённым →
          </Link>
        </div>
      ) : null}

      {hasAnySaved ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {[
              ["Сохранено за период", saved.combined_total],
              ["Видео", saved.videos],
              ["Темы", saved.families],
              ["Ещё изучаю (сейчас)", portfolio.pending_signals.cohort_still_watching],
              [
                "В тесте или отложено (сейчас)",
                portfolio.pending_signals.cohort_in_testing + portfolio.pending_signals.cohort_dropped,
              ],
              ["С оценкой находки", portfolio.latest_feedback.cohort_with_latest_feedback],
              ["Есть наблюдения", portfolio.observations.cohort_with_any_observation],
              [
                "Решения за период (смена статуса)",
                portfolio.decisions_in_period.status_changed_events,
              ],
            ].map(([label, value]) => (
              <div key={label} className="rounded-2xl border border-border bg-card p-5">
                <p className="text-sm text-muted-foreground">{label}</p>
                <p className="mt-2 text-3xl font-semibold tabular-nums">{value}</p>
              </div>
            ))}
          </div>

          <SectionPanel title="Сохранено за период">
            <ul className="space-y-2">
              {portfolio.saved_in_period_items.length === 0 ? (
                <li className="text-sm text-muted-foreground">Нет объектов в выбранном интервале.</li>
              ) : (
                portfolio.saved_in_period_items.map((item) => (
                  <li
                    key={`${item.kind}-${item.id}`}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border p-3"
                  >
                    <div>
                      <Link href={savedItemHref(item)} className="font-medium hover:text-primary">
                        {item.title}
                      </Link>
                      <p className="text-xs text-muted-foreground mt-0.5">
                        {item.kind === "video" ? "Видео" : "Тема"} · сохранено{" "}
                        {new Date(item.saved_at).toLocaleString("ru-RU")}
                      </p>
                    </div>
                    <div className="text-right text-xs text-muted-foreground">
                      <p>Текущий статус: {statusLabel(item.current_status)}</p>
                      <p>
                        Наблюдения: {item.observation_count}
                        {item.has_latest_feedback ? " · есть оценка" : ""}
                      </p>
                    </div>
                  </li>
                ))
              )}
            </ul>
          </SectionPanel>

          <SectionPanel title="Текущий статус (сохранённые за период)">
            {formatMap("Сейчас", portfolio.current_status_counts, {
              ...SAVED_RESEARCH_STATUS_LABELS,
              ARCHIVED: "В архиве",
            })}
          </SectionPanel>

          <SectionPanel title="Решения за период">
            <p className="text-sm text-muted-foreground mb-3">
              Смены статуса и другие события по дате фиксации, не по дате сохранения.
            </p>
            <div className="grid gap-4 sm:grid-cols-2">
              {formatMap(
                "Переходы статуса",
                portfolio.decisions_in_period.status_transition_events,
                {
                  to_WANT_TO_TEST: "→ Хочу протестировать",
                  to_TESTING: "→ Тестирую",
                  to_DROPPED: "→ Отложил",
                  to_WATCHING: "→ Наблюдаю",
                },
              )}
              {formatMap("Типы событий", portfolio.decisions_in_period.events_by_type)}
            </div>
          </SectionPanel>

          <SectionPanel title="Оценки находок (видео и темы)">
            {formatMap(
              "Последние оценки",
              portfolio.latest_feedback.research_verdict_distribution,
              ANALYST_VERDICT_LABELS,
            )}
            <ul className="mt-3 space-y-1 text-sm text-muted-foreground">
              <li>С оценкой: {portfolio.latest_feedback.cohort_with_latest_feedback}</li>
              <li>Без оценки: {portfolio.latest_feedback.cohort_without_latest_feedback}</li>
            </ul>
          </SectionPanel>

          <SectionPanel title="Наблюдения доступны">
            <div className="grid gap-4 sm:grid-cols-2">
              {formatMap(
                "Достаточность измерений",
                portfolio.observations.evidence_state_distribution,
                EVIDENCE_STATE_LABELS,
              )}
            </div>
            <ul className="mt-3 space-y-1 text-sm text-muted-foreground">
              <li>С хотя бы одним наблюдением: {portfolio.observations.cohort_with_any_observation}</li>
              <li>С несколькими точками: {portfolio.observations.cohort_with_multiple_observations}</li>
              <li>
                Только одна точка (мало для динамики):{" "}
                {portfolio.pending_signals.cohort_single_observation_only}
              </li>
            </ul>
          </SectionPanel>

          {saved.legacy_topics > 0 || report.topics_saved_in_period > 0 ? (
            <SectionPanel title="Ранее сохранённые темы (legacy)">
              <p className="text-sm text-muted-foreground mb-3">
                Отдельный формат закладок до Saved Research. Показатели не суммируются с видео и
                темами выше.
              </p>
              <div className="grid gap-4 sm:grid-cols-3">
                {[
                  ["Legacy тем за период", report.topics_saved_in_period],
                  ["С оценкой находки", report.topics_with_latest_feedback],
                  ["С результатом своего теста", report.topics_with_known_own_test_outcome],
                ].map(([label, value]) => (
                  <div key={label} className="rounded-xl border border-border p-4">
                    <p className="text-xs text-muted-foreground">{label}</p>
                    <p className="text-2xl font-semibold tabular-nums mt-1">{value}</p>
                  </div>
                ))}
              </div>
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                {formatMap("Текущие статусы legacy", report.current_status_counts, {
                  ...SAVED_TOPIC_STATUS_LABELS,
                  ARCHIVED: "В архиве",
                })}
                {formatMap(
                  "Переходы за период (legacy)",
                  report.status_transition_events,
                  {
                    to_WANT_TO_TEST: "→ Хочу протестировать",
                    to_TESTING: "→ Тестирую",
                    to_DROPPED: "→ Отложил",
                  },
                )}
                {formatMap(
                  "Оценки находки (legacy)",
                  report.latest_finding_rating_distribution,
                  FINDING_RATING_LABELS,
                )}
              </div>
              <Link
                href="/saved-topics"
                className="mt-4 inline-block text-sm font-medium text-primary hover:underline"
              >
                Список legacy тем →
              </Link>
            </SectionPanel>
          ) : null}

          <details className="rounded-2xl border border-border p-5">
            <summary className="font-medium">Как читать итоги</summary>
            <ul className="mt-4 list-disc space-y-1 pl-5 text-sm text-muted-foreground">
              {[...portfolio.interpretation_notes, ...report.interpretation_notes].map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </details>
        </>
      ) : null}
    </PageShell>
  );
}
