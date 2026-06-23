"use client";

import Image from "next/image";

import type { ExplosiveChannelItem } from "@/lib/types";
import {
  formatChannelAgeLabel,
  youtubeChannelUrl,
  youtubeVideoUrl,
} from "@/lib/explosive-channels";
import { cn, formatCompactNumber } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";

interface ExplosiveChannelCardProps {
  channel: ExplosiveChannelItem;
}

const externalLinkClassName =
  "cursor-pointer transition-colors hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40";

export function ExplosiveChannelCard({ channel }: ExplosiveChannelCardProps) {
  const channelHref = channel.channel_id
    ? youtubeChannelUrl(channel.channel_id)
    : null;
  const videoHref = channel.video_id ? youtubeVideoUrl(channel.video_id) : null;
  const thumbnail = channel.representative_video_thumbnail.trim();
  const avatar = channel.avatar_url.trim();

  return (
    <Card className="overflow-hidden border-border/60 bg-card/80 transition-shadow hover:shadow-lg hover:shadow-primary/5">
      <div className="flex items-start justify-between gap-3 border-b border-border/60 p-4">
        {channelHref ? (
          <a
            href={channelHref}
            target="_blank"
            rel="noopener noreferrer"
            className={cn("flex min-w-0 items-center gap-3", externalLinkClassName)}
          >
            <div className="relative h-11 w-11 shrink-0 overflow-hidden rounded-full bg-muted">
              {avatar ? (
                <Image
                  src={avatar}
                  alt={channel.channel_name}
                  fill
                  unoptimized
                  className="object-cover"
                  sizes="44px"
                />
              ) : (
                <span className="flex h-full w-full items-center justify-center text-sm font-semibold text-primary">
                  {channel.channel_name.charAt(0).toUpperCase() || "?"}
                </span>
              )}
            </div>
            <p className="line-clamp-2 text-sm font-semibold leading-snug">
              {channel.channel_name}
            </p>
          </a>
        ) : (
          <div className="flex min-w-0 items-center gap-3">
            <div className="relative h-11 w-11 shrink-0 overflow-hidden rounded-full bg-muted">
              {avatar ? (
                <Image
                  src={avatar}
                  alt={channel.channel_name}
                  fill
                  unoptimized
                  className="object-cover"
                  sizes="44px"
                />
              ) : (
                <span className="flex h-full w-full items-center justify-center text-sm font-semibold text-primary">
                  {channel.channel_name.charAt(0).toUpperCase() || "?"}
                </span>
              )}
            </div>
            <p className="line-clamp-2 text-sm font-semibold leading-snug">
              {channel.channel_name}
            </p>
          </div>
        )}

        <Badge variant="secondary" className="shrink-0 whitespace-nowrap">
          {formatChannelAgeLabel(channel.channel_age_days)}
        </Badge>
      </div>

      <div className="p-4 pt-3">
        {videoHref ? (
          <a
            href={videoHref}
            target="_blank"
            rel="noopener noreferrer"
            className={cn("block", externalLinkClassName)}
          >
            <div className="relative aspect-video overflow-hidden rounded-lg bg-muted">
              {thumbnail ? (
                <Image
                  src={thumbnail}
                  alt={channel.representative_video_title}
                  fill
                  unoptimized
                  className="object-cover"
                  sizes="(max-width: 768px) 100vw, (max-width: 1200px) 50vw, 33vw"
                />
              ) : (
                <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
                  Нет превью
                </div>
              )}
            </div>

            <p className="mt-3 line-clamp-2 text-sm font-medium leading-snug text-foreground">
              {channel.representative_video_title || "Без названия"}
            </p>
          </a>
        ) : (
          <>
            <div className="relative aspect-video overflow-hidden rounded-lg bg-muted">
              {thumbnail ? (
                <Image
                  src={thumbnail}
                  alt={channel.representative_video_title}
                  fill
                  unoptimized
                  className="object-cover"
                  sizes="(max-width: 768px) 100vw, (max-width: 1200px) 50vw, 33vw"
                />
              ) : (
                <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
                  Нет превью
                </div>
              )}
            </div>

            <p className="mt-3 line-clamp-2 text-sm font-medium leading-snug text-foreground">
              {channel.representative_video_title || "Без названия"}
            </p>
          </>
        )}
      </div>

      <div className="grid grid-cols-3 gap-2 border-t border-border/60 bg-muted/20 p-4">
        <Stat label="Подписчики" value={formatCompactNumber(channel.subscribers)} />
        <Stat label="Просмотры" value={formatCompactNumber(channel.representative_video_views)} />
        <Stat
          label="Виральность"
          value={`${channel.viral_coefficient.toFixed(1)}×`}
          accent
        />
      </div>
    </Card>
  );
}

function Stat({
  label,
  value,
  accent = false,
}: {
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <div className="text-center">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p
        className={cn(
          "mt-1 font-bold tabular-nums",
          accent ? "text-lg text-primary" : "text-sm",
        )}
      >
        {value}
      </p>
    </div>
  );
}
