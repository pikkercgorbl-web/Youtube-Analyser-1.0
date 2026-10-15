"use client";

import { useEffect, useState } from "react";
import { SlidersHorizontal, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DEFAULT_MANUAL_SEARCH_FILTERS,
  type ManualSearchFilters,
  type ManualSearchPeriod,
  type ManualSearchVideoType,
  validateManualSearchFilters,
} from "@/lib/manual-search-filters";

interface FiltersModalProps {
  open: boolean;
  filters: ManualSearchFilters;
  onClose: () => void;
  onApply: (filters: ManualSearchFilters) => void;
}

function parseOptionalNumber(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return null;
  }
  return parsed;
}

interface RangeFieldProps {
  label: string;
  minValue: string;
  maxValue: string;
  onMinChange: (value: string) => void;
  onMaxChange: (value: string) => void;
  step?: string;
  unit?: string;
}

function RangeField({
  label,
  minValue,
  maxValue,
  onMinChange,
  onMaxChange,
  step = "1",
  unit,
}: RangeFieldProps) {
  return (
    <div className="space-y-2">
      <p className="text-sm font-medium text-muted-foreground">{label}</p>
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">От{unit ? `, ${unit}` : ""}</label>
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
          <label className="text-xs text-muted-foreground">До{unit ? `, ${unit}` : ""}</label>
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

const PERIOD_OPTIONS: { value: ManualSearchPeriod; label: string }[] = [
  { value: "all", label: "Всё время" },
  { value: "week", label: "За неделю" },
  { value: "month", label: "За месяц" },
  { value: "year", label: "За год" },
];

const VIDEO_TYPE_OPTIONS: { value: ManualSearchVideoType; label: string }[] = [
  { value: "all", label: "Все" },
  { value: "regular", label: "Обычные видео" },
  { value: "shorts", label: "Shorts" },
  { value: "streams", label: "Трансляции" },
];

export function FiltersModal({ open, filters, onClose, onApply }: FiltersModalProps) {
  const [draft, setDraft] = useState<ManualSearchFilters>(filters);
  const [validationError, setValidationError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    setDraft(filters);
    setValidationError(null);
  }, [open, filters]);

  if (!open) {
    return null;
  }

  function updateDraft(patch: Partial<ManualSearchFilters>) {
    setDraft((current) => ({ ...current, ...patch }));
    setValidationError(null);
  }

  function handleApply() {
    const error = validateManualSearchFilters(draft);
    if (error) {
      setValidationError(error);
      return;
    }
    onApply(draft);
    onClose();
  }

  function handleReset() {
    setDraft(DEFAULT_MANUAL_SEARCH_FILTERS);
    setValidationError(null);
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
              Фильтры
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

        <div className="flex-1 space-y-6 overflow-y-auto px-5 py-4">
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium text-muted-foreground">Дата публикации</legend>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {PERIOD_OPTIONS.map((option) => (
                <label
                  key={option.value}
                  className="flex cursor-pointer items-center gap-2 rounded-md border border-border/60 bg-muted/20 px-3 py-2.5 text-sm has-[:checked]:border-primary has-[:checked]:bg-primary/10"
                >
                  <input
                    type="radio"
                    name="publishedPeriod"
                    value={option.value}
                    checked={draft.publishedPeriod === option.value}
                    onChange={() => updateDraft({ publishedPeriod: option.value })}
                    className="accent-primary"
                  />
                  {option.label}
                </label>
              ))}
            </div>
          </fieldset>

          <RangeField
            label="Длительность"
            unit="мин"
            minValue={draft.durationMinMinutes?.toString() ?? ""}
            maxValue={draft.durationMaxMinutes?.toString() ?? ""}
            onMinChange={(value) =>
              updateDraft({ durationMinMinutes: parseOptionalNumber(value) })
            }
            onMaxChange={(value) =>
              updateDraft({ durationMaxMinutes: parseOptionalNumber(value) })
            }
          />

          <RangeField
            label="Просмотры"
            minValue={draft.viewsMin?.toString() ?? ""}
            maxValue={draft.viewsMax?.toString() ?? ""}
            onMinChange={(value) => updateDraft({ viewsMin: parseOptionalNumber(value) })}
            onMaxChange={(value) => updateDraft({ viewsMax: parseOptionalNumber(value) })}
          />

          <fieldset className="space-y-2">
            <legend className="text-sm font-medium text-muted-foreground">Тип видео</legend>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {VIDEO_TYPE_OPTIONS.map((option) => (
                <label
                  key={option.value}
                  className="flex cursor-pointer items-center gap-2 rounded-md border border-border/60 bg-muted/20 px-3 py-2.5 text-sm has-[:checked]:border-primary has-[:checked]:bg-primary/10"
                >
                  <input
                    type="radio"
                    name="videoType"
                    value={option.value}
                    checked={draft.videoType === option.value}
                    onChange={() => updateDraft({ videoType: option.value })}
                    className="accent-primary"
                  />
                  {option.label}
                </label>
              ))}
            </div>
          </fieldset>

          {validationError ? (
            <p className="text-sm text-red-500" role="alert">
              {validationError}
            </p>
          ) : null}
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
