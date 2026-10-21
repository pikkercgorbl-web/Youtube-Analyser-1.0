"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";

import { SectionPanel } from "@/components/design-system";
import { SavedFamilyTopicFindingCard } from "@/components/saved-research/saved-family-topic-finding-card";
import { Button } from "@/components/ui/button";
import {
  confirmSavedFamilyTopicWatch,
  getSavedFamilyTopicFindings,
  getSavedFamilyTopicWatch,
  pauseSavedFamilyTopicWatch,
  resumeSavedFamilyTopicWatch,
  runSavedFamilyTopicWatchNow,
  saveFamilyTopicFinding,
} from "@/lib/api";
import type {
  SavedFamilyTopicFinding,
  SavedFamilyTopicQuerySuggestionItem,
  SavedFamilyTopicWatch,
} from "@/lib/saved-research-types";

const DISPLAY_LABELS: Record<string, string> = {
  not_configured: "Поиск видео по теме ещё не настраивали",
  draft: "Подтвердите запросы и запустите поиск",
  paused: "Поиск остановлен",
  scanning: "Идёт поиск…",
  never_checked: "Запросы подтверждены — нажмите «Запустить поиск сейчас»",
  empty: "Проверили по утверждённым запросам — совпадений в выдаче нет",
  has_results: "Есть совпадения в выдаче YouTube (не оценка «принадлежности теме»)",
  partial_error: "Часть запросов завершилась с ошибкой; остальные результаты ниже",
};

type QueryRow = { query: string; explanation: string | null };

type Props = {
  savedFamilyId: number;
  archived: boolean;
};

function rowsFromWatch(w: SavedFamilyTopicWatch, editingConfirmed: boolean): QueryRow[] {
  if (editingConfirmed && w.confirmed_queries.length > 0) {
    return w.confirmed_queries.map((query) => ({ query, explanation: null }));
  }
  if (w.suggested_query_items.length > 0) {
    return w.suggested_query_items.map((item) => ({
      query: item.query,
      explanation: item.source_explanation,
    }));
  }
  const fallback = w.confirmed_queries.length > 0 ? w.confirmed_queries : w.suggested_queries;
  return fallback.map((query) => ({ query, explanation: null }));
}

export function SavedFamilyTopicWatchPanel({ savedFamilyId, archived }: Props) {
  const [watch, setWatch] = useState<SavedFamilyTopicWatch | null>(null);
  const [queryRows, setQueryRows] = useState<QueryRow[]>([]);
  const [findings, setFindings] = useState<SavedFamilyTopicFinding[]>([]);
  const [findingsTotal, setFindingsTotal] = useState(0);
  const [hitsByQuery, setHitsByQuery] = useState<Record<string, number>>({});
  const [confirmedQueries, setConfirmedQueries] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showSetup, setShowSetup] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const w = await getSavedFamilyTopicWatch(savedFamilyId);
      setWatch(w);
      const rows = rowsFromWatch(w, false);
      setQueryRows((prev) => (showSetup && prev.some((r) => r.query.trim()) ? prev : rows.length ? rows : [{ query: "", explanation: null }]));
      const f = await getSavedFamilyTopicFindings(savedFamilyId, { limit: 50 });
      setFindings(f.items);
      setFindingsTotal(f.total);
      setHitsByQuery(f.hits_by_query ?? {});
      setConfirmedQueries(f.confirmed_queries ?? w.confirmed_queries);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  }, [savedFamilyId, showSetup]);

  useEffect(() => {
    void load();
  }, [load]);

  const applyDirection = (items: SavedFamilyTopicQuerySuggestionItem[]) => {
    if (!items.length) return;
    setQueryRows(
      items.map((item) => ({ query: item.query, explanation: item.source_explanation })),
    );
    setShowSetup(true);
  };

  const updateQuery = (index: number, value: string) => {
    setQueryRows((prev) => prev.map((row, i) => (i === index ? { ...row, query: value } : row)));
  };

  const addQuery = () => {
    if (queryRows.length >= 5) return;
    setQueryRows((prev) => [...prev, { query: "", explanation: null }]);
  };

  const removeQuery = (index: number) => {
    setQueryRows((prev) => prev.filter((_, i) => i !== index));
  };

  const onConfirm = async () => {
    setBusy(true);
    setError(null);
    try {
      const cleaned = queryRows.map((r) => r.query.trim()).filter(Boolean);
      if (cleaned.length < 1) {
        setError("Нужен хотя бы один запрос");
        return;
      }
      const w = await confirmSavedFamilyTopicWatch(savedFamilyId, cleaned);
      setWatch(w);
      setShowSetup(false);
      setConfirmedQueries(w.confirmed_queries);
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
      await runSavedFamilyTopicWatchNow(savedFamilyId);
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
      const w = await pauseSavedFamilyTopicWatch(savedFamilyId);
      setWatch(w);
    } finally {
      setBusy(false);
    }
  };

  const onResume = async () => {
    setBusy(true);
    try {
      const w = await resumeSavedFamilyTopicWatch(savedFamilyId);
      setWatch(w);
    } finally {
      setBusy(false);
    }
  };

  const onSaveFinding = async (findingId: number) => {
    try {
      await saveFamilyTopicFinding(savedFamilyId, findingId);
      setFindings((prev) =>
        prev.map((f) => (f.id === findingId ? { ...f, saved_to_research: true } : f)),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка сохранения");
    }
  };

  const hitsSummary = useMemo(() => {
    const entries = Object.entries(hitsByQuery);
    if (!entries.length) return null;
    return entries
      .sort((a, b) => b[1] - a[1])
      .map(([q, n]) => `«${q}»: ${n}`)
      .join(" · ");
  }, [hitsByQuery]);

  if (loading) {
    return (
      <SectionPanel title="Новые видео по теме">
        <p className="text-sm text-muted-foreground">Загрузка…</p>
      </SectionPanel>
    );
  }

  const displayState = watch?.display_state ?? "not_configured";
  const statusLabel = DISPLAY_LABELS[displayState] ?? displayState;
  const isActive = watch?.status === "active";
  const isPaused = watch?.status === "paused";
  const loadEstimate = watch?.load_estimate ?? {};
  const maxQueries = Number(loadEstimate.max_queries_per_watch ?? 5);
  const maxSearchesPerCycle = Number(loadEstimate.max_query_searches_per_discovery_cycle ?? 9);
  const maxPagesPerQuery = Number(loadEstimate.max_pages_per_query ?? 2);

  const setupVisible =
    showSetup || watch?.status === "draft" || !watch?.confirmed_queries.length;
  const manualOnly =
    watch?.suggestion_mode === "heterogeneous" &&
    (watch.suggested_query_items.length === 0 || watch.suggestion_message);

  return (
    <SectionPanel
      title="Новые видео по теме"
      description="Отдельный поиск YouTube по вашим формулировкам. Не путать с «Наблюдениями Attention» ниже."
    >
      {archived ? (
        <p className="text-sm text-amber-200">В архиве — поиск приостановлен. После восстановления включите вручную.</p>
      ) : null}
      {error ? <p className="text-sm text-destructive">{error}</p> : null}
      <p className="text-sm font-medium">{statusLabel}</p>
      {watch?.last_scan_at ? (
        <p className="text-xs text-muted-foreground">
          Последняя проверка: {new Date(watch.last_scan_at).toLocaleString()}
          {watch.last_error ? ` · ${watch.last_error}` : ""}
        </p>
      ) : null}
      {findingsTotal > 0 ? (
        <p className="text-xs text-muted-foreground">
          {findingsTotal} совпадений в выдаче по {confirmedQueries.length || "?"} утверждённым запросам
          {hitsSummary ? ` (${hitsSummary})` : ""}. Это не «{findingsTotal} видео по теме» и не доказательство
          принадлежности PatternFamily.
        </p>
      ) : watch?.last_scan_at ? (
        <p className="text-xs text-muted-foreground">
          Слабая или пустая выборка по текущим запросам — попробуйте сузить формулировки.
        </p>
      ) : null}
      <p className="text-xs text-muted-foreground">
        Лимиты (общие с поиском похожих для видео): до {maxQueries} запросов на тему, до {maxSearchesPerCycle}{" "}
        поисковых запросов и {maxSearchesPerCycle * maxPagesPerQuery} страниц InnerTube за цикл discovery (
        {maxPagesPerQuery} стр./запрос).
      </p>

      {!archived && !setupVisible ? (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => {
              setShowSetup(true);
              if (watch?.suggested_query_items.length) {
                setQueryRows(
                  watch.suggested_query_items.map((item) => ({
                    query: item.query,
                    explanation: item.source_explanation,
                  })),
                );
              }
            }}
          >
            Искать видео по теме
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
              Остановить
            </Button>
          ) : null}
          {isPaused ? (
            <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => void onResume()}>
              Возобновить (без немедленного скана)
            </Button>
          ) : null}
        </div>
      ) : null}

      {!archived && setupVisible ? (
        <div className="mt-4 space-y-3">
          {watch?.suggestion_message ? (
            <p className="text-sm text-amber-200/90">{watch.suggestion_message}</p>
          ) : null}
          {watch?.mixed_keyword_provenance ? (
            <p className="text-xs text-muted-foreground">
              Attention связал с темой несколько групп ключевых слов — не смешивайте разные направления в одном
              наборе запросов.
            </p>
          ) : null}
          {watch?.search_directions && watch.search_directions.length > 1 ? (
            <div className="space-y-2 rounded-md border border-border p-3">
              <p className="text-xs font-medium">Выберите одно направление</p>
              {watch.search_directions.map((dir) => (
                <div key={dir.direction_id} className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-medium">{dir.label}</span>
                  <span className="text-xs text-muted-foreground">{dir.explanation}</span>
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    disabled={!dir.suggestions.length}
                    onClick={() => applyDirection(dir.suggestions)}
                  >
                    Подставить запросы
                  </Button>
                </div>
              ))}
            </div>
          ) : null}
          {manualOnly && queryRows.length === 1 && !queryRows[0].query ? (
            <p className="text-sm text-muted-foreground">Задайте 1–5 запросов вручную.</p>
          ) : (
            <p className="text-xs text-muted-foreground">
              Предложения из названия темы и согласованных ключевых слов (можно удалить шумные строки).
            </p>
          )}
          {queryRows.map((row, i) => (
            <div key={i} className="space-y-1">
              <div className="flex gap-2">
                <input
                  className="flex-1 rounded-md border border-border bg-background px-2 py-1 text-sm"
                  value={row.query}
                  onChange={(e) => updateQuery(i, e.target.value)}
                  disabled={busy}
                  aria-label={`Запрос ${i + 1}`}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  onClick={() => removeQuery(i)}
                >
                  Удалить
                </Button>
              </div>
              {row.explanation ? (
                <p className="text-xs text-muted-foreground">{row.explanation}</p>
              ) : null}
            </div>
          ))}
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" size="sm" disabled={queryRows.length >= 5 || busy} onClick={addQuery}>
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
              Запустить поиск сейчас
            </Button>
            {isActive ? (
              <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => void onPause()}>
                Остановить
              </Button>
            ) : null}
            {isPaused ? (
              <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => void onResume()}>
                Возобновить
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}

      {findings.length > 0 ? (
        <ul className="mt-6 space-y-4">
          {findings.map((row) => (
            <SavedFamilyTopicFindingCard key={row.id} row={row} onSave={(id) => void onSaveFinding(id)} />
          ))}
        </ul>
      ) : watch?.last_scan_at ? (
        <p className="mt-4 text-sm text-muted-foreground">В последней проверке совпадений в списке нет.</p>
      ) : null}
      {findingsTotal > findings.length ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Показаны первые {findings.length} из {findingsTotal} совпадений в выдаче.
        </p>
      ) : null}
    </SectionPanel>
  );
}
