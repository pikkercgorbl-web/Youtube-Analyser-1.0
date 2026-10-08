"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

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
  patternActivity,
  patternDetailHref,
} from "@/lib/attention-format";
import type {
  AttentionPatternFamilyDetailResponse,
  AttentionPatternMemberVideo,
} from "@/lib/attention-types";
import { getAttentionPatternFamilyDetail } from "@/lib/api";
import { surfaces } from "@/lib/design-system/layout";
import { SaveTopicButton } from "@/components/saved-topics/save-topic-button";
import { cn } from "@/lib/utils";

import { AttentionSignalBadges, HumanReasonsList } from "./signal-badges";
import { YoutubeThumb } from "./youtube-thumb";

type SortKey = "newest" | "vph" | "views";

export function PatternFamilyDetailView({ familyKey }: { familyKey: string }) {
  const [state, setState] = useState<"loading" | "error" | "ready">("loading");
  const [message, setMessage] = useState("");
  const [detail, setDetail] =
    useState<AttentionPatternFamilyDetailResponse | null>(null);
  const [channelFilter, setChannelFilter] = useState("all");
  const [breakoutFilter, setBreakoutFilter] = useState<
    "all" | "in_top" | "rest"
  >("all");
  const [sort, setSort] = useState<SortKey>("newest");
  const [query, setQuery] = useState("");

  const load = useCallback(async () => {
    setState("loading");
    try {
      const data = await getAttentionPatternFamilyDetail(familyKey);
      setDetail(data);
      setState("ready");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Семейство не найдено",
      );
      setState("error");
    }
  }, [familyKey]);

  useEffect(() => {
    void load();
  }, [load]);

  const videos = useMemo(() => {
    const items = detail?.videos ?? [];
    const q = query.trim().toLowerCase();
    let next = items.filter((row) => {
      if (channelFilter !== "all" && row.channel_id !== channelFilter)
        return false;
      if (breakoutFilter === "in_top" && !row.in_winner_snapshot) return false;
      if (breakoutFilter === "rest" && row.in_winner_snapshot) return false;
      if (!q) return true;
      return (
        row.title.toLowerCase().includes(q) ||
        row.channel_title.toLowerCase().includes(q) ||
        row.video_id.toLowerCase().includes(q)
      );
    });
    const missing = (value: number | null | undefined, fallback: number) =>
      value == null || Number.isNaN(value) ? fallback : value;
    next = next.slice().sort((a, b) => {
      if (sort === "vph") return missing(b.vph, -1) - missing(a.vph, -1);
      if (sort === "views") return missing(b.views, -1) - missing(a.views, -1);
      const aTime = a.published_at ? new Date(a.published_at).getTime() : 0;
      const bTime = b.published_at ? new Date(b.published_at).getTime() : 0;
      return bTime - aTime;
    });
    return next;
  }, [detail, channelFilter, breakoutFilter, sort, query]);

  if (state === "loading") {
    return (
      <PageShell>
        <LoadingState title="Загрузка семейства паттернов…" />
      </PageShell>
    );
  }
  if (state === "error") {
    return (
      <PageShell>
        <ErrorState
          title="Не удалось открыть семейство"
          description={message}
          onRetry={load}
        />
      </PageShell>
    );
  }
  if (!detail?.family || detail.data_source === "unavailable") {
    return (
      <PageShell>
        <UnavailableState title="Attention Engine ещё не рассчитан." />
      </PageShell>
    );
  }

  const family = detail.family;
  const activity = patternActivity(family);
  return (
    <PageShell>
      <Link
        href="/opportunities"
        className={cn(
          buttonVariants({ variant: "ghost", size: "sm" }),
          "w-fit",
        )}
      >
        <ArrowLeft className="h-4 w-4" />К возможностям
      </Link>
      <PageHeader
        title={family.label}
        lead={groupingSourceLabel(family.family_kind)}
      />

      <div className={cn(surfaces.section, "space-y-3 p-4")}>
        <p className="text-sm font-medium">Почему Radar сгруппировал это</p>
        <p className="text-sm text-muted-foreground">
          {groupingSourceLabel(family.family_kind)}. Сравните конкретные ролики
          ниже: сходство темы или заголовков ещё не доказывает повторяемый
          успех.
        </p>
        <details className="text-sm text-muted-foreground">
          <summary>Технические основания группировки</summary>
          <div className="mt-2">
            <p>{family.grouping_reasons.join(" · ")}</p>
            <p data-testid="family-support">
              {family.support_sources.join(" · ")}
            </p>
            <p data-testid="family-flags">{family.quality_flags.join(" · ")}</p>
          </div>
        </details>
        <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <div>
            <p className="text-xs text-muted-foreground">Уникальные видео</p>
            <p className="text-lg font-semibold">{family.video_count}</p>
          </div>
          <div data-testid="pattern-channel-diversity">
            <p className="text-xs text-muted-foreground">Независимых каналов</p>
            <p className="text-lg font-semibold">{family.channel_count}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Запросы</p>
            <p className="text-lg font-semibold">{family.keyword_count}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Выборка Breakout</p>
            <p className="text-sm">
              {family.breakout_eligible_count} видео подходят для анализа
              Breakout (не топ Winners)
            </p>
          </div>
        </div>
        <div data-testid="pattern-activity">
          <p className="text-xs text-muted-foreground">
            Активность по периодам
          </p>
          <p className="text-lg font-semibold">
            {activity.available ? activity.label : "Недостаточно истории"}
          </p>
        </div>
        <SaveTopicButton familyKey={family.family_key} runId={detail.run_id} />
      </div>

      <SectionPanel title="Исходные паттерны">
        <ul className="space-y-1 text-sm" data-testid="family-member-patterns">
          {family.member_pattern_keys.map((key, index) => (
            <li key={key}>
              <Link
                href={patternDetailHref(key)}
                className="text-primary hover:underline"
              >
                {family.member_labels[index] ?? key}
              </Link>
            </li>
          ))}
        </ul>
      </SectionPanel>

      <SectionPanel title="Связанные запросы">
        {detail.related_keywords.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Связанные запросы не указаны.
          </p>
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
              <span className="text-muted-foreground">
                ({channel.video_count})
              </span>
            </li>
          ))}
        </ul>
      </SectionPanel>

      <SectionPanel title="Все уникальные видео семейства">
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
              onChange={(event) =>
                setBreakoutFilter(
                  event.target.value as "all" | "in_top" | "rest",
                )
              }
            >
              <option value="all">Все</option>
              <option value="in_top">В сегодняшнем топе</option>
              <option value="rest">Только остальные</option>
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
        <div className="space-y-2" data-testid="family-member-list">
          {videos.map((row) => (
            <MemberRow key={row.video_id} video={row} />
          ))}
        </div>
      </SectionPanel>

      <Disclosure summary="Технические детали">
        <dl className="space-y-1 font-mono text-xs text-muted-foreground">
          <div>family_key: {family.family_key}</div>
          <div>family_kind: {family.family_kind}</div>
          <div>run_id: {detail.run_id ?? "—"}</div>
          <div>
            member_pattern_keys: {family.member_pattern_keys.join(", ")}
          </div>
        </dl>
      </Disclosure>
    </PageShell>
  );
}

function MemberRow({ video }: { video: AttentionPatternMemberVideo }) {
  const href = canonicalYoutubeUrl(video.video_id, video.youtube_url);
  return (
    <article
      className={cn(surfaces.sectionMuted, "flex gap-3 p-3")}
      data-testid="pattern-member"
    >
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="shrink-0"
      >
        <YoutubeThumb
          videoId={video.video_id}
          title={video.title}
          className="h-20 w-36 rounded"
        />
      </a>
      <div className="min-w-0 flex-1">
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="font-medium hover:text-primary"
        >
          {video.title}
        </a>
        <p className="text-xs text-muted-foreground">{video.channel_title}</p>
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs">
          {formatOptionalViews(video.views) ? (
            <span>{formatOptionalViews(video.views)}</span>
          ) : null}
          {formatOptionalVph(video.vph) ? (
            <span>{formatOptionalVph(video.vph)}</span>
          ) : null}
          {formatOptionalAge(video.age_hours) ? (
            <span>{formatOptionalAge(video.age_hours)}</span>
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
