"use client";

import { useMemo, useState } from "react";

import {
  canonicalYoutubeUrl,
  formatOptionalAge,
  formatOptionalSubscribers,
  formatOptionalViews,
  formatOptionalVph,
} from "@/lib/attention-format";
import type { AttentionVideoWinner } from "@/lib/attention-types";
import { pageLayout, surfaces } from "@/lib/design-system/layout";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import { AttentionSignalBadges } from "./signal-badges";
import { YoutubeThumb } from "./youtube-thumb";

type SortKey = "breakout" | "vph" | "views" | "age";

export function WinnersTable({ videos }: { videos: AttentionVideoWinner[] }) {
  const [query, setQuery] = useState("");
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
            <option value="breakout">Breakout rank</option>
            <option value="vph">VPH</option>
            <option value="views">Views</option>
            <option value="age">Возраст</option>
          </select>
        </label>
      </div>

      <div className="hidden md:block overflow-x-auto rounded-xl border border-border/60">
        <table className={cn(pageLayout.tableMinWidth, "w-full text-sm")}>
          <thead className="bg-muted/30 text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">Видео</th>
              <th className="px-3 py-2 font-medium">Канал</th>
              <th className="px-3 py-2 font-medium">Views</th>
              <th className="px-3 py-2 font-medium" title="Средняя с публикации по последнему snapshot">
                VPH (с pub.)
              </th>
              <th className="px-3 py-2 font-medium">Возраст</th>
              <th className="px-3 py-2 font-medium">Подписчики</th>
              <th className="px-3 py-2 font-medium">Breakout</th>
              <th className="px-3 py-2 font-medium">Сигналы</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const href = canonicalYoutubeUrl(row.video_id, row.youtube_url);
              return (
                <tr key={row.video_id} className="border-t border-border/40" data-testid="winner-row">
                  <td className="px-3 py-2">
                    <a href={href} target="_blank" rel="noopener noreferrer" className="flex items-center gap-3">
                      <YoutubeThumb
                        videoId={row.video_id}
                        title={row.title}
                        className="h-12 w-20 shrink-0 rounded"
                      />
                      <span className="line-clamp-2 font-medium hover:text-primary">{row.title}</span>
                    </a>
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">{row.channel_title}</td>
                  <td className="px-3 py-2">{formatOptionalViews(row.views) ?? "—"}</td>
                  <td className="px-3 py-2">{formatOptionalVph(row.vph) ?? "—"}</td>
                  <td className="px-3 py-2">{formatOptionalAge(row.age_hours) ?? "—"}</td>
                  <td className="px-3 py-2">{formatOptionalSubscribers(row.subscribers) ?? "—"}</td>
                  <td className="px-3 py-2">
                    {row.breakout_rank != null ? `#${row.breakout_rank}` : "—"}
                  </td>
                  <td className="px-3 py-2">
                    <AttentionSignalBadges
                      treatAsWinner
                      reasonCodes={row.reason_codes}
                      accelerationState={row.acceleration_state}
                      delayedOutcomeState={row.delayed_outcome_state}
                      channelRelativeStatus={row.channel_relative_signal?.status}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="space-y-2 md:hidden">
        {rows.map((row) => {
          const href = canonicalYoutubeUrl(row.video_id, row.youtube_url);
          return (
            <article key={row.video_id} className={cn(surfaces.sectionMuted, "p-3")} data-testid="winner-row">
              <a href={href} target="_blank" rel="noopener noreferrer" className="flex gap-3">
                <YoutubeThumb videoId={row.video_id} title={row.title} className="h-16 w-28 shrink-0 rounded" />
                <div className="min-w-0">
                  <p className="line-clamp-2 text-sm font-medium">{row.title}</p>
                  <p className="text-xs text-muted-foreground">{row.channel_title}</p>
                </div>
              </a>
              <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
                {formatOptionalVph(row.vph) ? <span>{formatOptionalVph(row.vph)}</span> : null}
                {formatOptionalViews(row.views) ? <span>{formatOptionalViews(row.views)}</span> : null}
                {formatOptionalAge(row.age_hours) ? <span>{formatOptionalAge(row.age_hours)}</span> : null}
                {row.breakout_rank != null ? <span>Breakout #{row.breakout_rank}</span> : null}
                {formatOptionalSubscribers(row.subscribers) ? (
                  <span>{formatOptionalSubscribers(row.subscribers)} подп.</span>
                ) : null}
              </div>
              <div className="mt-2">
                <AttentionSignalBadges
                  treatAsWinner
                  reasonCodes={row.reason_codes}
                  accelerationState={row.acceleration_state}
                  delayedOutcomeState={row.delayed_outcome_state}
                  channelRelativeStatus={row.channel_relative_signal?.status}
                />
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}
