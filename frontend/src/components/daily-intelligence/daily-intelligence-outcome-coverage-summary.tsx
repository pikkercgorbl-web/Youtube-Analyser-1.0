"use client";

import { LoadingState } from "@/components/design-system";
import {
  OUTCOME_COVERAGE_CATEGORY_ORDER,
  outcomeCoverageCategoryLabel,
} from "@/lib/daily-intelligence-outcome-labels";
import type { DailyIntelligenceOutcomeCoverageResponse } from "@/lib/daily-intelligence-outcome-types";
import { formatDateTimeLocal } from "@/lib/monitoring-format";

const SUMMARY_LABEL: Record<string, string> = {
  MEASURED_POST_SIGNAL: "Измерено post-signal",
  MEASURED_PRE_SIGNAL: "Измерено pre-signal",
  NOT_MATURED: "Не созрел",
  MATURED_MISSING: "Окно закрыто, нет снимка",
  INVALID_TIMELINE: "Некорректный timeline",
  INSUFFICIENT_EVIDENCE: "Недостаточно данных",
};

export function DailyIntelligenceOutcomeCoverageSummary({
  data,
  loading,
  error,
  onRetry,
}: {
  data: DailyIntelligenceOutcomeCoverageResponse | null;
  loading: boolean;
  error: string | null;
  onRetry?: () => void;
}) {
  if (loading && !data) {
    return <LoadingState variant="inline" title="Загрузка outcome coverage…" />;
  }

  if (error && !data) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="di-outcome-coverage-error">
        Покрытие historical outcome недоступно: {error}. Таблица winners работает без категорий follow-up.
        {onRetry ? (
          <button type="button" className="ml-2 text-primary hover:underline" onClick={onRetry}>
            Повторить
          </button>
        ) : null}
      </p>
    );
  }

  if (!data) {
    return null;
  }

  const counts = data.coverage_by_category ?? data.coverage_counts ?? {};

  return (
    <div className="space-y-3" data-testid="di-outcome-coverage-summary">
      <p className="text-xs text-muted-foreground">
        Окно horizon outcome: discovery +72h ±12h (UTC). Пересчитано:{" "}
        {formatDateTimeLocal(data.reference_evaluated_at)}. Edition signal:{" "}
        {data.edition_signal_source_computed_at
          ? formatDateTimeLocal(data.edition_signal_source_computed_at)
          : "—"}
      </p>
      <dl className="grid gap-2 grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 text-sm">
        <div className="rounded-lg border border-border/80 px-3 py-2">
          <dt className="text-xs text-muted-foreground">Всего winners</dt>
          <dd className="tabular-nums font-medium">{data.winner_count}</dd>
        </div>
        {OUTCOME_COVERAGE_CATEGORY_ORDER.map((key) => (
          <div key={key} className="rounded-lg border border-border/80 px-3 py-2">
            <dt className="text-xs text-muted-foreground" title={outcomeCoverageCategoryLabel(key)}>
              {SUMMARY_LABEL[key] ?? key}
            </dt>
            <dd className="tabular-nums font-medium">{counts[key] ?? 0}</dd>
          </div>
        ))}
      </dl>
      {error ? (
        <p className="text-xs text-amber-200/90">
          Не удалось обновить coverage: {error}. Показаны последние загруженные данные.
        </p>
      ) : null}
    </div>
  );
}
