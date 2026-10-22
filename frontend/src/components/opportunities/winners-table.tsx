"use client";



import Link from "next/link";

import { Button, buttonVariants } from "@/components/ui/button";

import { useEffect, useMemo, useState } from "react";



import {

  canonicalYoutubeUrl,

  formatOptionalAge,

  formatOptionalSubscribers,

  formatOptionalViews,

  formatOptionalVph,

  familyDetailHref,

} from "@/lib/attention-format";

import type { AttentionChannelMomentum, AttentionVideoWinner } from "@/lib/attention-types";
import { OpportunityVideoSignalBadges } from "@/components/opportunities/opportunity-video-signal-badges";

import type { RelatedFamilyRef } from "@/lib/saved-research-types";

import { opportunityWinnerDetailHref } from "@/lib/opportunity-winner-routes";

import { SaveVideoButton } from "@/components/saved-research/save-video-button";

import { SaveFamilyButton } from "@/components/saved-research/save-family-button";

import { surfaces } from "@/lib/design-system/layout";

import { Input } from "@/components/ui/input";

import { cn } from "@/lib/utils";



import { stashWinnerForDetail } from "@/lib/opportunity-winner-cache";

import { YoutubeThumb } from "./youtube-thumb";



type SortKey = "breakout" | "vph" | "views" | "age";



export function WinnersTable({

  videos,

  runId = null,

  relatedFamiliesByVideoId = {},

  channelMomentum = [],

  focusVideoId = null,

  onFocusVideoHandled,

}: {

  videos: AttentionVideoWinner[];

  runId?: string | null;

  relatedFamiliesByVideoId?: Record<string, RelatedFamilyRef[]>;

  channelMomentum?: AttentionChannelMomentum[];

  focusVideoId?: string | null;

  onFocusVideoHandled?: () => void;

}) {

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



  useEffect(() => {

    if (!focusVideoId) {

      return;

    }

    if (query.trim()) {

      setQuery("");

      return;

    }

    const index = rows.findIndex((row) => row.video_id === focusVideoId);

    if (index < 0) {

      return;

    }

    if (index >= visibleCount) {

      setVisibleCount(index + 1);

      return;

    }

    const node = document.getElementById(`winner-${focusVideoId}`);

    if (!node) {

      return;

    }

    if (typeof node.scrollIntoView === "function") {

      node.scrollIntoView({ behavior: "smooth", block: "center" });

    }

    onFocusVideoHandled?.();

  }, [focusVideoId, rows, visibleCount, onFocusVideoHandled, query]);



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

        {rows.slice(0, visibleCount).map((row) => {

          const youtubeHref = canonicalYoutubeUrl(row.video_id, row.youtube_url);

          const displayTitle = row.title || "Видео без названия";

          return (

            <article

              key={row.video_id}

              id={`winner-${row.video_id}`}

              className={cn(

                surfaces.section,

                "radar-video-card overflow-hidden rounded-2xl transition-colors hover:border-primary/40",

                focusVideoId === row.video_id &&

                  "ring-2 ring-primary ring-offset-2 ring-offset-background",

              )}

              data-testid="winner-row"

              data-winner-focused={focusVideoId === row.video_id ? "true" : undefined}

            >

              <a

                href={youtubeHref}

                target="_blank"

                rel="noopener noreferrer"

                className="relative block focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-inset"

                aria-label={`Открыть «${displayTitle}» на YouTube`}

              >

                <YoutubeThumb

                  videoId={row.video_id}

                  title={displayTitle}

                  className="aspect-video w-full bg-muted"

                />

                <span className="absolute bottom-3 right-3 rounded-lg bg-black/80 px-3 py-1 text-sm text-white">

                  {formatOptionalAge(row.age_hours) ?? "Возраст неизвестен"}

                </span>

              </a>

              <div className="space-y-3 px-4 pb-4 pt-3 sm:px-5 sm:pb-5 sm:pt-4">

                <h3 className="text-base font-semibold leading-snug sm:text-lg">

                  <a

                    href={youtubeHref}

                    target="_blank"

                    rel="noopener noreferrer"

                    className="hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"

                    title={row.title}

                  >

                    {displayTitle}

                  </a>

                </h3>

                <p className="text-sm text-muted-foreground">

                  {row.channel_title || "Канал неизвестен"} ·{" "}

                  {formatOptionalSubscribers(row.subscribers) ?? "—"} подписчиков

                  {row.breakout_rank != null ? ` · Radar #${row.breakout_rank}` : null}

                </p>

                <dl className="grid grid-cols-2 gap-3 border-y border-border/60 py-3">

                  <div>

                    <dt className="text-xs text-muted-foreground">Просмотры</dt>

                    <dd className="mt-0.5 text-lg font-semibold tabular-nums sm:text-xl">

                      {formatOptionalViews(row.views) ?? "—"}

                    </dd>

                  </div>

                  <div>

                    <dt className="text-xs text-muted-foreground">В среднем за час</dt>

                    <dd className="mt-0.5 text-lg font-semibold tabular-nums text-primary sm:text-xl">

                      {formatOptionalVph(row.vph) ?? "—"}

                    </dd>

                  </div>

                </dl>

                <OpportunityVideoSignalBadges video={row} channelMomentum={channelMomentum} />

                <div className="flex flex-wrap gap-2">

                  <Link

                    href={opportunityWinnerDetailHref(row.video_id)}

                    className={cn(buttonVariants({ variant: "default", size: "sm" }))}

                    data-testid="winner-detail-link"

                    onClick={() => stashWinnerForDetail(row)}

                  >

                    Детали видео

                  </Link>

                  <Link

                    href={`/monitoring/videos/${encodeURIComponent(row.video_id)}`}

                    className={cn(buttonVariants({ variant: "outline", size: "sm" }))}

                  >

                    Динамика видео

                  </Link>

                  <SaveVideoButton videoId={row.video_id} />

                </div>

                {(relatedFamiliesByVideoId[row.video_id]?.length ?? 0) > 0 ? (

                  <div className="space-y-2 text-sm">

                    <p className="font-medium text-foreground">

                      Подборки, где встречается это видео

                    </p>

                    <ul className="space-y-2">

                      {relatedFamiliesByVideoId[row.video_id]?.map((family) => (

                        <li key={family.family_key} className="flex flex-wrap items-center gap-2">

                          <Link

                            href={familyDetailHref(family.family_key)}

                            className="text-primary hover:underline"

                          >

                            {family.label}

                          </Link>

                          <SaveFamilyButton

                            familyKey={family.family_key}

                            runId={runId}

                            label="Сохранить тему"

                          />

                        </li>

                      ))}

                    </ul>

                  </div>

                ) : (

                  <p className="text-xs text-muted-foreground">

                    Нет связанных family в текущем снимке.

                  </p>

                )}

              </div>

            </article>

          );

        })}

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

