"use client";

import { useEffect, useState } from "react";
import { SlidersHorizontal, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  DEFAULT_SEARCH_FILTERS,
  parseOptionalNumber,
  parseWordsInput,
  type SearchFilters,
  wordsToInputValue,
} from "@/lib/search-filters";
import { cn } from "@/lib/utils";

type FiltersTab = "video" | "channel";

interface FiltersModalProps {
  open: boolean;
  filters: SearchFilters;
  onClose: () => void;
  onApply: (filters: SearchFilters) => void;
}

interface FilterToggleProps {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}

interface RangeFieldProps {
  label: string;
  minValue: string;
  maxValue: string;
  onMinChange: (value: string) => void;
  onMaxChange: (value: string) => void;
  step?: string;
}

function FilterToggle({ label, checked, onChange }: FilterToggleProps) {
  return (
    <label className="flex cursor-pointer items-center justify-between rounded-md border border-border/60 bg-muted/20 px-3 py-2.5">
      <span className="text-sm">{label}</span>
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="h-4 w-4 rounded border-border accent-primary"
      />
    </label>
  );
}

function RangeField({
  label,
  minValue,
  maxValue,
  onMinChange,
  onMaxChange,
  step = "1",
}: RangeFieldProps) {
  return (
    <div className="space-y-2">
      <p className="text-sm font-medium text-muted-foreground">{label}</p>
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">От</label>
          <Input
            type="number"
            min="0"
            step={step}
            value={minValue}
            onChange={(event) => onMinChange(event.target.value)}
            placeholder="—"
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">До</label>
          <Input
            type="number"
            min="0"
            step={step}
            value={maxValue}
            onChange={(event) => onMaxChange(event.target.value)}
            placeholder="—"
          />
        </div>
      </div>
    </div>
  );
}

export function FiltersModal({ open, filters, onClose, onApply }: FiltersModalProps) {
  const [activeTab, setActiveTab] = useState<FiltersTab>("video");
  const [draft, setDraft] = useState<SearchFilters>(filters);
  const [plusWordsText, setPlusWordsText] = useState(wordsToInputValue(filters.plus_words));
  const [minusWordsText, setMinusWordsText] = useState(wordsToInputValue(filters.minus_words));

  useEffect(() => {
    if (!open) {
      return;
    }
    setDraft(filters);
    setPlusWordsText(wordsToInputValue(filters.plus_words));
    setMinusWordsText(wordsToInputValue(filters.minus_words));
    setActiveTab("video");
  }, [open, filters]);

  if (!open) {
    return null;
  }

  function updateDraft(patch: Partial<SearchFilters>) {
    setDraft((current) => ({ ...current, ...patch }));
  }

  function handleApply() {
    onApply({
      ...draft,
      plus_words: parseWordsInput(plusWordsText),
      minus_words: parseWordsInput(minusWordsText),
    });
    onClose();
  }

  function handleReset() {
    setDraft(DEFAULT_SEARCH_FILTERS);
    setPlusWordsText("");
    setMinusWordsText("");
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 p-0 sm:items-center sm:p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="filters-modal-title"
        className="flex max-h-[92vh] w-full flex-col overflow-hidden rounded-t-xl border border-border/60 bg-card shadow-2xl sm:max-h-[90vh] sm:max-w-xl sm:rounded-xl"
      >
        <div className="flex items-center justify-between border-b border-border/60 px-5 py-4">
          <div className="flex items-center gap-2">
            <SlidersHorizontal className="h-4 w-4 text-primary" />
            <h2 id="filters-modal-title" className="text-lg font-semibold">
              Расширенные фильтры
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            aria-label="Закрыть"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex border-b border-border/60 px-5">
          <button
            type="button"
            className={cn(
              "border-b-2 px-4 py-3 text-sm font-medium transition-colors",
              activeTab === "video"
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
            onClick={() => setActiveTab("video")}
          >
            Фильтры видео
          </button>
          <button
            type="button"
            className={cn(
              "border-b-2 px-4 py-3 text-sm font-medium transition-colors",
              activeTab === "channel"
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
            onClick={() => setActiveTab("channel")}
          >
            Фильтры канала
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {activeTab === "video" ? (
            <div className="space-y-5">
              <div className="grid gap-2 sm:grid-cols-2">
                <FilterToggle
                  label="Скрыть Shorts"
                  checked={draft.hide_shorts}
                  onChange={(checked) => updateDraft({ hide_shorts: checked })}
                />
                <FilterToggle
                  label="Скрыть обычные видео"
                  checked={draft.hide_regular}
                  onChange={(checked) => updateDraft({ hide_regular: checked })}
                />
                <FilterToggle
                  label="Скрыть трансляции"
                  checked={draft.hide_streams}
                  onChange={(checked) => updateDraft({ hide_streams: checked })}
                />
                <FilterToggle
                  label="Скрыть видео с иероглифами"
                  checked={draft.hide_hieroglyphs}
                  onChange={(checked) => updateDraft({ hide_hieroglyphs: checked })}
                />
                <FilterToggle
                  label="Только виральность > 1.0"
                  checked={draft.virality_only_above_one}
                  onChange={(checked) => updateDraft({ virality_only_above_one: checked })}
                />
              </div>

              <RangeField
                label="Коэффициент просмотров к подписчикам"
                minValue={draft.virality_min?.toString() ?? ""}
                maxValue={draft.virality_max?.toString() ?? ""}
                onMinChange={(value) => updateDraft({ virality_min: parseOptionalNumber(value) })}
                onMaxChange={(value) => updateDraft({ virality_max: parseOptionalNumber(value) })}
                step="0.01"
              />

              <RangeField
                label="Просмотры видео"
                minValue={draft.views_min?.toString() ?? ""}
                maxValue={draft.views_max?.toString() ?? ""}
                onMinChange={(value) => updateDraft({ views_min: parseOptionalNumber(value) })}
                onMaxChange={(value) => updateDraft({ views_max: parseOptionalNumber(value) })}
              />

              <div className="space-y-2">
                <label className="text-sm font-medium text-muted-foreground">Плюс-слова в названии</label>
                <Textarea
                  value={plusWordsText}
                  onChange={(event) => setPlusWordsText(event.target.value)}
                  placeholder="python, tutorial, course"
                  rows={2}
                />
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium text-muted-foreground">Минус-слова в названии</label>
                <Textarea
                  value={minusWordsText}
                  onChange={(event) => setMinusWordsText(event.target.value)}
                  placeholder="spam, clickbait"
                  rows={2}
                />
              </div>
            </div>
          ) : (
            <div className="space-y-5">
              <div className="grid gap-2 sm:grid-cols-2">
                <FilterToggle
                  label="Скрыть верифицированные каналы"
                  checked={draft.hide_verified}
                  onChange={(checked) => updateDraft({ hide_verified: checked })}
                />
                <FilterToggle
                  label="Скрыть каналы артистов (OAC)"
                  checked={draft.hide_artist}
                  onChange={(checked) => updateDraft({ hide_artist: checked })}
                />
                <FilterToggle
                  label="Скрыть детские каналы"
                  checked={draft.hide_kids}
                  onChange={(checked) => updateDraft({ hide_kids: checked })}
                />
              </div>

              <RangeField
                label="Подписчики канала"
                minValue={draft.subscribers_min?.toString() ?? ""}
                maxValue={draft.subscribers_max?.toString() ?? ""}
                onMinChange={(value) => updateDraft({ subscribers_min: parseOptionalNumber(value) })}
                onMaxChange={(value) => updateDraft({ subscribers_max: parseOptionalNumber(value) })}
              />

              <RangeField
                label="Общее количество просмотров канала"
                minValue={draft.channel_views_min?.toString() ?? ""}
                maxValue={draft.channel_views_max?.toString() ?? ""}
                onMinChange={(value) => updateDraft({ channel_views_min: parseOptionalNumber(value) })}
                onMaxChange={(value) => updateDraft({ channel_views_max: parseOptionalNumber(value) })}
              />

              <RangeField
                label="Всего видео на канале"
                minValue={draft.channel_videos_min?.toString() ?? ""}
                maxValue={draft.channel_videos_max?.toString() ?? ""}
                onMinChange={(value) => updateDraft({ channel_videos_min: parseOptionalNumber(value) })}
                onMaxChange={(value) => updateDraft({ channel_videos_max: parseOptionalNumber(value) })}
              />

              <RangeField
                label="Возраст канала (в днях)"
                minValue={draft.channel_age_min?.toString() ?? ""}
                maxValue={draft.channel_age_max?.toString() ?? ""}
                onMinChange={(value) => updateDraft({ channel_age_min: parseOptionalNumber(value) })}
                onMaxChange={(value) => updateDraft({ channel_age_max: parseOptionalNumber(value) })}
              />
            </div>
          )}
        </div>

        <div className="flex flex-col gap-3 border-t border-border/60 px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
          <Button type="button" variant="outline" className="w-full sm:w-auto" onClick={handleReset}>
            Сбросить
          </Button>
          <div className="flex flex-col-reverse gap-2 sm:flex-row">
            <Button type="button" variant="ghost" className="w-full sm:w-auto" onClick={onClose}>
              Отмена
            </Button>
            <Button type="button" className="w-full sm:w-auto" onClick={handleApply}>
              Применить
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
