"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ChevronDown, ExternalLink } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import { formatOptionalSubscribers } from "@/lib/attention-format";
import type { AttentionChannelMomentum } from "@/lib/attention-types";
import {
  buildChannelCalculationDetails,
  channelFaceSampleWarning,
  channelMomentumHeadline,
  classifyChannelMomentum,
  formatChannelComparisonLine,
  formatCategoryCountsSummary,
  channelMomentumCategoryCounts,
  formatEvidenceUnavailableMessage,
  pickEvidenceVideos,
  type ChannelMomentumCategory,
} from "@/lib/channel-momentum-presentation";
import { buildChannelSingleAnalysisUrl } from "@/lib/channel-single-analysis-url";
import { surfaces } from "@/lib/design-system/layout";
import { cn } from "@/lib/utils";

import { YoutubeThumb } from "./youtube-thumb";

const CATEGORY_SORT: Record<ChannelMomentumCategory, number> = {
  confirmed_growth: 0,
  strong_outliers: 1,
  insufficient_data: 2,
};

function ChannelAvatar({ title }: { title: string }) {
  const initial = (title.trim()[0] || "?").toUpperCase();
  return (
    <div
      className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-muted text-sm font-semibold text-muted-foreground"
      aria-hidden
    >
      {initial}
    </div>
  );
}

function ChannelCard({ channel }: { channel: AttentionChannelMomentum }) {
  const [calcOpen, setCalcOpen] = useState(false);
  const headline = channelMomentumHeadline(channel);
  const subs = formatOptionalSubscribers(channel.subscriber_count_latest);
  const ratio = channel.recent_median_vph_vs_previous;
  const improving = channel.recent_improvement_count ?? 0;
  const evidencePick = pickEvidenceVideos(channel, 3);
  const evidenceUnavailable = formatEvidenceUnavailableMessage(evidencePick, channel);
  const sampleWarning = channelFaceSampleWarning(channel);
  const calcLines = buildChannelCalculationDetails(channel);
  const youtubeChannelUrl = `https://www.youtube.com/channel/${encodeURIComponent(channel.channel_id)}`;

  return (
    <article
      className={cn(surfaces.section, "overflow-hidden rounded-2xl p-4 sm:p-5")}
      data-testid="channel-card"
      data-channel-category={headline.category}
    >
      <div className="flex gap-3">
        <ChannelAvatar title={channel.channel_title} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <h3 className="truncate text-base font-semibold sm:text-lg">{channel.channel_title}</h3>
              <p className="text-xs text-muted-foreground sm:text-sm">
                {subs ? `${subs} подписчиков` : "Подписчики неизвестны"}
              </p>
            </div>
            <span
              className={cn(
                "shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium",
                headline.category === "confirmed_growth" && "bg-primary/15 text-primary",
                headline.category === "strong_outliers" && "bg-amber-500/15 text-amber-200",
                headline.category === "insufficient_data" && "bg-muted text-muted-foreground",
              )}
            >
              {headline.title}
            </span>
          </div>

          <p className="mt-3 text-sm leading-snug text-foreground">{formatChannelComparisonLine(channel)}</p>
          {headline.hint ? (
            <p className="mt-1 text-xs text-muted-foreground">{headline.hint}</p>
          ) : null}
          {sampleWarning ? (
            <p className="mt-2 text-xs text-amber-200/90" data-testid="channel-sample-warning">
              {sampleWarning}
            </p>
          ) : null}

          <dl className="mt-4 grid grid-cols-2 gap-3">
            <div>
              <dt className="text-xs text-muted-foreground">Темп новых vs прежних</dt>
              <dd className="mt-0.5 text-lg font-semibold tabular-nums text-primary sm:text-xl">
                {ratio != null ? `${ratio.toFixed(2)}×` : "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Сильных новых роликов</dt>
              <dd className="mt-0.5 text-lg font-semibold tabular-nums sm:text-xl">{improving}</dd>
            </div>
          </dl>

          {evidencePick.videos.length > 0 ? (
            <div className="mt-4 space-y-2">
              <p className="text-xs font-medium text-muted-foreground">На чём основан вывод</p>
              <ul className="space-y-2">
                {evidencePick.videos.map((v) => (
                  <li key={v.video_id} className="flex gap-2">
                    <YoutubeThumb
                      videoId={v.video_id}
                      title={v.title}
                      className="h-12 w-20 shrink-0 rounded object-cover"
                    />
                    <div className="min-w-0 flex-1 text-xs sm:text-sm">
                      <a
                        href={v.youtube_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="line-clamp-2 font-medium hover:text-primary"
                      >
                        {v.title}
                      </a>
                      <p className="text-muted-foreground">
                        {v.metricCaption ?? (v.vphLabel ? `VPH: ${v.vphLabel}` : "—")}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ) : evidenceUnavailable ? (
            <p className="mt-4 text-xs text-muted-foreground" data-testid="channel-evidence-unavailable">
              {evidenceUnavailable}
            </p>
          ) : null}

          <div className="mt-4 flex flex-wrap gap-2">
            <a
              href={youtubeChannelUrl}
              target="_blank"
              rel="noopener noreferrer"
              className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
            >
              YouTube <ExternalLink className="ml-1 h-3 w-3" />
            </a>
            <Link
              href={buildChannelSingleAnalysisUrl({ channelId: channel.channel_id })}
              className={cn(buttonVariants({ variant: "default", size: "sm" }))}
            >
              Анализ канала
            </Link>
          </div>

          <div className="mt-4 border-t border-border/60 pt-3">
            <button
              type="button"
              className="flex w-full items-center justify-between text-left text-sm text-muted-foreground hover:text-foreground"
              aria-expanded={calcOpen}
              onClick={() => setCalcOpen((v) => !v)}
              data-testid="channel-calc-toggle"
            >
              Как рассчитано
              <ChevronDown className={cn("h-4 w-4 shrink-0", calcOpen && "rotate-180")} />
            </button>
            {calcOpen ? (
              <ul
                className="mt-2 list-disc space-y-1 pl-4 text-xs leading-relaxed text-muted-foreground"
                data-testid="channel-calc-details"
              >
                {calcLines.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            ) : null}
          </div>
        </div>
      </div>
    </article>
  );
}

export function RisingChannelsSection({
  channels,
}: {
  channels: AttentionChannelMomentum[];
}) {
  const sorted = useMemo(() => {
    return [...channels].sort((a, b) => {
      const ca = classifyChannelMomentum(a);
      const cb = classifyChannelMomentum(b);
      if (CATEGORY_SORT[ca] !== CATEGORY_SORT[cb]) {
        return CATEGORY_SORT[ca] - CATEGORY_SORT[cb];
      }
      const ra = a.recent_median_vph_vs_previous ?? 0;
      const rb = b.recent_median_vph_vs_previous ?? 0;
      return rb - ra;
    });
  }, [channels]);

  const categoryCounts = channelMomentumCategoryCounts(channels);
  const categorySummary = formatCategoryCountsSummary(categoryCounts);
  if (channels.length === 0) {
    return (
      <div
        className={cn(surfaces.sectionMuted, "space-y-2 p-5")}
        data-testid="channels-empty"
      >
        <p className="text-lg font-medium">Сигналов по каналам пока нет</p>
        <p className="text-sm text-muted-foreground">
          Нужны измерения нескольких новых и предыдущих видео на одинаковом возрасте (~24 ч после
          публикации). Это не значит, что каналы не растут — данных в снимке может не хватать.
        </p>
        <a href="/monitoring" className="inline-block text-sm text-primary hover:underline">
          Проверить наблюдение за видео →
        </a>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground" data-testid="channels-category-summary">
        {channels.length} каналов в снимке: {categorySummary}
      </p>
      <div className="grid gap-4 md:grid-cols-2">
        {sorted.map((channel) => (
          <ChannelCard key={channel.channel_id} channel={channel} />
        ))}
      </div>
    </div>
  );
}
