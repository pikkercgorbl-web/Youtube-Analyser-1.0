"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";

import {
  canonicalYoutubeUrl,
  formatOptionalSubscribers,
  formatOptionalVph,
  humanReasonsForDisplay,
} from "@/lib/attention-format";
import type { AttentionChannelMomentum, AttentionVideoWinner } from "@/lib/attention-types";
import { surfaces } from "@/lib/design-system/layout";
import { cn } from "@/lib/utils";

import { HumanReasonsList } from "./signal-badges";

function videoTitleLookup(
  videoId: string,
  winners: AttentionVideoWinner[] | undefined,
): string {
  const row = winners?.find((item) => item.video_id === videoId);
  return row?.title?.trim() || videoId;
}

function ChannelCard({
  channel,
  winnerLookup,
}: {
  channel: AttentionChannelMomentum;
  winnerLookup?: AttentionVideoWinner[];
}) {
  const [open, setOpen] = useState(false);
  const subs = formatOptionalSubscribers(channel.subscriber_count_latest);
  const recentVph = formatOptionalVph(channel.recent_median_vph);
  const prevVph = formatOptionalVph(channel.previous_median_vph);
  const ratio = channel.recent_median_vph_vs_previous;
  const horizon = channel.momentum_horizon_hours ?? 24;
  const tolerance = channel.momentum_horizon_tolerance_hours ?? 6;
  const threshold = channel.improvement_ratio_threshold ?? 1.5;
  const displayReasons = humanReasonsForDisplay(channel.human_reasons);
  return (
    <article className={cn(surfaces.sectionMuted, "p-4")} data-testid="channel-card">
      <button
        type="button"
        className="flex w-full items-start justify-between text-left"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <div>
          <p className="font-medium">{channel.channel_title}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {subs ? `${subs} подп.` : "подписчики неизвестны"}
            {" · "}
            eligible recent/previous: {channel.recent_eligible_count ?? channel.recent_video_count}/
            {channel.previous_eligible_count ?? channel.previous_video_count}
            {" · "}
            измерения ~{horizon}h (±{tolerance}h): {channel.recent_measurable_count ?? "—"}/
            {channel.previous_measurable_count ?? "—"}
          </p>
        </div>
        <ChevronDown className={cn("h-4 w-4 shrink-0 text-muted-foreground", open && "rotate-180")} />
      </button>
      <dl className="mt-3 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
        <div>
          Подходят для анализа Breakout (недавнее): {channel.breakout_video_count}
        </div>
        <div>Контекст keyword 72h: {channel.confirmed_72h_count}</div>
        <div className="col-span-2">
          Повторяемое улучшение: {channel.recent_improvement_count ?? "—"} recent ≥ {threshold}× median previous
        </div>
        {recentVph ? <div>median VPH recent (~{horizon}h): {recentVph}</div> : null}
        {prevVph ? <div>median VPH previous (~{horizon}h): {prevVph}</div> : null}
        {channel.previous_baseline_zero ? (
          <div className="col-span-2">median previous = 0 — отношение не вычисляется</div>
        ) : ratio != null ? (
          <div className="col-span-2">отношение medians: {ratio.toFixed(2)}×</div>
        ) : null}
        {channel.subscriber_growth_available && channel.subscriber_growth_absolute != null ? (
          <div className="col-span-2">
            контекст подписчиков: +{channel.subscriber_growth_absolute}
            {channel.subscriber_growth_pct != null ? ` (${channel.subscriber_growth_pct.toFixed(1)}%)` : ""}
          </div>
        ) : null}
      </dl>
      <HumanReasonsList reasons={displayReasons} />
      {(channel.incompleteness_notes?.length ?? 0) > 0 ? (
        <p className="mt-2 text-xs text-muted-foreground" data-testid="channel-incompleteness">
          Неполная история: {channel.incompleteness_notes?.join("; ")}
        </p>
      ) : null}
      {open ? (
        <div className="mt-3 space-y-2 border-t border-border/50 pt-3 text-sm" data-testid="channel-expanded">
          <p className="text-xs text-muted-foreground">
            Representative IDs — recent с наибольшим age-aligned VPH среди прошедших порог улучшения (до 5).
          </p>
          <ul className="space-y-1 text-sm">
            {channel.representative_video_ids.map((videoId) => (
              <li key={videoId}>
                <a
                  href={canonicalYoutubeUrl(videoId)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary hover:underline"
                >
                  {videoTitleLookup(videoId, winnerLookup)}
                </a>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </article>
  );
}

export function RisingChannelsSection({
  channels,
  winnerLookup,
}: {
  channels: AttentionChannelMomentum[];
  winnerLookup?: AttentionVideoWinner[];
}) {
  if (channels.length === 0) {
    return (
      <div className={cn(surfaces.sectionMuted, "space-y-2 p-5")} data-testid="channels-empty">
        <p className="text-sm">
          В этом снимке нет каналов с Channel Momentum. Сигнал требует ≥2 previous и ≥2 recent видео с confirmed
          regular, snapshots около {24}h от публикации и минимум два recent, каждый ≥1.5× median previous на том же
          горизонте.
        </p>
        <p className="text-xs text-muted-foreground">
          Пустой блок чаще означает недостаток измерений (формат, snapshots), а не отсутствие роста. Диагностика — в
          offline-отчёте momentum compute.
        </p>
      </div>
    );
  }
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {channels.map((channel) => (
        <ChannelCard key={channel.channel_id} channel={channel} winnerLookup={winnerLookup} />
      ))}
    </div>
  );
}
