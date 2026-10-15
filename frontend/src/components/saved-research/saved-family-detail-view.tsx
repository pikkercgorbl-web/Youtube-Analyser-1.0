"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ArrowLeft } from "lucide-react";

import {
  ErrorState,
  LoadingState,
  PageHeader,
  PageShell,
  SectionPanel,
} from "@/components/design-system";
import { ObservationHistoryPanel } from "@/components/saved-research/observation-history-panel";
import { SavedResearchAnalystFeedbackPanel } from "@/components/saved-research/saved-research-analyst-feedback-panel";
import { SavedResearchMetadataForm } from "@/components/saved-research/saved-research-metadata-form";
import { SavedResearchValidationPanel } from "@/components/saved-research/saved-research-validation-panel";
import { familyDetailHref } from "@/lib/attention-format";
import {
  archiveSavedFamily,
  getSavedFamily,
  getSavedFamilyHistory,
  getSavedFamilyValidation,
  patchSavedFamily,
  restoreSavedFamily,
} from "@/lib/api";
import {
  familyHistoricalAnchorCounts,
  formatMetricOrUnavailable,
  isDailyIntelligenceAnchorPayload,
  familyObservationSourceLabel,
} from "@/lib/saved-research-format";
import { FAMILY_HISTORICAL_ANCHOR_SAVE_LABEL } from "@/lib/saved-research-labels";
import type {
  SavedFamilyDetail,
  SavedFamilyObservation,
  SavedResearchStatus,
} from "@/lib/saved-research-types";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const HISTORY_PAGE = 20;

export function SavedFamilyDetailView({ familyId }: { familyId: number }) {
  const [detail, setDetail] = useState<SavedFamilyDetail | null>(null);
  const [history, setHistory] = useState<SavedFamilyObservation[]>([]);
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
  const [validation, setValidation] = useState<Record<string, unknown> | null>(null);

  const loadHistory = useCallback(
    async (offset: number, append: boolean) => {
      setHistoryLoading(true);
      try {
        const res = await getSavedFamilyHistory(familyId, { limit: HISTORY_PAGE, offset });
        setHistoryTotal(res.total);
        setHistoryOffset(offset + res.items.length);
        setHistory((prev) => (append ? [...prev, ...res.items] : res.items));
      } finally {
        setHistoryLoading(false);
      }
    },
    [familyId],
  );

  const load = useCallback(async () => {
    setState("loading");
    try {
      const item = await getSavedFamily(familyId);
      setDetail(item);
      setStatus(item.status);
      setNotes(item.notes);
      setTagsText(item.tags.join(", "));
      await loadHistory(0, false);
      const val = await getSavedFamilyValidation(familyId);
      setValidation(val.validation);
      setState("ready");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка загрузки");
      setState("error");
    }
  }, [familyId, loadHistory]);

  useEffect(() => {
    void load();
  }, [load]);

  const onSaveMeta = async () => {
    setSaving(true);
    setSaveMessage(null);
    setSaveError(null);
    try {
      const tags = tagsText
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
      const updated = await patchSavedFamily(familyId, { status, notes, tags });
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
        <LoadingState title="Загрузка темы…" />
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

  const frozenFamily = (detail.frozen_snapshot.family ?? {}) as Record<string, unknown>;
  const live = detail.live_observation;

  return (
    <PageShell>
      <Link
        href="/saved"
        className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "w-fit")}
      >
        <ArrowLeft className="mr-1 h-4 w-4" />
        Сохранённое
      </Link>
      <PageHeader
        title={detail.label}
        lead="Сравните замороженную тему с последним наблюдением Attention."
      />
      <p className="text-sm">
        <Link href={familyDetailHref(detail.family_key)} className="text-primary hover:underline">
          Открыть в «Возможностях»
        </Link>
      </p>
      {detail.archived_at ? (
        <p className="mt-2 text-sm text-amber-200">
          В архиве с {new Date(detail.archived_at).toLocaleString()}
        </p>
      ) : null}
      {detail.absence_message ? (
        <p className="mt-2 text-sm text-muted-foreground">{detail.absence_message}</p>
      ) : null}

      <div className="mt-8 grid gap-6 lg:grid-cols-2">
        <SectionPanel title="Сохранено (заморожено)">
          <p className="text-sm">
            Видео: {formatMetricOrUnavailable(String(frozenFamily.video_count ?? ""))} · Каналы:{" "}
            {formatMetricOrUnavailable(String(frozenFamily.channel_count ?? ""))}
          </p>
        </SectionPanel>
        <SectionPanel
          title="Сейчас (последнее наблюдение)"
          description="Не пересчитывает Attention"
        >
          {live ? (
            isDailyIntelligenceAnchorPayload(live.payload) ? (
              <div className="space-y-2 text-sm">
                <p className="font-medium">{FAMILY_HISTORICAL_ANCHOR_SAVE_LABEL}</p>
                {familyObservationSourceLabel(live.payload) ? (
                  <p className="text-xs text-muted-foreground">
                    {familyObservationSourceLabel(live.payload)}
                  </p>
                ) : null}
                {(() => {
                  const counts = familyHistoricalAnchorCounts(live.payload);
                  return (
                    <p>
                      {live.label ?? detail.label} · видео{" "}
                      {formatMetricOrUnavailable(
                        counts.video_count != null ? String(counts.video_count) : null,
                      )}{" "}
                      · каналы{" "}
                      {formatMetricOrUnavailable(
                        counts.channel_count != null ? String(counts.channel_count) : null,
                      )}
                    </p>
                  );
                })()}
                <p className="text-muted-foreground">Новых live-наблюдений Attention пока нет.</p>
              </div>
            ) : live.family_present ? (
              <p className="text-sm">
                {live.label ?? detail.label} · видео{" "}
                {formatMetricOrUnavailable(live.video_count != null ? String(live.video_count) : null)} ·
                каналы{" "}
                {formatMetricOrUnavailable(
                  live.channel_count != null ? String(live.channel_count) : null,
                )}
                {detail.count_deltas?.video_count != null
                  ? ` (Δ видео ${detail.count_deltas.video_count > 0 ? "+" : ""}${detail.count_deltas.video_count})`
                  : ""}
              </p>
            ) : (
              <p className="text-sm text-muted-foreground">{live.absence_message ?? detail.absence_message}</p>
            )
          ) : (
            <p className="text-sm text-muted-foreground">Наблюдений пока нет.</p>
          )}
        </SectionPanel>
      </div>

      {validation ? (
        <div className="mt-6">
          <SavedResearchValidationPanel validation={validation} kind="family" />
        </div>
      ) : null}

      <div className="mt-6">
        <SavedResearchAnalystFeedbackPanel
          kind="family"
          entityId={familyId}
          archived={Boolean(detail.archived_at)}
        />
      </div>

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
          onArchive={() => void archiveSavedFamily(familyId).then(setDetail)}
          onRestore={() => void restoreSavedFamily(familyId).then(setDetail)}
        />
        <ObservationHistoryPanel
          kind="family"
          items={history}
          total={historyTotal}
          loading={historyLoading}
          hasMore={history.length < historyTotal}
          onLoadMore={() => void loadHistory(historyOffset, true)}
        />
      </div>

      <details className="mt-8 text-xs text-muted-foreground">
        <summary>Технические детали</summary>
        <p className="mt-2">family_key: {detail.family_key}</p>
        <p>run при сохранении: {detail.created_from_attention_run_id ?? "—"}</p>
      </details>
    </PageShell>
  );
}
