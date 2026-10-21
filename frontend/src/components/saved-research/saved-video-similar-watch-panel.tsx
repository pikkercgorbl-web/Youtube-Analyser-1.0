"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronDown, Loader2 } from "lucide-react";

import { SectionPanel } from "@/components/design-system";
import { SavedVideoSimilarFindingCard } from "@/components/saved-research/saved-video-similar-finding-card";
import { Button } from "@/components/ui/button";
import {
  confirmSavedVideoSimilarWatch,
  getSavedVideoSimilarFindings,
  getSavedVideoSimilarWatch,
  pauseSavedVideoSimilarWatch,
  resumeSavedVideoSimilarWatch,
  runSavedVideoSimilarWatchNow,
  saveSimilarFinding,
  setSimilarFindingFeedback,
} from "@/lib/api";
import type {
  SavedVideoSimilarFinding,
  SavedVideoSimilarWatch,
} from "@/lib/saved-research-types";

const DISPLAY_LABELS: Record<string, string> = {
  not_configured: "Поиск по похожим ещё не настраивали",
  draft: "Подтвердите запросы и запустите поиск",
  paused: "Поиск остановлен",
  scanning: "Идёт поиск…",
  never_checked: "Запросы подтверждены — нажмите «Запустить поиск сейчас»",
  empty: "Проверили по вашим запросам — в базе нет сохранённых находок этого скана",
  has_results: "Есть результаты поиска (основной список — тематически близкие)",
  partial_error: "Часть запросов завершилась с ошибкой; остальные результаты ниже",
};

type Props = {
  savedVideoId: number;
  archived: boolean;
};

export function SavedVideoSimilarWatchPanel({ savedVideoId, archived }: Props) {
  const [watch, setWatch] = useState<SavedVideoSimilarWatch | null>(null);
  const [queries, setQueries] = useState<string[]>([]);
  const [primaryFindings, setPrimaryFindings] = useState<SavedVideoSimilarFinding[]>([]);
  const [otherFindings, setOtherFindings] = useState<SavedVideoSimilarFinding[]>([]);
  const [otherTotal, setOtherTotal] = useState(0);
  const [showOther, setShowOther] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const w = await getSavedVideoSimilarWatch(savedVideoId);
      setWatch(w);
      const initial =
        w.confirmed_queries.length > 0 ? w.confirmed_queries : w.suggested_queries;
      setQueries(initial.length ? [...initial] : [""]);
      const f = await getSavedVideoSimilarFindings(savedVideoId, {
        primary_limit: 30,
        other_limit: 100,
      });
      setPrimaryFindings(f.primary_items);
      setOtherFindings(f.other_items);
      setOtherTotal(f.other_total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  }, [savedVideoId]);

  useEffect(() => {
    void load();
  }, [load]);

  const updateQuery = (index: number, value: string) => {
    setQueries((prev) => prev.map((q, i) => (i === index ? value : q)));
  };

  const addQuery = () => {
    if (queries.length >= 5) return;
    setQueries((prev) => [...prev, ""]);
  };

  const removeQuery = (index: number) => {
    setQueries((prev) => prev.filter((_, i) => i !== index));
  };

  const onConfirm = async () => {
    setBusy(true);
    setError(null);
    try {
      const cleaned = queries.map((q) => q.trim()).filter(Boolean);
      if (cleaned.length < 1) {
        setError("Нужен хотя бы один запрос");
        return;
      }
      const w = await confirmSavedVideoSimilarWatch(savedVideoId, cleaned);
      setWatch(w);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось подтвердить");
    } finally {
      setBusy(false);
    }
  };

  const onRunNow = async () => {
    setBusy(true);
    setError(null);
    setWatch((prev) => (prev ? { ...prev, display_state: "scanning" } : prev));
    try {
      await runSavedVideoSimilarWatchNow(savedVideoId);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Поиск не выполнен");
      await load();
    } finally {
      setBusy(false);
    }
  };

  const onPause = async () => {
    setBusy(true);
    try {
      const w = await pauseSavedVideoSimilarWatch(savedVideoId);
      setWatch(w);
    } finally {
      setBusy(false);
    }
  };

  const onResume = async () => {
    setBusy(true);
    try {
      const w = await resumeSavedVideoSimilarWatch(savedVideoId);
      setWatch(w);
    } finally {
      setBusy(false);
    }
  };

  const patchFinding = (
    findingId: number,
    patch: Partial<Pick<SavedVideoSimilarFinding, "user_verdict" | "saved_to_research">>,
  ) => {
    const apply = (list: SavedVideoSimilarFinding[]) =>
      list.map((f) => (f.id === findingId ? { ...f, ...patch } : f));
    setPrimaryFindings(apply);
    setOtherFindings(apply);
  };

  const onSaveFinding = async (findingId: number) => {
    try {
      await saveSimilarFinding(savedVideoId, findingId);
      patchFinding(findingId, { saved_to_research: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка сохранения");
    }
  };

  const onFeedback = async (findingId: number, verdict: "fit" | "not_fit") => {
    try {
      const updated = await setSimilarFindingFeedback(savedVideoId, findingId, verdict);
      patchFinding(findingId, { user_verdict: updated.user_verdict ?? verdict });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить оценку");
    }
  };

  if (loading) {
    return (
      <SectionPanel title="Поиск похожих">
        <p className="text-sm text-muted-foreground">Загрузка…</p>
      </SectionPanel>
    );
  }

  const displayState = watch?.display_state ?? "not_configured";
  const statusLabel = DISPLAY_LABELS[displayState] ?? displayState;
  const isActive = watch?.status === "active";
  const isPaused = watch?.status === "paused";
  const hasAnyFindings = primaryFindings.length > 0 || otherTotal > 0;

  return (
    <SectionPanel
      title="Найдено по вашим запросам"
      description="Отдельный поиск YouTube по вашим формулировкам. Не влияет на «Возможности» и Monitoring."
    >
      {archived ? (
        <p className="text-sm text-amber-200">В архиве — поиск приостановлен.</p>
      ) : null}
      {error ? <p className="text-sm text-destructive">{error}</p> : null}
      <p className="text-sm font-medium">{statusLabel}</p>
      {watch?.last_scan_at ? (
        <p className="text-xs text-muted-foreground">
          Последняя проверка: {new Date(watch.last_scan_at).toLocaleString()}
          {watch.last_error ? ` · ${watch.last_error}` : ""}
        </p>
      ) : null}

      {!archived ? (
        <div className="mt-4 space-y-2">
          <p className="text-xs text-muted-foreground">
            Варианты запросов из названия (можно изменить). Это не рекомендации ИИ.
          </p>
          {queries.map((q, i) => (
            <div key={i} className="flex gap-2">
              <input
                className="flex-1 rounded-md border border-border bg-background px-2 py-1 text-sm"
                value={q}
                onChange={(e) => updateQuery(i, e.target.value)}
                disabled={busy || isActive}
                aria-label={`Запрос ${i + 1}`}
              />
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={queries.length <= 1 || busy}
                onClick={() => removeQuery(i)}
              >
                Удалить
              </Button>
            </div>
          ))}
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" size="sm" disabled={queries.length >= 5 || busy} onClick={addQuery}>
              Добавить запрос
            </Button>
            <Button type="button" size="sm" disabled={busy} onClick={() => void onConfirm()}>
              Подтвердить запросы
            </Button>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={busy || !isActive}
              onClick={() => void onRunNow()}
            >
              {busy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : null}
              Запустить поиск сейчас
            </Button>
            {isActive ? (
              <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => void onPause()}>
                Остановить поиск
              </Button>
            ) : null}
            {isPaused ? (
              <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => void onResume()}>
                Возобновить (без немедленного скана)
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}

      {primaryFindings.length > 0 ? (
        <ul className="mt-6 space-y-4">
          {primaryFindings.map((row) => (
            <SavedVideoSimilarFindingCard
              key={row.id}
              row={row}
              showOtherHint={false}
              onSave={(id) => void onSaveFinding(id)}
              onFeedback={(id, v) => void onFeedback(id, v)}
            />
          ))}
        </ul>
      ) : hasAnyFindings && watch?.last_scan_at ? (
        <p className="mt-4 text-sm text-muted-foreground">
          В основном списке нет уверенно близких роликов — см. «Остальные результаты поиска» ниже.
        </p>
      ) : watch?.last_scan_at && !hasAnyFindings ? (
        <p className="mt-4 text-sm text-muted-foreground">В последней проверке новых роликов в списке нет.</p>
      ) : null}

      {otherTotal > 0 ? (
        <div className="mt-6">
          <button
            type="button"
            className="flex w-full items-center gap-2 rounded-md border border-border px-3 py-2 text-left text-sm font-medium hover:bg-muted/50"
            onClick={() => setShowOther((v) => !v)}
            aria-expanded={showOther}
          >
            <ChevronDown className={`h-4 w-4 shrink-0 transition-transform ${showOther ? "rotate-180" : ""}`} />
            Остальные результаты поиска ({otherTotal})
          </button>
          {showOther ? (
            <ul className="mt-3 space-y-4">
              {otherFindings.map((row) => (
                <SavedVideoSimilarFindingCard
                  key={row.id}
                  row={row}
                  showOtherHint
                  onSave={(id) => void onSaveFinding(id)}
                  onFeedback={(id, v) => void onFeedback(id, v)}
                />
              ))}
              {otherTotal > otherFindings.length ? (
                <p className="text-xs text-muted-foreground">
                  Показаны первые {otherFindings.length} из {otherTotal}.
                </p>
              ) : null}
            </ul>
          ) : null}
        </div>
      ) : null}

    </SectionPanel>
  );
}
