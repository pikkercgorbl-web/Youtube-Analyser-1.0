"use client";

import { Search } from "lucide-react";
import type { UploadPeriod } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";

export interface AnomalyFilters {
  q: string;
  period: UploadPeriod;
  durationMin: number;
  durationMax: number;
  minVirality: number;
}

interface AnomalyFiltersPanelProps {
  filters: AnomalyFilters;
  loading?: boolean;
  onChange: (filters: AnomalyFilters) => void;
  onSubmit: () => void;
}

export function AnomalyFiltersPanel({ filters, loading, onChange, onSubmit }: AnomalyFiltersPanelProps) {
  const update = (patch: Partial<AnomalyFilters>) => onChange({ ...filters, ...patch });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Search className="h-4 w-4 text-primary" />
          Фильтры поиска аномалий
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid gap-4 lg:grid-cols-[1fr_auto_auto]">
          <div className="space-y-2">
            <label className="text-sm font-medium text-muted-foreground">Ключевое слово / ниша</label>
            <Input
              placeholder="например: stoicism ai shorts"
              value={filters.q}
              onChange={(e) => update({ q: e.target.value })}
              onKeyDown={(e) => e.key === "Enter" && onSubmit()}
            />
          </div>

          <Select
            label="Период загрузки"
            value={filters.period}
            onChange={(e) => update({ period: e.target.value as UploadPeriod })}
            className="min-w-[160px]"
          >
            <option value="24h">Последние 24 часа</option>
            <option value="week">Последняя неделя</option>
            <option value="month">Последний месяц</option>
          </Select>

          <div className="flex items-end">
            <Button className="w-full lg:w-auto" onClick={onSubmit} disabled={loading || !filters.q.trim()}>
              {loading ? "Поиск..." : "Найти аномалии"}
            </Button>
          </div>
        </div>

        <div className="grid gap-6 md:grid-cols-3">
          <Slider
            label="Мин. длительность"
            value={filters.durationMin}
            min={0}
            max={3600}
            step={15}
            suffix=" сек"
            onChange={(durationMin) => update({ durationMin: Math.min(durationMin, filters.durationMax) })}
          />
          <Slider
            label="Макс. длительность"
            value={filters.durationMax}
            min={0}
            max={7200}
            step={30}
            suffix=" сек"
            onChange={(durationMax) => update({ durationMax: Math.max(durationMax, filters.durationMin) })}
          />
          <Slider
            label="Мин. вирусность"
            value={filters.minVirality}
            min={0}
            max={5000}
            step={100}
            suffix="%"
            onChange={(minVirality) => update({ minVirality })}
          />
        </div>
      </CardContent>
    </Card>
  );
}
