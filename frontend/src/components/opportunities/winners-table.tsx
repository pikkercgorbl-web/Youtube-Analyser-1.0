"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
import { useMemo, useState } from "react";

import {
  canonicalYoutubeUrl,
  formatOptionalAge,
  formatOptionalSubscribers,
  formatOptionalViews,
  formatOptionalVph,
} from "@/lib/attention-format";
import type { AttentionVideoWinner } from "@/lib/attention-types";
import { surfaces } from "@/lib/design-system/layout";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import { AttentionSignalBadges } from "./signal-badges";
import { YoutubeThumb } from "./youtube-thumb";

type SortKey = "breakout" | "vph" | "views" | "age";

export function WinnersTable({ videos }: { videos: AttentionVideoWinner[] }) {
  const [query, setQuery] = useState("");
  const [visibleCount, setVisibleCount] = useState(12);
  const [sort, setSort] = useState<SortKey>("breakout");

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = q
      ? videos.filter(
          (row) =>
            row.title.toLowerCase().includes(q) ||
            row.channel_title.toLowerCase().includes(q) ||
            row.video_id.toLowerCase().includes(q),
        )
      : videos.slice();
    const rank = (value: number | null | undefined, missing: number) =>
      value == null || Number.isNaN(value) ? missing : value;
    filtered.sort((a, b) => {
      if (sort === "breakout") {
        return rank(a.breakout_rank, 10_000) - rank(b.breakout_rank, 10_000);
      }
      if (sort === "vph") {
        return rank(b.vph, -1) - rank(a.vph, -1);
      }
      if (sort === "views") {
        return rank(b.views, -1) - rank(a.views, -1);
      }
      return rank(a.age_hours, 10_000) - rank(b.age_hours, 10_000);
    });
    return filtered;
  }, [videos, query, sort]);

  return (
    <div className="space-y-3" data-testid="winners-table">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Поиск по названию или каналу"
          aria-label="Поиск по названию или каналу"
          className="max-w-md"
        />
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          Сортировка
          <select
            className="rounded-md border border-input bg-transparent px-2 py-1 text-foreground"
            value={sort}
            onChange={(event) => setSort(event.target.value as SortKey)}
            aria-label="Сортировка видео"
          >
            <option value="breakout">По рейтингу Radar</option>
            <option value="vph">Просмотры в час</option>
            <option value="views">Просмотры</option>
            <option value="age">Возраст</option>
          </select>
        </label>
      </div>

      <p className="text-sm text-muted-foreground" aria-live="polite">
        Показано {Math.min(visibleCount, rows.length)} из {rows.length}{" "}
        совпадений · VPH — средние просмотры в час с публикации
      </p>
      {rows.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-border p-10 text-center">
          <p className="text-lg font-medium">Видео не найдены</p>
          <p className="mt-2 text-muted-foreground">
            Попробуйте другое название или имя канала.
          </p>
        </div>
      ) : null}
      <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
        {rows.slice(0, visibleCount).map((row) => (
          <article
            key={row.video_id}
            className={cn(
              surfaces.section,
              "radar-video-card overflow-hidden rounded-2xl transition-colors hover:border-primary/40",
            )}
            data-testid="winner-row"
          >
            <a
              href={canonicalYoutubeUrl(row.video_id, row.youtube_url)}
              target="_blank"
              rel="noopener noreferrer"
              className="group block"
            >
              <div className="relative">
                <YoutubeThumb
                  videoId={row.video_id}
                  title={row.title}
                  className="aspect-video w-full bg-muted"
                />
                <span className="absolute bottom-3 right-3 rounded-lg bg-black/80 px-3 py-1 text-sm text-white">
                  {formatOptionalAge(row.age_hours) ?? "Возраст неизвестен"}
                </span>
              </div>
              <h3
                className="px-5 pt-4 text-lg font-semibold leading-snug group-hover:text-primary"
                title={row.title}
              >
                {row.title || "Видео без названия"}
              </h3>
            </a>
            <div className="space-y-4 px-5 pb-5 pt-2">
              <p className="text-sm text-muted-foreground">
                {row.channel_title || "Канал неизвестен"} ·{" "}
                {formatOptionalSubscribers(row.subscribers) ?? "—"} подписчиков
              </p>
              <dl className="grid grid-cols-2 gap-4 border-y border-border/60 py-4">
                <div>
                  <dt className="text-xs text-muted-foreground">Просмотры</dt>
                  <dd className="mt-1 text-xl font-semibold tabular-nums">
                    {formatOptionalViews(row.views) ?? "—"}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">
                    В среднем за час
                  </dt>
                  <dd className="mt-1 text-xl font-semibold tabular-nums text-primary">
                    {formatOptionalVph(row.vph) ?? "—"}
                  </dd>
                </div>
              </dl>
              <p className="text-sm leading-relaxed">
                {row.acceleration_state === "accelerating"
                  ? "Ускорение подтверждено серией измерений."
                  : "Ранний сигнал по отдельному видео. Повторяемость на канале ещё нужно изучить."}
              </p>
              <AttentionSignalBadges
                reasonCodes={row.reason_codes}
                accelerationState={row.acceleration_state}
                delayedOutcomeState={row.delayed_outcome_state}
                channelRelativeStatus={row.channel_relative_signal?.status}
              />
              <details className="text-sm text-muted-foreground">
                <summary>Основание сигнала</summary>
                <div className="mt-2 space-y-2">
                  <p>
                    Место в рейтинге видео:{" "}
                    {row.breakout_rank != null
                      ? `#${row.breakout_rank}`
                      : "не указано"}
                    . Рейтинг не гарантирует успех следующего ролика.
                  </p>
                  <p>
                    Средняя скорость рассчитана с публикации, а не за последний
                    час.
                  </p>
                  {row.human_reasons.length > 0 ? (
                    <ul className="list-disc pl-4">
                      {row.human_reasons.map((reason) => (
                        <li key={reason}>{reason}</li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              </details>
              <Link
                href={`/monitoring/videos/${encodeURIComponent(row.video_id)}`}
                className="mr-4 inline-flex text-sm font-semibold hover:text-primary"
              >
                Динамика видео →
              </Link>
              <a
                href={canonicalYoutubeUrl(row.video_id, row.youtube_url)}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex text-sm font-semibold text-primary hover:underline"
              >
                Смотреть на YouTube ↗
              </a>
            </div>
          </article>
        ))}
      </div>
      {visibleCount < rows.length ? (
        <Button
          variant="outline"
          onClick={() => setVisibleCount((count) => count + 12)}
        >
          Показать ещё {Math.min(12, rows.length - visibleCount)} видео
        </Button>
      ) : null}
    </div>
  );
}
