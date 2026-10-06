"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Bookmark } from "lucide-react";

import {
  Disclosure,
  ErrorState,
  LoadingState,
  PageHeader,
  PageShell,
  SectionPanel,
  UnavailableState,
} from "@/components/design-system";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  canonicalYoutubeUrl,
  formatOptionalAge,
  formatOptionalSubscribers,
  formatOptionalViews,
  formatOptionalVph,
  groupingSourceLabel,
  humanReasonsForDisplay,
  patternActivity,
} from "@/lib/attention-format";
import type { AttentionPatternDetailResponse, AttentionPatternMemberVideo } from "@/lib/attention-types";
import { getAttentionPatternDetail } from "@/lib/api";
import { surfaces } from "@/lib/design-system/layout";
import { savedTopicAffordance } from "@/lib/saved-topics";
import { cn } from "@/lib/utils";

import { AttentionSignalBadges, HumanReasonsList } from "./signal-badges";
import { YoutubeThumb } from "./youtube-thumb";

type SortKey = "newest" | "vph" | "views";

export function PatternDetailView({ patternKey }: { patternKey: string }) {
  const [state, setState] = useState<"loading" | "error" | "ready">("loading");
  const [message, setMessage] = useState("");
  const [detail, setDetail] = useState<AttentionPatternDetailResponse | null>(null);
  const [channelFilter, setChannelFilter] = useState("all");
  const [breakoutFilter, setBreakoutFilter] = useState<"all" | "in_top" | "rest">("all");
  const [sort, setSort] = useState<SortKey>("newest");
  const [query, setQuery] = useState("");

  const load = useCallback(async () => {
    setState("loading");
    try {
      const data = await getAttentionPatternDetail(patternKey);
      setDetail(data);
      setState("ready");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Паттерн не найден");
      setState("error");
    }
  }, [patternKey]);

  useEffect(() => {
    void load();
  }, [load]);

  const videos = useMemo(() => {
    const items = detail?.videos ?? [];
    const q = query.trim().toLowerCase();
    let next = items.filter((row) => {
      if (channelFilter !== "all" && row.channel_id !== channelFilter) {
        return false;
      }
      if (breakoutFilter === "in_top" && !row.in_winner_snapshot) {
        return false;
      }
      if (breakoutFilter === "rest" && row.in_winner_snapshot) {
        return false;
      }
      if (!q) {
        return true;
      }
      return (
        row.title.toLowerCase().includes(q) ||
        row.channel_title.toLowerCase().includes(q) ||
        row.video_id.toLowerCase().includes(q)
      );
    });
    const missing = (value: number | null | undefined, fallback: number) =>
      value == null || Number.isNaN(value) ? fallback : value;
    next = next.slice().sort((a, b) => {
      if (sort === "vph") {
        return missing(b.vph, -1) - missing(a.vph, -1);
      }
      if (sort === "views") {
        return missing(b.views, -1) - missing(a.views, -1);
      }
      const aTime = a.published_at ? new Date(a.published_at).getTime() : 0;
      const bTime = b.published_at ? new Date(b.published_at).getTime() : 0;
      return bTime - aTime;
    });
    return next;
  }, [detail, channelFilter, breakoutFilter, sort, query]);

  if (state === "loading") {
    return (
      <PageShell>
        <LoadingState title="Загрузка паттерна…" />
      </PageShell>
    );
  }
  if (state === "error") {
    return (
      <PageShell>
        <ErrorState title="Не удалось открыть паттерн" description={message} onRetry={load} />
      </PageShell>
    );
  }
  if (!detail?.pattern || detail.data_source === "unavailable") {
    return (
      <PageShell>
        <UnavailableState title="Attention Engine ещё не рассчитан." />
      </PageShell>
    );
  }

  const pattern = detail.pattern;
  const activity = patternActivity(pattern);
  const save = savedTopicAffordance({ familyKey: pattern.pattern_key, runId: detail.run_id });
  const reasons = humanReasonsForDisplay(pattern.human_reasons);

  return (
    <PageShell>
      <Link href="/opportunities" className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "w-fit")}>
        <ArrowLeft className="h-4 w-4" />
        К возможностям
      </Link>
      <PageHeader title={pattern.label} lead={groupingSourceLabel(pattern.kind)} />

      <div className={cn(surfaces.section, "space-y-3 p-4")}>
        <p className="text-sm font-medium">Почему Radar показал это</p>
        {reasons.length > 0 ? (
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
            {reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">Нет сохранённых human_reasons.</p>
        )}
        <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <div>
            <p className="text-xs text-muted-foreground">Видео</p>
            <p className="text-lg font-semibold">{pattern.video_count}</p>
          </div>
          <div data-testid="pattern-channel-diversity">
            <p className="text-xs text-muted-foreground">Независимых каналов</p>
            <p className="text-lg font-semibold">{pattern.channel_count}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Keywords</p>
            <p className="text-lg font-semibold">{pattern.keyword_count}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Breakout</p>
            <p className="text-sm">
              {pattern.breakout_video_count} видео подходят для анализа Breakout
            </p>
          </div>
        </div>
        <div data-testid="pattern-activity">
          <p className="text-xs text-muted-foreground">Активность по периодам</p>
          <p className="text-sm">48–24ч назад · 24ч назад · Последние 24ч</p>
          <p className="text-lg font-semibold">
            {activity.available ? activity.label : "Недостаточно истории"}
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled
            title={save.hint}
            data-testid="save-pattern"
          >
            <Bookmark className="h-3.5 w-3.5" />
            Сохранить
          </Button>
        </div>
      </div>

      <SectionPanel title="Связанные keywords">
        {detail.related_keywords.length === 0 ? (
          <p className="text-sm text-muted-foreground">Нет связанных TargetKeyword в этом паттерне.</p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            {detail.related_keywords.map((row) => (
              <li
                key={row.keyword_id}
                className="rounded-full border border-border/60 px-3 py-1 text-sm"
              >
                {row.keyword}
              </li>
            ))}
          </ul>
        )}
      </SectionPanel>

      <SectionPanel title="Участвующие каналы">
        <ul className="grid gap-2 sm:grid-cols-2">
          {detail.channels.map((channel) => (
            <li key={channel.channel_id} className="text-sm">
              {channel.channel_title}{" "}
              <span className="text-muted-foreground">({channel.video_count})</span>
            </li>
          ))}
        </ul>
      </SectionPanel>

      <SectionPanel title="Все видео паттерна" description="Полный состав группы, не избранные примеры.">
        <div className="flex flex-col gap-2 lg:flex-row lg:flex-wrap lg:items-center">
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Поиск"
            className="max-w-xs"
          />
          <label className="text-sm text-muted-foreground">
            Канал{" "}
            <select
              className="rounded-md border border-input bg-transparent px-2 py-1 text-foreground"
              value={channelFilter}
              onChange={(event) => setChannelFilter(event.target.value)}
            >
              <option value="all">Все</option>
              {detail.channels.map((channel) => (
                <option key={channel.channel_id} value={channel.channel_id}>
                  {channel.channel_title}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm text-muted-foreground">
            В топе дня{" "}
            <select
              className="rounded-md border border-input bg-transparent px-2 py-1 text-foreground"
              value={breakoutFilter}
              onChange={(event) => setBreakoutFilter(event.target.value as "all" | "in_top" | "rest")}
            >
              <option value="all">Все</option>
              <option value="in_top">В сегодняшнем топе</option>
              <option value="rest">Только остальные участники</option>
            </select>
          </label>
          <label className="text-sm text-muted-foreground">
            Сортировка{" "}
            <select
              className="rounded-md border border-input bg-transparent px-2 py-1 text-foreground"
              value={sort}
              onChange={(event) => setSort(event.target.value as SortKey)}
            >
              <option value="newest">Сначала новые</option>
              <option value="vph">VPH</option>
              <option value="views">Views</option>
            </select>
          </label>
        </div>
        <p className="text-xs text-muted-foreground">
          Показано {videos.length} из {detail.videos.length}
        </p>
        <div className="space-y-2" data-testid="pattern-member-list">
          {videos.map((row) => (
            <MemberRow key={row.video_id} video={row} />
          ))}
        </div>
      </SectionPanel>

      <Disclosure summary="Технические детали">
        <dl className="space-y-1 font-mono text-xs text-muted-foreground">
          <div>pattern_key: {pattern.pattern_key}</div>
          <div>kind: {pattern.kind}</div>
          <div>run_id: {detail.run_id ?? "—"}</div>
          <div>keyword_ids: {pattern.participating_keyword_ids.join(", ") || "—"}</div>
        </dl>
      </Disclosure>
    </PageShell>
  );
}

function MemberRow({ video }: { video: AttentionPatternMemberVideo }) {
  const href = canonicalYoutubeUrl(video.video_id, video.youtube_url);
  return (
    <article className={cn(surfaces.sectionMuted, "flex gap-3 p-3")} data-testid="pattern-member">
      <a href={href} target="_blank" rel="noopener noreferrer" className="shrink-0">
        <YoutubeThumb videoId={video.video_id} title={video.title} className="h-20 w-36 rounded" />
      </a>
      <div className="min-w-0 flex-1">
        <a href={href} target="_blank" rel="noopener noreferrer" className="font-medium hover:text-primary">
          {video.title}
        </a>
        <p className="text-xs text-muted-foreground">{video.channel_title}</p>
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs">
          {formatOptionalViews(video.views) ? <span>{formatOptionalViews(video.views)}</span> : null}
          {formatOptionalVph(video.vph) ? <span>{formatOptionalVph(video.vph)}</span> : null}
          {formatOptionalAge(video.age_hours) ? <span>{formatOptionalAge(video.age_hours)}</span> : null}
          {video.breakout_rank != null ? <span>Breakout #{video.breakout_rank}</span> : null}
          {formatOptionalSubscribers(video.subscribers) ? (
            <span>{formatOptionalSubscribers(video.subscribers)} подп.</span>
          ) : null}
          {video.in_winner_snapshot ? <span>в сегодняшнем топе</span> : null}
        </div>
        <AttentionSignalBadges
          treatAsWinner={video.in_winner_snapshot}
          inWinnerSnapshot={video.in_winner_snapshot}
          reasonCodes={video.reason_codes}
          accelerationState={video.acceleration_state}
          delayedOutcomeState={video.delayed_outcome_state}
        />
        <HumanReasonsList reasons={video.human_reasons} />
      </div>
    </article>
  );
}
