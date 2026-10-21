"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  Disclosure,
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
import type { ValidationReport } from "@/lib/validation-types";
import { buildValidationSummaryBlocks } from "@/lib/validation-presentation";
import {
  formatValidationPeriodLabel,
  parseValidationPeriodSearchParams,
  type ValidationPeriodDates,
  validationPeriodHref,
  validationPeriodToApiParams,
} from "@/lib/validation-period";
import { APP_TIMEZONE } from "@/lib/app-timezone";

import { ValidationSavedItemRow } from "./validation-saved-item-row";

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

export function ValidationReportView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const parsedFromUrl = useMemo(
    () => parseValidationPeriodSearchParams(searchParams),
    [searchParams],
  );

  const [dates, setDates] = useState<ValidationPeriodDates>(parsedFromUrl.dates);
  const [urlIssue, setUrlIssue] = useState<string | null>(parsedFromUrl.urlIssue);
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [reportState, setReportState] = useState<"loading" | "error" | "ready">("loading");
  const [message, setMessage] = useState("");
  const requestSeq = useRef(0);

  useEffect(() => {
    setDates(parsedFromUrl.dates);
    setUrlIssue(parsedFromUrl.urlIssue);
    if (parsedFromUrl.urlCorrected) {
      router.replace(validationPeriodHref(parsedFromUrl.dates), { scroll: false });
    }
  }, [parsedFromUrl, router]);

  const periodValid =
    !dates.from || !dates.to || dates.from <= dates.to;

  const load = useCallback(async () => {
    if (!periodValid) {
      return;
    }
    const seq = ++requestSeq.current;
    setReportState("loading");
    try {
      const data = await getValidationReport(validationPeriodToApiParams(dates));
      if (seq !== requestSeq.current) {
        return;
      }
      setReport(data);
      setReportState("ready");
    } catch (error) {
      if (seq !== requestSeq.current) {
        return;
      }
      setMessage(error instanceof Error ? error.message : "Не удалось загрузить отчёт");
      setReportState("error");
    }
  }, [dates, periodValid]);

  useEffect(() => {
    void load();
  }, [load]);

  const updatePeriod = (patch: Partial<ValidationPeriodDates>) => {
    const next: ValidationPeriodDates = { ...dates, ...patch };
    if (next.from && next.to && next.from > next.to) {
      setUrlIssue("Дата «с» не может быть позже даты «по».");
      setDates(next);
      return;
    }
    setUrlIssue(null);
    setDates(next);
    router.replace(validationPeriodHref(next), { scroll: false });
  };

  const portfolio = report?.research_portfolio;
  const saved = portfolio?.saved_in_period;
  const hints = portfolio?.portfolio_hints;
  const hasAnySaved = (saved?.combined_total ?? 0) > 0;
  const summaryBlocks = useMemo(
    () => (portfolio ? buildValidationSummaryBlocks(portfolio, dates) : []),
    [portfolio, dates],
  );

  const researchStatusLabels = useMemo(
    () => ({
      ...SAVED_RESEARCH_STATUS_LABELS,
      ARCHIVED: "В архиве",
    }),
    [],
  );

  return (
    <PageShell>
      <PageHeader
        title="Итоги исследований"
        lead="Что вы сохранили, какие измерения доступны и какие решения зафиксировали за выбранный период."
      />

      <SectionPanel title="Период">
        <p className="mb-3 text-sm font-medium" data-testid="period-label">
          Показано: {formatValidationPeriodLabel(dates)} · календарь {APP_TIMEZONE}
        </p>
        {urlIssue ? (
          <p className="mb-3 text-sm text-amber-700 dark:text-amber-200" data-testid="period-url-issue">
            {urlIssue} Период сброшен на «за всё время».
          </p>
        ) : null}
        {!periodValid ? (
          <p className="mb-3 text-sm text-destructive">
            Исправьте даты: «с» не может быть позже «по». Запрос не отправляется.
          </p>
        ) : null}
        <div className="flex flex-col gap-2 sm:flex-row">
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-muted-foreground">С</span>
            <Input
              aria-label="Начало периода"
              data-testid="period-from"
              type="date"
              value={dates.from}
              onChange={(event) => updatePeriod({ from: event.target.value })}
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-muted-foreground">По</span>
            <Input
              aria-label="Конец периода"
              data-testid="period-to"
              type="date"
              value={dates.to}
              onChange={(event) => updatePeriod({ to: event.target.value })}
            />
          </label>
        </div>
      </SectionPanel>

      {reportState === "loading" ? <LoadingState title="Загрузка итогов…" /> : null}
      {reportState === "error" ? (
        <ErrorState title={message} onRetry={() => void load()} />
      ) : null}

      {reportState === "ready" && report && portfolio && saved && hints ? (
        <>
          {!hasAnySaved ? (
            <div className="rounded-2xl border border-dashed border-border p-8">
              <h2 className="text-xl font-semibold">Пока нет сохранённых исследований</h2>
              <p className="mt-3 max-w-2xl text-muted-foreground">
                Сохраните видео или тему из «Возможностей» или архива отчётов — они появятся здесь
                и в разделе «Сохранённое».
              </p>
              <Link
                href="/opportunities"
                className="mt-5 inline-block font-medium text-primary hover:underline"
              >
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
              <div
                className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"
                data-testid="validation-summary-blocks"
              >
                {summaryBlocks.map((block) => (
                  <div key={block.id} className="rounded-2xl border border-border bg-card p-4">
                    <p className="text-sm text-muted-foreground">{block.title}</p>
                    <p className="mt-1 text-3xl font-semibold tabular-nums">{block.value}</p>
                    <p className="mt-2 text-xs text-muted-foreground leading-snug">{block.detail}</p>
                  </div>
                ))}
              </div>

              <SectionPanel title="Сохранённые объекты">
                <p className="mb-3 text-sm text-muted-foreground">
                  Ссылки ведут в карточку сохранённого объекта; после просмотра можно вернуться сюда с тем же
                  периодом.
                </p>
                <ul className="space-y-2">
                  {portfolio.saved_in_period_items.length === 0 ? (
                    <li className="text-sm text-muted-foreground">Нет объектов в выбранном интервале.</li>
                  ) : (
                    portfolio.saved_in_period_items.map((item) => (
                      <ValidationSavedItemRow
                        key={`${item.kind}-${item.id}`}
                        item={item}
                        dates={dates}
                        statusLabels={researchStatusLabels}
                      />
                    ))
                  )}
                </ul>
                <Link
                  href="/saved"
                  className="mt-4 inline-block text-sm font-medium text-primary hover:underline"
                >
                  Все сохранённые →
                </Link>
              </SectionPanel>

              <div className="rounded-2xl border border-border bg-card p-5">
                <Disclosure summary="Как посчитано">
                  <div className="space-y-6 text-sm text-muted-foreground">
                    <div>
                      <p className="font-medium text-foreground">Временные правила</p>
                      <ul className="mt-2 list-disc space-y-1 pl-5">
                        {Object.entries(portfolio.temporal_contracts).map(([key, text]) => (
                          <li key={key}>
                            <span className="font-mono text-xs">{key}</span>: {text}
                          </li>
                        ))}
                      </ul>
                    </div>

                    <div className="grid gap-4 sm:grid-cols-2">
                      {formatMap("Текущий статус (когорта периода)", portfolio.current_status_counts, {
                        ...SAVED_RESEARCH_STATUS_LABELS,
                        ARCHIVED: "В архиве",
                      })}
                      {formatMap(
                        "Переходы статуса за период",
                        portfolio.decisions_in_period.status_transition_events,
                        {
                          to_WANT_TO_TEST: "→ Хочу протестировать",
                          to_TESTING: "→ Тестирую",
                          to_DROPPED: "→ Отложил",
                          to_WATCHING: "→ Наблюдаю",
                        },
                      )}
                      {formatMap("Типы событий за период", portfolio.decisions_in_period.events_by_type)}
                      {formatMap(
                        "Оценки находок (verdict)",
                        portfolio.latest_feedback.research_verdict_distribution,
                        ANALYST_VERDICT_LABELS,
                      )}
                      {formatMap(
                        "Достаточность измерений",
                        portfolio.observations.evidence_state_distribution,
                        EVIDENCE_STATE_LABELS,
                      )}
                    </div>

                    <ul className="list-disc space-y-1 pl-5">
                      <li>С оценкой находки: {portfolio.latest_feedback.cohort_with_latest_feedback}</li>
                      <li>Без оценки: {portfolio.latest_feedback.cohort_without_latest_feedback}</li>
                      <li>С наблюдениями: {portfolio.observations.cohort_with_any_observation}</li>
                      <li>
                        Несколько точек наблюдения: {portfolio.observations.cohort_with_multiple_observations}
                      </li>
                      <li>
                        Только одна точка: {portfolio.pending_signals.cohort_single_observation_only}
                      </li>
                    </ul>

                    {saved.legacy_topics > 0 || report.topics_saved_in_period > 0 ? (
                      <div className="border-t border-border/50 pt-4">
                        <p className="font-medium text-foreground">Legacy темы (отдельный формат)</p>
                        <p className="mt-1">
                          За период: {report.topics_saved_in_period}. Не суммируются с видео и темами Saved
                          Research выше.
                        </p>
                        <div className="mt-3 grid gap-4 sm:grid-cols-2">
                          {formatMap("Статусы legacy", report.current_status_counts, {
                            ...SAVED_TOPIC_STATUS_LABELS,
                            ARCHIVED: "В архиве",
                          })}
                          {formatMap(
                            "Переходы legacy за период",
                            report.status_transition_events,
                            {
                              to_WANT_TO_TEST: "→ Хочу протестировать",
                              to_TESTING: "→ Тестирую",
                              to_DROPPED: "→ Отложил",
                            },
                          )}
                          {formatMap(
                            "Оценки находки legacy",
                            report.latest_finding_rating_distribution,
                            FINDING_RATING_LABELS,
                          )}
                        </div>
                        <p className="mt-3 text-sm text-muted-foreground">
                          Старые закладки (формат saved_topics) доступны только по прямой ссылке{" "}
                          <Link href="/saved-topics" className="font-medium text-primary hover:underline">
                            /saved-topics
                          </Link>
                          ; новые темы сохраняйте в «Сохранённое».
                        </p>
                      </div>
                    ) : null}

                    <div className="border-t border-border/50 pt-4">
                      <p className="font-medium text-foreground">Пояснения</p>
                      <ul className="mt-2 list-disc space-y-1 pl-5">
                        {[...portfolio.interpretation_notes, ...report.interpretation_notes].map((note) => (
                          <li key={note}>{note}</li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </Disclosure>
              </div>
            </>
          ) : null}
        </>
      ) : null}
    </PageShell>
  );
}
