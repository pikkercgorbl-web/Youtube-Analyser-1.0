"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";

import {
  canonicalYoutubeUrl,
  formatOptionalSubscribers,
  formatOptionalVph,
} from "@/lib/attention-format";
import type { AttentionChannelMomentum } from "@/lib/attention-types";
import { surfaces } from "@/lib/design-system/layout";
import { cn } from "@/lib/utils";

import { HumanReasonsList } from "./signal-badges";

function ChannelCard({ channel }: { channel: AttentionChannelMomentum }) {
  const [open, setOpen] = useState(false);
  const subs = formatOptionalSubscribers(channel.subscriber_count_latest);
  const recentVph = formatOptionalVph(channel.recent_median_vph);
  const prevVph = formatOptionalVph(channel.previous_median_vph);
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
            недавние видео: {channel.recent_video_count}
            {" · "}
            предыдущие: {channel.previous_video_count}
          </p>
        </div>
        <ChevronDown className={cn("h-4 w-4 shrink-0 text-muted-foreground", open && "rotate-180")} />
      </button>
      <dl className="mt-3 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
        <div>Breakout в окне: {channel.breakout_video_count}</div>
        <div>72h confirmed: {channel.confirmed_72h_count}</div>
        {recentVph ? <div>недавний median VPH: {recentVph}</div> : null}
        {prevVph ? <div>предыдущий median VPH: {prevVph}</div> : null}
        {channel.subscriber_growth_available && channel.subscriber_growth_absolute != null ? (
          <div className="col-span-2">
            рост подписчиков: {channel.subscriber_growth_absolute}
            {channel.subscriber_growth_pct != null ? ` (${channel.subscriber_growth_pct.toFixed(1)}%)` : ""}
          </div>
        ) : null}
      </dl>
      <HumanReasonsList reasons={channel.human_reasons} />
      {open ? (
        <div className="mt-3 space-y-2 border-t border-border/50 pt-3 text-sm" data-testid="channel-expanded">
          <p>
            Недавнее окно: {channel.recent_window_days} д · предыдущее окно: {channel.previous_window_days} д
          </p>
          <p className="text-xs text-muted-foreground">Representative videos</p>
          <ul className="space-y-1 text-sm">
            {channel.representative_video_ids.map((videoId) => (
              <li key={videoId}>
                <a
                  href={canonicalYoutubeUrl(videoId)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary hover:underline"
                >
                  {videoId}
                </a>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </article>
  );
}

export function RisingChannelsSection({ channels }: { channels: AttentionChannelMomentum[] }) {
  if (channels.length === 0) {
    return (
      <div
        className={cn(surfaces.sectionMuted, "space-y-2 p-5")}
        data-testid="channels-insufficient-history"
      >
        <p className="text-sm">
          Radar пока накапливает сравнительную историю каналов. Для Channel Momentum нужен недавний период
          и сопоставимый предыдущий период.
        </p>
        <p className="text-xs text-muted-foreground">Обычно потребуется больше истории наблюдений.</p>
      </div>
    );
  }
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {channels.map((channel) => (
        <ChannelCard key={channel.channel_id} channel={channel} />
      ))}
    </div>
  );
}
