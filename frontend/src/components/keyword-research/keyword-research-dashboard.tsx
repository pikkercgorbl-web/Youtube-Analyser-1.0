"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Bookmark,
  FolderSearch,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  Video,
} from "lucide-react";

import { fetchKeywordResearch, fetchSavedKeywords, saveSavedKeyword } from "@/lib/api";
import type { KeywordResearchItem, KeywordResearchResponse, SavedKeywordItem } from "@/lib/types";
import {
  cn,
  competitionLevelLabel,
  overallLevelLabel,
  parseCommaWords,
} from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";

type QueryTab = "all" | "similar" | "related" | "question";
type SortOption = "score_desc" | "score_asc" | "volume_desc" | "competition_asc" | "competition_desc";

const TAB_ITEMS: { id: QueryTab; label: string }[] = [
  { id: "all", label: "ВСЕ" },
  { id: "similar", label: "ПОХОЖИЕ" },
  { id: "related", label: "СВЯЗАННЫЕ" },
  { id: "question", label: "ВОПРОСНОГО ТИПА" },
];

const SORT_OPTIONS: { value: SortOption; label: string }[] = [
  { value: "score_desc", label: "Оценка ↓" },
  { value: "score_asc", label: "Оценка ↑" },
  { value: "volume_desc", label: "Объём ↓" },
  { value: "competition_asc", label: "Конкуренция ↑" },
  { value: "competition_desc", label: "Конкуренция ↓" },
];

const SURFACE_CARD = "rounded-xl border border-border/60 bg-card/80";
const SURFACE_PANEL = "border-border/60 bg-white/5";

const HISTORY_DATES_KEY = "keyword-research-history-dates";

function readHistoryDates(): Record<string, string> {
  if (typeof window === "undefined") return {};
  try {
    return JSON.parse(localStorage.getItem(HISTORY_DATES_KEY) || "{}") as Record<string, string>;
  } catch {
    return {};
  }
}

function touchHistoryDate(keyword: string) {
  const dates = readHistoryDates();
  dates[keyword.toLowerCase()] = new Date().toISOString();
  localStorage.setItem(HISTORY_DATES_KEY, JSON.stringify(dates));
}

function formatHistoryDate(iso: string | undefined): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(iso));
}

function getItemsForTab(result: KeywordResearchResponse, tab: QueryTab): KeywordResearchItem[] {
  if (tab === "similar") return result.suggestions.similar;
  if (tab === "related") return result.suggestions.related;
  if (tab === "question") return result.suggestions.questions;

  const seen = new Set<string>();
  const merged: KeywordResearchItem[] = [];
  for (const item of [
    ...result.suggestions.similar,
    ...result.suggestions.questions,
    ...result.suggestions.related,
  ]) {
    const key = item.keyword.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    merged.push(item);
  }
  return merged;
}

function filterByWords(
  items: KeywordResearchItem[],
  plusWords: string[],
  minusWords: string[],
): KeywordResearchItem[] {
  return items.filter((item) => {
    const lower = item.keyword.toLowerCase();
    if (minusWords.some((word) => lower.includes(word))) return false;
    if (plusWords.length === 0) return true;
    return plusWords.every((word) => lower.includes(word));
  });
}

function sortItems(items: KeywordResearchItem[], sortBy: SortOption): KeywordResearchItem[] {
  const sorted = [...items];
  switch (sortBy) {
    case "score_asc":
      return sorted.sort((a, b) => a.score - b.score);
    case "volume_desc":
      return sorted.sort((a, b) => b.volume - a.volume);
    case "competition_asc":
      return sorted.sort((a, b) => a.competition - b.competition);
    case "competition_desc":
      return sorted.sort((a, b) => b.competition - a.competition);
    default:
      return sorted.sort((a, b) => b.score - a.score);
  }
}

export function KeywordResearchDashboard() {
  const [history, setHistory] = useState<SavedKeywordItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [activeKeyword, setActiveKeyword] = useState("");
  const [result, setResult] = useState<KeywordResearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newKeywordOpen, setNewKeywordOpen] = useState(false);
  const [newKeywordInput, setNewKeywordInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveNotice, setSaveNotice] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<QueryTab>("all");
  const [sortBy, setSortBy] = useState<SortOption>("score_desc");
  const [multiSelectMode, setMultiSelectMode] = useState(false);
  const [selectedKeywords, setSelectedKeywords] = useState<Set<string>>(new Set());
  const [plusWordsRaw, setPlusWordsRaw] = useState("");
  const [minusWordsRaw, setMinusWordsRaw] = useState("");
  const [historyDates, setHistoryDates] = useState<Record<string, string>>({});

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const items = await fetchSavedKeywords();
      setHistory(items);
    } catch {
      setHistory([]);
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadHistory();
    setHistoryDates(readHistoryDates());
  }, [loadHistory]);

  const runAnalysis = useCallback(async (keyword: string) => {
    const trimmed = keyword.trim();
    if (!trimmed) return;

    setActiveKeyword(trimmed);
    setLoading(true);
    setError(null);
    setResult(null);
    setSelectedKeywords(new Set());
    touchHistoryDate(trimmed);
    setHistoryDates(readHistoryDates());

    try {
      const data = await fetchKeywordResearch(trimmed);
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка анализа");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const handleSave = async () => {
    if (!result) return;
    setSaving(true);
    setSaveNotice(null);
    try {
      await saveSavedKeyword({
        keyword: result.main_query.keyword,
        volume: result.main_query.volume,
        competition: result.main_query.competition,
        score: result.main_query.score,
      });
      setSaveNotice("Сохранено");
      await loadHistory();
    } catch (err) {
      setSaveNotice(err instanceof Error ? err.message : "Ошибка сохранения");
    } finally {
      setSaving(false);
    }
  };

  const plusWords = useMemo(() => parseCommaWords(plusWordsRaw), [plusWordsRaw]);
  const minusWords = useMemo(() => parseCommaWords(minusWordsRaw), [minusWordsRaw]);

  const filteredRelated = useMemo(() => {
    if (!result) return [];
    const tabbed = getItemsForTab(result, activeTab);
    const wordFiltered = filterByWords(tabbed, plusWords, minusWords);
    return sortItems(wordFiltered, sortBy);
  }, [result, activeTab, plusWords, minusWords, sortBy]);

  const toggleSelect = (keyword: string) => {
    setSelectedKeywords((current) => {
      const next = new Set(current);
      if (next.has(keyword)) next.delete(keyword);
      else next.add(keyword);
      return next;
    });
  };

  return (
    <div className="flex h-full min-h-screen w-full flex-1 overflow-hidden text-foreground">
      {/* History sidebar */}
      <aside
        className={cn(
          "flex h-full min-h-screen w-[250px] shrink-0 flex-col border-r",
          SURFACE_PANEL,
        )}
      >
        <div className="border-b border-border/60 p-4">
          <Button
            className="w-full gap-2 bg-primary text-primary-foreground hover:bg-primary/90"
            onClick={() => {
              setNewKeywordInput(activeKeyword);
              setNewKeywordOpen(true);
            }}
          >
            <Plus className="h-4 w-4" />
            Новое ключевое слово
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto p-2">
          <p className="px-2 py-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            История
          </p>
          {historyLoading ? (
            <div className="space-y-2 px-2">
              <Skeleton className="h-12" />
              <Skeleton className="h-12" />
            </div>
          ) : history.length === 0 ? (
            <p className="px-2 text-xs text-muted-foreground">Нет сохранённых ключей</p>
          ) : (
            <ul className="space-y-1">
              {history.map((item) => {
                const active = item.keyword.toLowerCase() === activeKeyword.toLowerCase();
                const dateIso = historyDates[item.keyword.toLowerCase()];
                return (
                  <li key={item.id}>
                    <button
                      type="button"
                      onClick={() => void runAnalysis(item.keyword)}
                      className={cn(
                        "w-full rounded-lg px-3 py-2.5 text-left transition-colors",
                        active
                          ? "border border-primary/40 bg-primary/15 text-foreground"
                          : "text-muted-foreground hover:bg-white/5",
                      )}
                    >
                      <p className="truncate text-sm font-medium text-foreground">{item.keyword}</p>
                      <p className="mt-0.5 text-xs text-muted-foreground">{formatHistoryDate(dateIso)}</p>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </aside>

      {/* Main dashboard */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        {!result && !loading ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-4 text-center">
            <FolderSearch className="h-12 w-12 text-primary/60" />
            <div>
              <p className="text-lg font-medium">Выберите или добавьте ключевое слово</p>
              <p className="mt-1 text-sm text-muted-foreground">
                Используйте историю слева или кнопку «Новое ключевое слово»
              </p>
            </div>
            <Button
              className="bg-primary text-primary-foreground hover:bg-primary/90"
              onClick={() => setNewKeywordOpen(true)}
            >
              <Plus className="mr-2 h-4 w-4" />
              Начать анализ
            </Button>
          </div>
        ) : (
          <>
            {/* Top bar */}
            <header className="border-b border-border/60 p-5">
              <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
                <div className="min-w-0 flex-1 space-y-3">
                  <div className="flex items-start gap-3">
                    <div className="mt-1 flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary">
                      <FolderSearch className="h-5 w-5" />
                    </div>
                    <div className="min-w-0">
                      {loading ? (
                        <Skeleton className="h-8 w-64" />
                      ) : (
                        <h1 className="truncate text-2xl font-bold tracking-tight">
                          {result?.main_query.keyword ?? activeKeyword}
                        </h1>
                      )}
                      {error ? <p className="mt-1 text-sm text-rose-400">{error}</p> : null}
                      {saveNotice ? (
                        <p className="mt-1 text-xs text-emerald-400">{saveNotice}</p>
                      ) : null}
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => void handleSave()}
                      disabled={!result || saving}
                    >
                      {saving ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Bookmark className="h-4 w-4" />
                      )}
                      <span className="ml-2">Сохранить</span>
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => result && void runAnalysis(result.main_query.keyword)}
                      disabled={!result || loading}
                    >
                      <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
                      <span className="ml-2">Обновить данные</span>
                    </Button>
                    <Link
                      href={
                        result ? `/?q=${encodeURIComponent(result.main_query.keyword)}` : "#"
                      }
                      className={cn(
                        "inline-flex h-8 items-center justify-center gap-2 rounded-md border border-border/60 bg-card/80 px-3 text-xs font-medium transition-colors hover:bg-white/5",
                        !result && "pointer-events-none opacity-50",
                      )}
                    >
                      <Video className="h-4 w-4" />
                      Найти видео
                    </Link>
                  </div>
                </div>

                {result ? (
                  <div className="grid w-full shrink-0 gap-3 sm:grid-cols-3 xl:w-auto xl:min-w-[520px]">
                    <MetricWidget
                      title="Поисковой объем"
                      icon={Search}
                      value={String(result.main_query.volume)}
                      subtitle="из 100"
                    />
                    <MetricWidget
                      title="Конкуренция"
                      value={`${result.main_query.competition}/100`}
                      badge={competitionLevelLabel(result.main_query.competition)}
                    />
                    <MetricWidget
                      title="Общая оценка"
                      value={`${result.main_query.score.toFixed(1)}/100`}
                      badge={overallLevelLabel(result.main_query.score)}
                    />
                  </div>
                ) : loading ? (
                  <div className="grid w-full gap-3 sm:grid-cols-3 xl:w-auto xl:min-w-[520px]">
                    <Skeleton className="h-24" />
                    <Skeleton className="h-24" />
                    <Skeleton className="h-24" />
                  </div>
                ) : null}
              </div>
            </header>

            {/* Tabs + toolbar */}
            <div className="border-b border-border/60 px-5">
              <div className="flex gap-6 overflow-x-auto">
                {TAB_ITEMS.map((tab) => (
                  <button
                    key={tab.id}
                    type="button"
                    onClick={() => setActiveTab(tab.id)}
                    className={cn(
                      "shrink-0 border-b-2 py-3 text-xs font-semibold tracking-wide transition-colors",
                      activeTab === tab.id
                        ? "border-primary text-primary"
                        : "border-transparent text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-3 py-3">
                <Button
                  variant="outline"
                  size="sm"
                  className={cn(multiSelectMode && "border-primary/50 text-primary")}
                  onClick={() => {
                    setMultiSelectMode((value) => !value);
                    setSelectedKeywords(new Set());
                  }}
                >
                  Выбрать несколько
                </Button>
                <Select
                  aria-label="Сортировка"
                  value={sortBy}
                  onChange={(event) => setSortBy(event.target.value as SortOption)}
                  className="h-9 w-auto min-w-[160px]"
                >
                  {SORT_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </Select>
                <span className="text-xs text-muted-foreground">
                  Показано: {filteredRelated.length}
                  {multiSelectMode && selectedKeywords.size > 0
                    ? ` · Выбрано: ${selectedKeywords.size}`
                    : ""}
                </span>
              </div>
            </div>

            {/* Work area */}
            <div className="flex min-h-0 flex-1 overflow-hidden">
              {/* Filters */}
              <aside className={cn("w-[300px] shrink-0 overflow-y-auto border-r p-4", SURFACE_PANEL)}>
                <h3 className="mb-4 text-sm font-semibold">Фильтры</h3>
                <div className="space-y-4">
                  <div className="space-y-2">
                    <label className="text-xs font-medium text-muted-foreground">Плюс-слова</label>
                    <Textarea
                      placeholder="tutorial, guide, обзор"
                      value={plusWordsRaw}
                      onChange={(event) => setPlusWordsRaw(event.target.value)}
                      rows={4}
                      className="resize-none"
                    />
                    <p className="text-xs text-muted-foreground/70">Через запятую — все слова должны быть в запросе</p>
                  </div>
                  <div className="space-y-2">
                    <label className="text-xs font-medium text-muted-foreground">Минус-слова</label>
                    <Textarea
                      placeholder="minecraft, free, shorts"
                      value={minusWordsRaw}
                      onChange={(event) => setMinusWordsRaw(event.target.value)}
                      rows={4}
                      className="resize-none"
                    />
                    <p className="text-xs text-muted-foreground/70">Через запятую — скрыть запросы с этими словами</p>
                  </div>
                </div>
              </aside>

              {/* Cards grid */}
              <div className="min-w-0 flex-1 overflow-y-auto p-4">
                {loading ? (
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                    {Array.from({ length: 8 }).map((_, index) => (
                      <Skeleton key={index} className="h-44" />
                    ))}
                  </div>
                ) : filteredRelated.length === 0 ? (
                  <div className="flex h-full min-h-[200px] items-center justify-center text-sm text-muted-foreground">
                    Нет запросов по выбранным фильтрам
                  </div>
                ) : (
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                    {filteredRelated.map((item) => (
                      <RelatedKeywordCard
                        key={item.keyword}
                        item={item}
                        selected={selectedKeywords.has(item.keyword)}
                        multiSelectMode={multiSelectMode}
                        onToggleSelect={() => toggleSelect(item.keyword)}
                        onAnalyze={() => void runAnalysis(item.keyword)}
                      />
                    ))}
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </div>

      {newKeywordOpen ? (
        <NewKeywordModal
          value={newKeywordInput}
          onChange={setNewKeywordInput}
          loading={loading}
          onClose={() => setNewKeywordOpen(false)}
          onSubmit={() => {
            setNewKeywordOpen(false);
            void runAnalysis(newKeywordInput);
          }}
        />
      ) : null}
    </div>
  );
}

function MetricWidget({
  title,
  icon: Icon,
  value,
  subtitle,
  badge,
}: {
  title: string;
  icon?: React.ComponentType<{ className?: string }>;
  value: string;
  subtitle?: string;
  badge?: { label: string; variant: "success" | "warning" | "danger" };
}) {
  return (
    <div className={cn(SURFACE_CARD, "p-4")}>
      <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
        {Icon ? <Icon className="h-3.5 w-3.5 text-primary" /> : null}
        {title}
      </div>
      <div className="mt-2 flex items-end justify-between gap-2">
        <p className="text-2xl font-bold tabular-nums">{value}</p>
        {badge ? <Badge variant={badge.variant}>{badge.label}</Badge> : null}
        {subtitle ? <span className="text-xs text-muted-foreground">{subtitle}</span> : null}
      </div>
    </div>
  );
}

function RelatedKeywordCard({
  item,
  selected,
  multiSelectMode,
  onToggleSelect,
  onAnalyze,
}: {
  item: KeywordResearchItem;
  selected: boolean;
  multiSelectMode: boolean;
  onToggleSelect: () => void;
  onAnalyze: () => void;
}) {
  const competition = competitionLevelLabel(item.competition);
  const overall = overallLevelLabel(item.score);

  return (
    <article
      className={cn(
        "flex flex-col transition-all",
        SURFACE_CARD,
        selected ? "border-primary/60 ring-1 ring-primary/30" : "hover:border-border",
      )}
    >
      <div className="flex items-start justify-between gap-2 border-b border-border/60 px-4 py-3">
        <button
          type="button"
          className="min-w-0 flex-1 text-left text-sm font-semibold leading-snug hover:text-primary"
          onClick={multiSelectMode ? onToggleSelect : onAnalyze}
        >
          {item.keyword}
        </button>
        {multiSelectMode ? (
          <input
            type="checkbox"
            checked={selected}
            onChange={onToggleSelect}
            className="mt-1 h-4 w-4 accent-primary"
          />
        ) : null}
      </div>

      <div className="flex flex-1 flex-col items-center justify-center px-4 py-5">
        <p className="text-xs text-muted-foreground">Поисковой объем</p>
        <p className="mt-1 text-3xl font-black tabular-nums text-primary">{item.volume}</p>
      </div>

      <div className="grid grid-cols-2 gap-px border-t border-border/60 bg-border/40">
        <div className="bg-card/80 px-3 py-3 text-center">
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Конкуренция</p>
          <p className="mt-1 text-sm font-bold tabular-nums">{item.competition}/100</p>
          <Badge variant={competition.variant} className="mt-2">
            {competition.label}
          </Badge>
        </div>
        <div className="bg-card/80 px-3 py-3 text-center">
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Оценка</p>
          <p className="mt-1 text-sm font-bold tabular-nums">{item.score.toFixed(1)}/100</p>
          <Badge variant={overall.variant} className="mt-2">
            {overall.label}
          </Badge>
        </div>
      </div>
    </article>
  );
}

function NewKeywordModal({
  value,
  onChange,
  loading,
  onClose,
  onSubmit,
}: {
  value: string;
  onChange: (value: string) => void;
  loading: boolean;
  onClose: () => void;
  onSubmit: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="w-full max-w-md rounded-xl border border-border/60 bg-card p-5 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <h2 className="text-lg font-semibold">Новое ключевое слово</h2>
        <p className="mt-1 text-sm text-muted-foreground">Введите запрос для SEO-анализа ниши</p>
        <Input
          autoFocus
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => event.key === "Enter" && onSubmit()}
          placeholder="python tutorial, k-pop dance..."
          className="mt-4"
          disabled={loading}
        />
        <div className="mt-4 flex justify-end gap-2">
          <Button
            variant="outline"
            onClick={onClose}
            disabled={loading}
          >
            Отмена
          </Button>
          <Button
            className="bg-primary text-primary-foreground hover:bg-primary/90"
            onClick={onSubmit}
            disabled={loading || !value.trim()}
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Анализировать"}
          </Button>
        </div>
      </div>
    </div>
  );
}
