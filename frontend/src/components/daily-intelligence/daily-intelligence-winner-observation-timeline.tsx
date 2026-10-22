"use client";

import { useState } from "react";

import { ErrorState, LoadingState, SectionPanel } from "@/components/design-system";
import { APPEARANCE_RUN_SOURCE } from "@/lib/daily-intelligence-evidence-format";
import { formatOutcomeTimestamp } from "@/lib/daily-intelligence-outcome-format";
import type { DailyIntelligenceWinnerOutcomeFollowUp } from "@/lib/daily-intelligence-outcome-types";
import type { DailyIntelligenceVideoAppearanceItem } from "@/lib/daily-intelligence-types";
import { formatDateTimeLocal } from "@/lib/monitoring-format";

import { DailyIntelligencePagination } from "./daily-intelligence-pagination";

function timelineEntries(
  reportDate: string,
  editionRank: number,
  appearances: DailyIntelligenceVideoAppearanceItem[],
  followUp: DailyIntelligenceWinnerOutcomeFollowUp | null,
) {
  const sorted = [...appearances].sort(
    (a, b) => new Date(a.source_computed_at).getTime() - new Date(b.source_computed_at).getTime(),
  );
  const first = sorted[0];
  const sameDayRuns = sorted.filter((a) => a.report_date === reportDate);
  const otherDays = sorted.filter((a) => a.report_date !== reportDate);

  const items: { key: string; title: string; detail: string }[] = [];

  if (first) {
    items.push({
      key: "first-run",
      title: "Первое появление в run Attention",
      detail: `${formatDateTimeLocal(first.source_computed_at)} · rank в этом run #${first.rank} · UTC-день ${first.report_date}`,
    });
  }

  items.push({
    key: "edition",
    title: "Итог daily edition за выбранный день",
    detail: `UTC-день ${reportDate} · место в подборке #${editionRank} (не путать с rank отдельного run)`,
  });

  if (sameDayRuns.length > 1) {
    items.push({
      key: "same-day-runs",
      title: "Повторные run в тот же UTC-день",
      detail: `${sameDayRuns.length - 1} доп. появлений в runs до финальной edition`,
    });
  }

  if (otherDays.length > 0) {
    items.push({
      key: "other-days",
      title: "Появления в другие UTC-дни",
      detail: `${otherDays.length} записей в архиве appearances`,
    });
  }

  const outcome = followUp?.outcome_measurement as Record<string, unknown> | undefined;
  const outcomeAt = outcome?.snapshot_captured_at;
  if (typeof outcomeAt === "string" && outcomeAt) {
    items.push({
      key: "outcome",
      title: "Horizon outcome snapshot",
      detail: formatOutcomeTimestamp(outcomeAt),
    });
  } else if (followUp?.coverage_category === "NOT_MATURED") {
    items.push({
      key: "outcome-pending",
      title: "Horizon outcome",
      detail: "Измерение ещё не зафиксировано в архиве",
    });
  } else if (followUp?.coverage_category === "MATURED_MISSING") {
    items.push({
      key: "outcome-missing",
      title: "Horizon outcome",
      detail: "Окно закрыто — подходящий snapshot не найден",
    });
  }

  return items;
}

export function DailyIntelligenceWinnerObservationTimeline({
  reportDate,
  editionRank,
  appearances,
  appearanceTotal,
  appearanceOffset,
  appearancesLoading,
  appearancesError,
  followUp,
  onPageChange,
  onRetry,
}: {
  reportDate: string;
  editionRank: number;
  appearances: DailyIntelligenceVideoAppearanceItem[];
  appearanceTotal: number;
  appearanceOffset: number;
  appearancesLoading: boolean;
  appearancesError: string | null;
  followUp: DailyIntelligenceWinnerOutcomeFollowUp | null;
  onPageChange: (offset: number) => void;
  onRetry: () => void;
}) {
  const [showFull, setShowFull] = useState(false);
  const entries = timelineEntries(reportDate, editionRank, appearances, followUp);

  return (
    <SectionPanel
      title="История наблюдений"
      description="Краткая хронология без смешивания run signal и итога daily edition."
    >
      {appearancesError ? (
        <ErrorState title={appearancesError} compact onRetry={onRetry} />
      ) : appearancesLoading && appearances.length === 0 ? (
        <LoadingState variant="inline" title="Загрузка истории…" />
      ) : (
        <>
          <ol className="space-y-4 max-w-3xl" data-testid="di-observation-timeline">
            {entries.map((entry, index) => (
              <li key={entry.key} className="flex gap-3 text-sm">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-muted text-xs tabular-nums">
                  {index + 1}
                </span>
                <div className="min-w-0">
                  <p className="font-medium">{entry.title}</p>
                  <p className="text-muted-foreground mt-0.5 leading-relaxed">{entry.detail}</p>
                </div>
              </li>
            ))}
          </ol>

          {appearanceTotal === 0 ? (
            <p className="mt-3 text-sm text-muted-foreground">Нет сохранённых run-появлений</p>
          ) : (
            <button
              type="button"
              className="mt-4 text-sm text-primary hover:underline"
              onClick={() => setShowFull((v) => !v)}
              data-testid="di-toggle-all-appearances"
            >
              {showFull ? "Скрыть полный список" : "Все наблюдения"}
            </button>
          )}

          {showFull && appearanceTotal > 0 ? (
            <div className="mt-4 space-y-3">
              <p className="text-xs text-muted-foreground">{APPEARANCE_RUN_SOURCE}</p>
              <div className="overflow-x-auto rounded-xl border border-border">
                <table className="w-full text-sm" data-testid="di-appearance-table">
                  <thead className="bg-muted/30 text-left text-xs text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2">UTC-день</th>
                      <th className="px-3 py-2">Публикация run</th>
                      <th className="px-3 py-2 w-16">Rank run</th>
                      <th className="px-3 py-2">Run ID</th>
                    </tr>
                  </thead>
                  <tbody>
                    {appearances.map((row) => (
                      <tr
                        key={`${row.source_run_id}-${row.source_computed_at}`}
                        className="border-t border-border/60"
                      >
                        <td className="px-3 py-2 tabular-nums align-top">{row.report_date}</td>
                        <td className="px-3 py-2 text-xs align-top whitespace-nowrap">
                          {formatDateTimeLocal(row.source_computed_at)}
                        </td>
                        <td className="px-3 py-2 tabular-nums align-top">#{row.rank}</td>
                        <td className="px-3 py-2 font-mono text-[11px] break-all align-top text-muted-foreground">
                          {row.source_run_id}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <DailyIntelligencePagination
                total={appearanceTotal}
                offset={appearanceOffset}
                limit={10}
                disabled={appearancesLoading}
                onPageChange={onPageChange}
              />
            </div>
          ) : null}
        </>
      )}
    </SectionPanel>
  );
}
