"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft } from "lucide-react";

import { HelpText, LoadingState, PageHeader, PageShell, SectionPanel } from "@/components/design-system";
import { EvidenceBadge, LifecycleBadge } from "@/components/design-system/status-badges";
import { Select } from "@/components/ui/select";
import { StateMessage } from "@/components/ui/state-message";
import { fetchKeywordPerformanceDetail } from "@/lib/api";
import {
  EVIDENCE_NOT_QUALITY,
  keywordEvidenceStatusLabel,
  LIFECYCLE_NOT_QUALITY,
  NEW_TO_CORPUS_HELP,
  VPH_AT_DISCOVERY_TOOLTIP,
} from "@/lib/keyword-performance-copy";
import {
  formatOptionalNumber,
  formatTopDecileBreakoutRate,
  formatVph,
} from "@/lib/keyword-performance-format";
import {
  metricFamilyFetchFlags,
  type KeywordAttributionMode,
  type KeywordPerformanceMetricFamily,
  type KeywordPerformanceMetrics,
} from "@/lib/keyword-performance-types";
import { formatDateTimeLocal } from "@/lib/monitoring-format";

type DetailFamily = Exclude<KeywordPerformanceMetricFamily, "full">;

export default function KeywordPerformanceDetailPage() {
  const params = useParams();
  const keywordId = Number(params.keywordId);
  const [family, setFamily] = useState<DetailFamily>("discovery");
  const [attribution, setAttribution] = useState<KeywordAttributionMode>("all_hits");
  const [metrics, setMetrics] = useState<KeywordPerformanceMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const hasLoaded = useRef(false);

  const load = useCallback(async () => {
    if (!Number.isFinite(keywordId)) {
      setError("Некорректный id");
      setLoading(false);
      return;
    }
    setLoading(true);
    if (!hasLoaded.current) {
      setError(null);
    }
    try {
      const flags = metricFamilyFetchFlags(family);
      const data = await fetchKeywordPerformanceDetail(keywordId, {
        attribution_mode: attribution,
        ...flags,
      });
      setMetrics(data);
      hasLoaded.current = true;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить ключ");
      if (!hasLoaded.current) {
        setMetrics(null);
      }
    } finally {
      setLoading(false);
    }
  }, [attribution, family, keywordId]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <PageShell>
      <div className="flex flex-wrap items-center gap-4">
        <Link
          href="/keyword-performance"
          className="inline-flex h-8 items-center gap-2 rounded-md px-0 text-sm text-primary hover:underline"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden />
          К списку
        </Link>
        <Link
          href="/keywords"
          className="inline-flex h-8 items-center text-sm text-primary hover:underline"
          data-testid="open-in-keyword-pool"
        >
          Открыть в пуле ключей
        </Link>
      </div>

      <div className="flex flex-wrap gap-3">
        <Select
          value={family}
          onChange={(e) => setFamily(e.target.value as DetailFamily)}
          className="min-w-[160px]"
        >
          <option value="discovery">Discovery</option>
          <option value="breakout">Breakout</option>
          <option value="outcomes">72h исходы</option>
        </Select>
        <Select
          value={attribution}
          onChange={(e) => setAttribution(e.target.value as KeywordAttributionMode)}
          className="min-w-[180px]"
        >
          <option value="all_hits">Все находки</option>
          <option value="first_discovery">Первый источник</option>
        </Select>
      </div>

      {loading && !metrics ? <LoadingState title="Загрузка ключа…" /> : null}
      {error && !metrics ? <StateMessage variant="error" title="Ошибка" description={error} /> : null}

      {metrics ? (
        <>
          <PageHeader title={metrics.keyword} lead={`keyword_id ${metrics.keyword_id}`} />
          <div className="flex flex-wrap items-center gap-2">
            <LifecycleBadge status={metrics.lifecycle_status} title={LIFECYCLE_NOT_QUALITY} />
            <EvidenceBadge
              status={metrics.evidence_status}
              label={keywordEvidenceStatusLabel(metrics.evidence_status)}
            />
          </div>
          <HelpText>{EVIDENCE_NOT_QUALITY}</HelpText>

          {metrics.evaluated_at ? (
            <p className="text-xs text-muted-foreground">
              Срез оценки: {formatDateTimeLocal(metrics.evaluated_at)}
            </p>
          ) : null}

          {(family === "discovery" || family === "breakout" || family === "outcomes") && (
            <SectionPanel title="Discovery">
              <dl className="grid gap-3 text-sm sm:grid-cols-2">
                <div>
                  <dt className="text-muted-foreground">Найдено видео</dt>
                  <dd>{formatOptionalNumber(metrics.unique_video_count)}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Новых для базы</dt>
                  <dd title={NEW_TO_CORPUS_HELP}>{formatOptionalNumber(metrics.new_to_corpus_video_count)}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">VPH при находке (медиана)</dt>
                  <dd title={VPH_AT_DISCOVERY_TOOLTIP}>{formatVph(metrics.median_vph_at_discovery)}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Сканов</dt>
                  <dd>{metrics.scan_count}</dd>
                </div>
              </dl>
            </SectionPanel>
          )}

          {(family === "breakout" || family === "outcomes") && (
            <SectionPanel title="Breakout">
              <p className="text-sm text-muted-foreground">
                Доля top-decile:{" "}
                {formatTopDecileBreakoutRate(
                  metrics.top_decile_breakout_rate,
                  metrics.global_eligible_video_count,
                )}{" "}
                · в top-decile {formatOptionalNumber(metrics.top_decile_breakout_count)}
              </p>
            </SectionPanel>
          )}

          {(family === "outcomes" || family === "discovery") && (
            <SectionPanel title="72h исходы">
              <p className="text-sm text-muted-foreground">
                Валидные исходы:{" "}
                {(metrics.observed_72h_video_count ?? 0) === 0
                  ? "Исходов пока нет"
                  : formatOptionalNumber(metrics.observed_72h_video_count)}{" "}
                · без снимка {formatOptionalNumber(metrics.missing_72h_video_count)} · медиана роста{" "}
                {(metrics.observed_72h_video_count ?? 0) === 0
                  ? "—"
                  : formatOptionalNumber(metrics.median_absolute_view_growth_72h)}
              </p>
            </SectionPanel>
          )}
        </>
      ) : null}

      {!loading && !error && !metrics ? (
        <StateMessage title="Ключ не найден" description="Проверьте id в URL." />
      ) : null}
    </PageShell>
  );
}
