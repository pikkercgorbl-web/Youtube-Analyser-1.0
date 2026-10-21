"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, ExternalLink } from "lucide-react";

import {
  ErrorState,
  LoadingState,
  PageHeader,
  PageShell,
  SectionPanel,
} from "@/components/design-system";
import { Button, buttonVariants } from "@/components/ui/button";
import { ObservationHistoryPanel } from "@/components/saved-research/observation-history-panel";
import { SavedResearchAnalystFeedbackPanel } from "@/components/saved-research/saved-research-analyst-feedback-panel";
import { SavedResearchMetadataForm } from "@/components/saved-research/saved-research-metadata-form";
import { SavedResearchValidationPanel } from "@/components/saved-research/saved-research-validation-panel";
import { YoutubeThumb } from "@/components/opportunities/youtube-thumb";
import { savedResearchBackLink } from "@/lib/saved-research-return-nav";
import {
  familyDetailHref,
  formatOptionalAge,
  formatOptionalSubscribers,
  formatOptionalViews,
} from "@/lib/attention-format";
import {
  archiveSavedVideo,
  getSavedVideo,
  getSavedVideoHistory,
  getSavedVideoValidation,
  patchSavedVideo,
  refreshSavedVideoMetrics,
  restoreSavedVideo,
} from "@/lib/api";
import { ChannelBaselinePanel } from "@/components/opportunities/channel-baseline-panel";
import { VideoDiscoveryKeywords } from "@/components/opportunities/video-discovery-keywords";
import { FrozenVideoHighlightBlock } from "@/components/saved-research/frozen-video-highlight-block";
import { frozenVideoHighlightFromPayload } from "@/lib/opportunity-winner-presentation";
import {
  channelRelativeFromEvidence,
  familyLabelsFromContext,
  formatMetricOrUnavailable,
  formatObservationWhen,
  formatVphValue,
  frozenHumanReasons,
  isManualObservationPayload,
  observationSourceLabel,
  parseWinnerEvidence,
  videoObservationAttentionLabel,
  youtubeWatchUrl,
} from "@/lib/saved-research-format";
import { DELAYED_OUTCOME_LABELS } from "@/lib/saved-research-labels";
import type {
  SavedResearchStatus,
  SavedVideoDetail,
  SavedVideoObservation,
} from "@/lib/saved-research-types";
import { buildManualSearchFromSavedUrl } from "@/lib/manual-search-url";
import { SavedVideoSimilarWatchPanel } from "@/components/saved-research/saved-video-similar-watch-panel";
import { cn } from "@/lib/utils";

const HISTORY_PAGE = 20;

function winnerFromObservation(obs: SavedVideoObservation | null): Record<string, unknown> | null {
  if (!obs?.payload?.winner || typeof obs.payload.winner !== "object") {
    return null;
  }
  return obs.payload.winner as Record<string, unknown>;
}

export function SavedVideoDetailView({ videoId }: { videoId: number }) {
  const searchParams = useSearchParams();
  const backLink = useMemo(
    () => savedResearchBackLink(searchParams.get("returnTo")),
    [searchParams],
  );
  const [detail, setDetail] = useState<SavedVideoDetail | null>(null);
  const [history, setHistory] = useState<SavedVideoObservation[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyOffset, setHistoryOffset] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [state, setState] = useState<"loading" | "error" | "ready">("loading");
  const [error, setError] = useState("");
  const [status, setStatus] = useState<SavedResearchStatus>("WATCHING");
  const [notes, setNotes] = useState("");
  const [tagsText, setTagsText] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [refreshCooldownUntil, setRefreshCooldownUntil] = useState<number | null>(null);
  const [validation, setValidation] = useState<Record<string, unknown> | null>(null);

  const loadHistory = useCallback(
    async (offset: number, append: boolean) => {
      setHistoryLoading(true);
      try {
        const res = await getSavedVideoHistory(videoId, { limit: HISTORY_PAGE, offset });
        setHistoryTotal(res.total);
        setHistoryOffset(offset + res.items.length);
        setHistory((prev) => (append ? [...prev, ...res.items] : res.items));
      } finally {
        setHistoryLoading(false);
      }
    },
    [videoId],
  );

  const load = useCallback(async () => {
    setState("loading");
    try {
      const item = await getSavedVideo(videoId);
      setDetail(item);
      setStatus(item.status);
      setNotes(item.notes);
      setTagsText(item.tags.join(", "));
      await loadHistory(0, false);
      const val = await getSavedVideoValidation(videoId);
      setValidation(val.validation);
      setState("ready");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка загрузки");
      setState("error");
    }
  }, [videoId, loadHistory]);

  useEffect(() => {
    void load();
  }, [load]);

  const frozen = detail?.frozen_snapshot ?? {};
  const identity = (frozen.identity ?? {}) as Record<string, unknown>;
  const frozenEvidence = useMemo(() => parseWinnerEvidence(frozen.evidence), [frozen]);
  const live = detail?.live_observation ?? null;
  const liveWinner = winnerFromObservation(live);

  const frozenRel = channelRelativeFromEvidence(frozenEvidence);
  const liveRel = channelRelativeFromEvidence(
    liveWinner ? (liveWinner as Record<string, unknown>) : null,
  );
  const frozenHighlight = useMemo(
    () => frozenVideoHighlightFromPayload(detail?.frozen_snapshot ?? {}),
    [detail?.frozen_snapshot],
  );

  const onRefreshMetrics = async () => {
    if (refreshCooldownUntil != null && Date.now() < refreshCooldownUntil) {
      return;
    }
    setRefreshing(true);
    setRefreshError(null);
    try {
      const res = await refreshSavedVideoMetrics(videoId);
      setDetail(res.item);
      setRefreshCooldownUntil(Date.now() + res.cooldown_seconds * 1000);
      await loadHistory(0, false);
      const val = await getSavedVideoValidation(videoId);
      setValidation(val.validation);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Не удалось обновить метрики";
      setRefreshError(message);
      if (typeof err === "object" && err !== null && "response" in err) {
        const retry = (err as { response?: { headers?: { "retry-after"?: string } } }).response
          ?.headers?.["retry-after"];
        if (retry) {
          const sec = Number(retry);
          if (Number.isFinite(sec) && sec > 0) {
            setRefreshCooldownUntil(Date.now() + sec * 1000);
          }
        }
      }
    } finally {
      setRefreshing(false);
    }
  };

  const onSaveMeta = async () => {
    setSaving(true);
    setSaveMessage(null);
    setSaveError(null);
    try {
      const tags = tagsText
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
      const updated = await patchSavedVideo(videoId, { status, notes, tags });
      setDetail(updated);
      setSaveMessage("Сохранено");
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  };

  if (state === "loading") {
    return (
      <PageShell>
        <LoadingState title="Загрузка видео…" />
      </PageShell>
    );
  }
  if (state === "error") {
    return (
      <PageShell>
        <ErrorState title={error} onRetry={() => void load()} />
      </PageShell>
    );
  }
  if (!detail) return null;

  const title = String(identity.title ?? detail.video_id);
  const ytUrl = youtubeWatchUrl(
    detail.video_id,
    typeof identity.youtube_url === "string" ? identity.youtube_url : null,
  );
  const savedFamilies = familyLabelsFromContext(frozen);
  const liveFamilies = live?.family_memberships ?? [];
  const frozenReasonCodes = Array.isArray(frozenEvidence?.reason_codes)
    ? (frozenEvidence!.reason_codes as string[])
    : [];
  const frozenHumanReasonLines = frozenHumanReasons(frozen);

  return (
    <PageShell>
      <Link
        href={backLink.href}
        className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "w-fit")}
      >
        <ArrowLeft className="mr-1 h-4 w-4" />
        {backLink.label}
      </Link>
      <div className="mt-4 grid gap-6 lg:grid-cols-[minmax(0,280px)_1fr]">
        <YoutubeThumb videoId={detail.video_id} title={title} className="aspect-video w-full rounded-xl" />
        <div>
          <PageHeader title={title} lead={String(identity.channel_title ?? "")} />
          <FrozenVideoHighlightBlock view={frozenHighlight} />
          <div className="mt-2 flex flex-wrap gap-2">
            {!detail.archived_at ? (
              <Link
                href={buildManualSearchFromSavedUrl({
                  sourceSavedId: detail.id,
                  sourceVideoId: detail.video_id,
                  initialQuery: title,
                })}
                className={buttonVariants({ variant: "secondary", size: "sm" })}
              >
                Исследовать тему
              </Link>
            ) : null}
            <a
              href={ytUrl}
              target="_blank"
              rel="noopener noreferrer"
              className={cn(buttonVariants({ variant: "default", size: "sm" }), "inline-flex gap-2")}
            >
              Открыть на YouTube
              <ExternalLink className="h-4 w-4" aria-hidden />
            </a>
            {!detail.archived_at ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={
                  refreshing ||
                  (refreshCooldownUntil != null && Date.now() < refreshCooldownUntil)
                }
                onClick={() => void onRefreshMetrics()}
              >
                {refreshing ? "Обновление…" : "Обновить статистику"}
              </Button>
            ) : null}
          </div>
          {refreshError ? <p className="mt-2 text-sm text-destructive">{refreshError}</p> : null}
          {live && isManualObservationPayload(live.payload) ? (
            <p className="mt-2 text-xs text-muted-foreground">
              Последнее измерение: {formatObservationWhen(live.observed_at)} ·{" "}
              {observationSourceLabel(live.payload) ?? "YouTube Data API"}
            </p>
          ) : null}
          <p className="mt-2 text-xs text-muted-foreground">
            Сохранено {new Date(detail.saved_at).toLocaleString()}
          </p>
        </div>
      </div>

      {detail.archived_at ? (
        <p className="mt-4 text-sm text-amber-200">
          В архиве с {new Date(detail.archived_at).toLocaleString()}
        </p>
      ) : null}

      {validation ? (
        <div className="mt-6">
          <SavedResearchValidationPanel validation={validation} kind="video" />
        </div>
      ) : null}

      <div className="mt-6">
        <SavedResearchAnalystFeedbackPanel
          kind="video"
          entityId={videoId}
          archived={Boolean(detail.archived_at)}
        />
      </div>

      <div className="mt-8 grid gap-6 lg:grid-cols-2">
        <SectionPanel title="Сохранено (заморожено)" description="Снимок на момент сохранения">
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <dt className="text-muted-foreground">Просмотры</dt>
              <dd className="font-semibold tabular-nums">
                {formatMetricOrUnavailable(formatOptionalViews(frozenEvidence?.views as number))}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">VPH</dt>
              <dd className="font-semibold tabular-nums">
                {formatMetricOrUnavailable(formatVphValue(frozenEvidence?.vph as number))}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Подписчики</dt>
              <dd>{formatMetricOrUnavailable(formatOptionalSubscribers(frozenEvidence?.subscribers as number))}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Breakout</dt>
              <dd>
                {frozenEvidence?.breakout_rank != null
                  ? `#${String(frozenEvidence.breakout_rank)}`
                  : "—"}
              </dd>
            </div>
          </dl>
          <ChannelBaselinePanel rel={frozenRel} className="mt-3" />
          {frozenHumanReasonLines.length > 0 ||
          frozenReasonCodes.length > 0 ||
          frozenRel ? (
            <details className="mt-4 text-sm" data-testid="saved-video-how-calculated">
              <summary className="cursor-pointer font-medium text-foreground">
                Как рассчитано
              </summary>
              <div className="mt-3 space-y-3 text-muted-foreground">
                {frozenHumanReasonLines.length > 0 ? (
                  <ul className="list-disc space-y-1 pl-5">
                    {frozenHumanReasonLines.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                ) : (
                  <p>Текстовые пояснения Radar в снимке не сохранены.</p>
                )}
                {frozenReasonCodes.length > 0 ? (
                  <p className="font-mono text-xs text-muted-foreground">
                    reason_codes: {frozenReasonCodes.join(", ")}
                  </p>
                ) : null}
                {frozenRel ? <ChannelBaselinePanel rel={frozenRel} /> : null}
              </div>
            </details>
          ) : null}
        </SectionPanel>

        <SectionPanel title="Сейчас (последнее наблюдение)" description="Не пересчитывает Attention">
          {live ? (
            <>
              {detail.attention_absence_message ? (
                <p className="text-sm text-muted-foreground">{detail.attention_absence_message}</p>
              ) : null}
              {!live.video_present_in_attention && live.monitoring_snapshot_available ? (
                <p className="mt-2 text-sm text-muted-foreground">
                  Видео не в текущей подборке Attention, но в Monitoring уже есть снимки — оно могло
                  попасть в corpus раньше (Discovery), независимо от того, откуда вы его сохранили.
                </p>
              ) : null}
              {!live.video_present_in_attention && !live.monitoring_snapshot_available ? (
                <p className="mt-2 text-sm text-muted-foreground">
                  Сохранение в портфель не включает автоматический Monitoring и не добавляет ролик в
                  подборку Attention. Наблюдение в Radar идёт через Discovery и read model; здесь вы
                  фиксируете заметку и метрики вручную.
                </p>
              ) : null}
              <dl className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <dt className="text-muted-foreground">Просмотры</dt>
                  <dd className="font-semibold tabular-nums">
                    {formatMetricOrUnavailable(formatOptionalViews(live.views))}
                    {detail.metric_deltas?.views != null
                      ? ` (${detail.metric_deltas.views > 0 ? "+" : ""}${detail.metric_deltas.views})`
                      : ""}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">VPH</dt>
                  <dd className="font-semibold tabular-nums">
                    {formatMetricOrUnavailable(formatVphValue(live.vph))}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Attention</dt>
                  <dd>
                    {videoObservationAttentionLabel({
                      video_present_in_attention: live.video_present_in_attention,
                      payload: live.payload,
                    })}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Monitoring</dt>
                  <dd>{live.monitoring_snapshot_available ? "снимок доступен" : "снимок недоступен"}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">72ч</dt>
                  <dd>
                    {live.delayed_outcome_state
                      ? DELAYED_OUTCOME_LABELS[live.delayed_outcome_state] ?? live.delayed_outcome_state
                      : "—"}
                  </dd>
                </div>
              </dl>
              <ChannelBaselinePanel rel={liveRel} className="mt-3" />
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Наблюдений пока нет.</p>
          )}
        </SectionPanel>
      </div>

      <SectionPanel title="Запросы обнаружения" className="mt-6">
        <VideoDiscoveryKeywords
          videoId={detail.video_id}
          keywords={detail.discovery_keywords ?? []}
        />
      </SectionPanel>

      <div className="mt-6">
        <SavedVideoSimilarWatchPanel
          savedVideoId={detail.id}
          archived={Boolean(detail.archived_at)}
        />
      </div>

      <SectionPanel title="Подборки с этим видео" className="mt-6">
        <p className="text-sm font-medium">На момент сохранения</p>
        {savedFamilies.length ? (
          <ul className="mt-2 text-sm list-disc pl-5">
            {savedFamilies.map((label) => (
              <li key={label}>{label}</li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground mt-2">Нет связанных family в снимке сохранения.</p>
        )}
        {liveFamilies.length > 0 ? (
          <>
            <p className="text-sm font-medium mt-4">В последнем наблюдении</p>
            <ul className="mt-2 space-y-1 text-sm">
              {liveFamilies.map((f) => (
                <li key={f.family_key}>
                  <Link href={familyDetailHref(f.family_key)} className="text-primary hover:underline">
                    {f.label}
                  </Link>
                </li>
              ))}
            </ul>
          </>
        ) : null}
      </SectionPanel>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <SavedResearchMetadataForm
          status={status}
          notes={notes}
          tagsText={tagsText}
          archivedAt={detail.archived_at}
          saving={saving}
          saveMessage={saveMessage}
          saveError={saveError}
          onStatusChange={setStatus}
          onNotesChange={setNotes}
          onTagsChange={setTagsText}
          onSave={() => void onSaveMeta()}
          onArchive={() =>
            void archiveSavedVideo(videoId).then((updated) => {
              setDetail(updated);
            })
          }
          onRestore={() =>
            void restoreSavedVideo(videoId).then((updated) => {
              setDetail(updated);
            })
          }
        />
        <ObservationHistoryPanel
          kind="video"
          items={history}
          total={historyTotal}
          loading={historyLoading}
          hasMore={history.length < historyTotal}
          onLoadMore={() => void loadHistory(historyOffset, true)}
        />
      </div>

      <details className="mt-8 text-xs text-muted-foreground">
        <summary>Технические детали</summary>
        <p className="mt-2">video_id: {detail.video_id}</p>
        <p>run при сохранении: {detail.created_from_attention_run_id ?? "—"}</p>
        <p>
          возраст при сохранении:{" "}
          {formatMetricOrUnavailable(formatOptionalAge(frozenEvidence?.age_hours as number))}
        </p>
      </details>
    </PageShell>
  );
}
