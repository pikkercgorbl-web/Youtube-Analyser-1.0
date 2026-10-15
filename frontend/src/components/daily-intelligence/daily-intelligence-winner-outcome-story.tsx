"use client";

import { ErrorState, LoadingState, SectionPanel } from "@/components/design-system";
import { formatComparisonMetricsBlock } from "@/lib/daily-intelligence-outcome-format";
import type { DailyIntelligenceWinnerOutcomeFollowUp } from "@/lib/daily-intelligence-outcome-types";
import {
  OUTCOME_TONE_CLASS,
  outcomeComparisonLimitationNote,
  outcomeResearchCopy,
} from "@/lib/daily-intelligence-winner-research";
import { cn } from "@/lib/utils";

import { DailyIntelligenceWinnerStatCard } from "./daily-intelligence-winner-stat-card";

export function DailyIntelligenceWinnerOutcomeStory({
  followUp,
  loading,
  error,
  onRetry,
}: {
  followUp: DailyIntelligenceWinnerOutcomeFollowUp | null;
  loading: boolean;
  error: string | null;
  onRetry?: () => void;
}) {
  if (loading && !followUp) {
    return (
      <SectionPanel title="Что произошло дальше" description="Контрольное измерение ≈72h после discovery.">
        <LoadingState variant="inline" title="Загружаем статус измерения…" />
      </SectionPanel>
    );
  }

  if (error && !followUp) {
    return (
      <SectionPanel title="Что произошло дальше">
        <ErrorState
          title="Статус контрольного измерения недоступен"
          description={`${error}. Остальная информация о подборке сохранена.`}
          compact
          onRetry={onRetry}
        />
      </SectionPanel>
    );
  }

  if (!followUp) {
    return null;
  }

  const copy = outcomeResearchCopy(followUp.coverage_category, followUp.outcome_window_phase);
  const metrics = formatComparisonMetricsBlock(followUp.comparison_metrics);
  const limitation = outcomeComparisonLimitationNote(followUp);
  const showDescriptive =
    followUp.comparison_metrics.delta_views_descriptive != null &&
    followUp.coverage_category === "MEASURED_POST_SIGNAL";

  return (
    <SectionPanel
      title="Что произошло дальше"
      description="Сравнение frozen подборки с horizon outcome по сохранённым snapshots."
    >
      <div
        className={cn("rounded-xl border px-4 py-4 max-w-3xl", OUTCOME_TONE_CLASS[copy.tone])}
        data-testid="di-outcome-story-status"
      >
        <p className="font-medium text-sm">{copy.headline}</p>
        <p className="mt-2 text-sm text-muted-foreground leading-relaxed">{copy.explanation}</p>
        {copy.nextStep ? (
          <p className="mt-2 text-xs text-muted-foreground">{copy.nextStep}</p>
        ) : null}
      </div>

      <div className="mt-5 grid gap-3 grid-cols-2 lg:grid-cols-4">
        <DailyIntelligenceWinnerStatCard
          label="Просмотры при подборке"
          value={metrics.frozenViews}
        />
        <DailyIntelligenceWinnerStatCard
          label="Просмотры на horizon"
          value={metrics.outcomeViews}
        />
        {showDescriptive ? (
          <>
            <DailyIntelligenceWinnerStatCard
              label="Разница (описательно)"
              value={metrics.deltaDescriptive}
              hint="Не подтверждённый рост после сигнала"
            />
            <DailyIntelligenceWinnerStatCard
              label="Отношение (описательно)"
              value={metrics.ratioDescriptive}
            />
          </>
        ) : (
          <DailyIntelligenceWinnerStatCard
            label="Разница просмотров"
            value="—"
            hint={
              followUp.coverage_category === "MEASURED_PRE_SIGNAL"
                ? "Измерение до финала дня — delta post-signal не показываем"
                : "Нет валидного сравнения"
            }
          />
        )}
      </div>

      {limitation ? (
        <p className="mt-4 text-sm text-muted-foreground max-w-3xl border-l-2 border-amber-500/50 pl-3">
          {limitation}
        </p>
      ) : null}

      {followUp.attention_views_provenance.baseline_provenance_verified &&
      followUp.comparison_metrics.verified_post_signal_growth != null ? (
        <p className="mt-3 text-xs text-muted-foreground max-w-3xl">
          Подтверждённый baseline в payload: verified post-signal growth{" "}
          {metrics.verifiedGrowth} (ratio {metrics.verifiedRatio}).
        </p>
      ) : null}
    </SectionPanel>
  );
}
