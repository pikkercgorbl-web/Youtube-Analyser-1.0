"use client";

import {
  buildReportDiscoverySummary,
  formatReportAnalyzedPeriod,
  formatReportGeneratedLine,
} from "@/lib/daily-intelligence-presentation";
import type { DailyIntelligenceReportSummary } from "@/lib/daily-intelligence-types";
import { ZeroContextNote } from "@/components/design-system";

import { DailyIntelligenceStatusBadge } from "./daily-intelligence-status-badge";
import { dailyIntelligenceStatusHint } from "@/lib/daily-intelligence-labels";

export function DailyIntelligenceReportHeader({
  report,
}: {
  report: DailyIntelligenceReportSummary;
}) {
  const statusHint = dailyIntelligenceStatusHint(report.status);

  return (
    <header
      className="rounded-xl border border-border bg-card/40 p-4 sm:p-5 space-y-3"
      data-testid="di-report-header"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-lg font-semibold tabular-nums">Отчёт за {report.report_date}</h2>
        <DailyIntelligenceStatusBadge status={report.status} title={statusHint ?? undefined} />
      </div>
      {statusHint ? <p className="text-xs text-muted-foreground max-w-3xl">{statusHint}</p> : null}
      <p className="text-sm text-foreground max-w-3xl leading-relaxed">
        {buildReportDiscoverySummary(report)}
      </p>
      <dl className="grid gap-2 sm:grid-cols-2 text-sm max-w-3xl">
        <div>
          <dt className="text-xs text-muted-foreground">Что анализировали</dt>
          <dd>{formatReportAnalyzedPeriod(report)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Когда зафиксировано</dt>
          <dd>{formatReportGeneratedLine(report)}</dd>
        </div>
      </dl>
      {report.coverage_gaps?.length ? (
        <ZeroContextNote>
          Ограничения покрытия: {report.coverage_gaps.join("; ")}
        </ZeroContextNote>
      ) : null}
    </header>
  );
}
