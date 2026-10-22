"use client";

import type { ReactNode } from "react";

import { ErrorState, LoadingState, Metric, MetricGroup, SectionPanel } from "@/components/design-system";
import { formatComparisonMetricsBlock, formatOutcomeTimestamp } from "@/lib/daily-intelligence-outcome-format";
import {
  attentionViewsSourceLabel,
  metricsInterpretationLabel,
  outcomeCoverageCategoryLabel,
  outcomeWindowPhaseLabel,
} from "@/lib/daily-intelligence-outcome-labels";
import type { DailyIntelligenceWinnerOutcomeFollowUp } from "@/lib/daily-intelligence-outcome-types";
import { formatDateTimeLocal } from "@/lib/monitoring-format";

import { DailyIntelligenceFrozenJson } from "./daily-intelligence-frozen-json";
import { DailyIntelligenceOutcomeCoverageBadge } from "./daily-intelligence-outcome-coverage-badge";

function readString(obj: Record<string, unknown>, key: string): string | null {
  const v = obj[key];
  return typeof v === "string" && v ? v : null;
}

function readNumber(obj: Record<string, unknown>, key: string): number | null {
  const v = obj[key];
  return typeof v === "number" && !Number.isNaN(v) ? v : null;
}

function FollowUpShell({
  embedded,
  children,
}: {
  embedded?: boolean;
  children: ReactNode;
}) {
  if (embedded) {
    return <div className="space-y-4">{children}</div>;
  }
  return (
    <SectionPanel
      title="Historical Follow-up"
      description="Сравнение frozen daily edition с horizon outcome snapshot. Не live Attention."
    >
      {children}
    </SectionPanel>
  );
}

export function DailyIntelligenceHistoricalFollowUpPanel({
  followUp,
  loading,
  error,
  onRetry,
  embedded,
}: {
  followUp: DailyIntelligenceWinnerOutcomeFollowUp | null;
  loading: boolean;
  error: string | null;
  onRetry?: () => void;
  embedded?: boolean;
}) {
  if (loading && !followUp) {
    return (
      <FollowUpShell embedded={embedded}>
        <LoadingState variant="inline" title="Загрузка follow-up…" />
      </FollowUpShell>
    );
  }

  if (error && !followUp) {
    return (
      <FollowUpShell embedded={embedded}>
        <ErrorState
          title="Follow-up недоступен"
          description={`${error}. Остальные блоки winner остаются без изменений.`}
          compact
          onRetry={onRetry}
        />
      </FollowUpShell>
    );
  }

  if (!followUp) {
    return null;
  }

  const signals = followUp.signal_timestamps as Record<string, unknown>;
  const anchor = followUp.discovery_outcome_anchor as Record<string, unknown>;
  const outcome = followUp.outcome_measurement as Record<string, unknown>;
  const frozenDelayed = followUp.frozen_delayed_outcome as Record<string, unknown>;
  const prov = followUp.attention_views_provenance;
  const metrics = formatComparisonMetricsBlock(followUp.comparison_metrics);

  const showVerifiedGrowth =
    followUp.coverage_category === "MEASURED_POST_SIGNAL" &&
    prov.baseline_provenance_verified &&
    followUp.comparison_metrics.verified_post_signal_growth != null;

  const categoryLabel = outcomeCoverageCategoryLabel(
    followUp.coverage_category,
    followUp.outcome_window_phase,
  );

  return (
    <FollowUpShell embedded={embedded}>
      <div data-testid="di-historical-followup">
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <DailyIntelligenceOutcomeCoverageBadge
          category={followUp.coverage_category}
          phase={followUp.outcome_window_phase}
        />
        {followUp.coverage_reason ? (
          <span className="text-xs text-muted-foreground">{followUp.coverage_reason}</span>
        ) : null}
      </div>

      <div className="space-y-6">
        <div>
          <h3 className="text-sm font-medium">A. Статус и время</h3>
          <dl className="mt-2 grid gap-2 sm:grid-cols-2 text-sm">
            <div>
              <dt className="text-xs text-muted-foreground">Категория покрытия</dt>
              <dd>{categoryLabel}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Фаза outcome-окна</dt>
              <dd>{outcomeWindowPhaseLabel(followUp.outcome_window_phase)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Discovery (timestamp)</dt>
              <dd>{formatOutcomeTimestamp(anchor.discovered_at)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Первый signal (run)</dt>
              <dd>{formatOutcomeTimestamp(signals.first_signal_source_computed_at)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Edition signal (daily edition)</dt>
              <dd>{formatOutcomeTimestamp(signals.edition_signal_source_computed_at)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Целевой момент outcome (+72h)</dt>
              <dd>{formatOutcomeTimestamp(anchor.outcome_window_target_at)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Фактический снимок outcome</dt>
              <dd>{formatOutcomeTimestamp(outcome.snapshot_captured_at)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Пересчитано</dt>
              <dd>{formatDateTimeLocal(followUp.reference_evaluated_at)}</dd>
            </div>
          </dl>
          <p className="mt-3 text-xs text-muted-foreground max-w-prose">
            Окно измерения: discovery +{readNumber(anchor, "horizon_hours") ?? 72}h с допуском ±
            {readNumber(anchor, "tolerance_hours") ?? 12}h UTC (
            {formatOutcomeTimestamp(anchor.outcome_window_start_at)} —{" "}
            {formatOutcomeTimestamp(anchor.outcome_window_end_at)}).
          </p>
        </div>

        <div className="border-t border-border/50 pt-4">
          <h3 className="text-sm font-medium">B. Измерения</h3>
          <MetricGroup>
            <Metric
              label="Frozen attention views (baseline)"
              value={metrics.frozenViews}
              helper={
                prov.baseline_provenance_verified
                  ? "Baseline с подтверждённым происхождением"
                  : "Описательное значение — verified baseline не подтверждён"
              }
            />
            <Metric label="Outcome views (horizon)" value={metrics.outcomeViews} />
            <Metric
              label="Δ просмотров (описательно)"
              value={metrics.deltaDescriptive}
              helper="Не verified post-signal growth"
            />
            <Metric label="Описательный ratio" value={metrics.ratioDescriptive} />
            {showVerifiedGrowth ? (
              <Metric
                label="Verified post-signal growth"
                value={metrics.verifiedGrowth}
                helper={`Ratio: ${metrics.verifiedRatio}`}
              />
            ) : followUp.coverage_category === "MEASURED_PRE_SIGNAL" ? (
              <Metric
                label="Post-signal growth"
                value="—"
                helper="Outcome до edition signal — post-signal growth не показываем"
              />
            ) : null}
            <Metric
              label="Часов edition signal → outcome"
              value={metrics.elapsedHours}
            />
          </MetricGroup>
          {followUp.comparison_metrics.metrics_reason ? (
            <p className="mt-2 text-xs text-muted-foreground">
              {followUp.comparison_metrics.metrics_reason}
            </p>
          ) : null}
        </div>

        <div className="border-t border-border/50 pt-4">
          <h3 className="text-sm font-medium">C. Provenance</h3>
          <ul className="mt-2 space-y-2 text-sm text-muted-foreground">
            <li>
              <span className="text-foreground">Источник frozen views: </span>
              {attentionViewsSourceLabel(prov.attention_views_source)}
            </li>
            <li>
              <span className="text-foreground">Baseline verified: </span>
              {prov.baseline_provenance_verified ? "Да" : "Нет — временное происхождение frozen просмотров не доказано"}
            </li>
            {prov.candidate_baseline_snapshot_at ? (
              <li>
                <span className="text-foreground">Возможный исходный snapshot: </span>
                {formatDateTimeLocal(prov.candidate_baseline_snapshot_at)}
              </li>
            ) : null}
            <li>
              <span className="text-foreground">Интерпретация метрик: </span>
              {metricsInterpretationLabel(followUp.metrics_interpretation)}
            </li>
          </ul>
        </div>

        <div className="border-t border-border/50 pt-4">
          <h3 className="text-sm font-medium">D. Historical integrity</h3>
          <p className="mt-2 text-sm text-muted-foreground">
            Значения из frozen payload на момент публикации Attention (отдельно от вновь найденного horizon
            outcome):
          </p>
          <MetricGroup>
            <Metric
              label="Frozen delayed_outcome_state"
              value={readString(frozenDelayed, "delayed_outcome_state") ?? "—"}
            />
            <Metric
              label="Frozen delayed_outcome_growth"
              value={readString(frozenDelayed, "delayed_outcome_growth") ?? "—"}
            />
          </MetricGroup>
          <p className="mt-3 text-xs text-muted-foreground">
            Live Attention не пересчитывается. Follow-up использует сохранённые snapshots и frozen evidence.
          </p>
          <DailyIntelligenceFrozenJson
            label="Raw follow-up payload (JSON)"
            payload={followUp as unknown as Record<string, unknown>}
          />
        </div>
      </div>
      </div>
    </FollowUpShell>
  );
}
