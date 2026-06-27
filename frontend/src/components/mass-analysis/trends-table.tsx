"use client";

import Image from "next/image";

import type { MassAnalysisResponse } from "@/lib/types";
import { cn, formatNumber } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type OutlierVideo = MassAnalysisResponse["videos"][number];

interface TrendsTableProps {
  data: MassAnalysisResponse;
}

export function TrendsTable({ data }: TrendsTableProps) {
  const rows = data.videos;
  const topVideo = rows[0];

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <SummaryCard label="Каналов найдено" value={`${data.channels_found} / ${data.channels_requested}`} />
        <SummaryCard label="Видео проанализировано" value={formatNumber(data.total_videos_analyzed)} />
        <SummaryCard
          label="Не найдено"
          value={String(data.channels_not_found.length)}
          highlight={data.channels_not_found.length > 0 ? "warning" : undefined}
        />
        <SummaryCard
          label="Лучший индекс"
          value={topVideo ? `x${topVideo.outlier_score.toFixed(1)}` : "—"}
          highlight={topVideo && topVideo.outlier_score > 2 ? "success" : undefined}
        />
      </div>

      {data.channels_not_found.length > 0 && (
        <Card className="border-amber-500/30 bg-amber-500/5">
          <CardContent className="p-4 text-sm text-amber-200">
            Не удалось загрузить: {data.channels_not_found.join(", ")}
          </CardContent>
        </Card>
      )}

      <Card className="hidden md:block">
        <CardHeader>
          <CardTitle>Аномально популярные видео</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto p-0">
          <table className="w-full min-w-[980px] text-sm">
            <thead>
              <tr className="border-b border-border/60 text-left text-muted-foreground">
                <th className="px-4 py-3 font-medium">Канал</th>
                <th className="px-4 py-3 font-medium">Видео</th>
                <th className="px-4 py-3 font-medium">Просмотры</th>
                <th className="px-4 py-3 font-medium">Средние на канале</th>
                <th className="px-4 py-3 font-medium">Индекс хайпа</th>
                <th className="px-4 py-3 font-medium">Дата выхода</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <TrendRow key={row.video_url} row={row} />
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <div className="space-y-3 md:hidden">
        <h3 className="text-base font-semibold">Аномально популярные видео</h3>
        {rows.map((row) => (
          <Card key={`${row.video_url}-mobile`}>
            <CardContent className="space-y-3 p-4">
              <div className="flex items-start justify-between gap-2">
                <ChannelLink row={row} />
                <OutlierBadge score={row.outlier_score} />
              </div>
              <a
                href={row.video_url}
                target="_blank"
                rel="noopener noreferrer"
                className="block font-medium leading-snug hover:text-primary"
              >
                {row.video_title}
              </a>
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div className="rounded-md bg-muted/30 px-3 py-2">
                  <p className="text-[10px] uppercase text-muted-foreground">Просмотры</p>
                  <p className="mt-1 font-semibold">{formatNumber(row.views)}</p>
                </div>
                <div className="rounded-md bg-muted/30 px-3 py-2">
                  <p className="text-[10px] uppercase text-muted-foreground">Средние</p>
                  <p className="mt-1 font-semibold">{formatNumber(row.channel_average_views)}</p>
                </div>
                <div className="rounded-md bg-muted/30 px-3 py-2">
                  <p className="text-[10px] uppercase text-muted-foreground">Дата выхода</p>
                  <p className="mt-1 font-semibold">{row.published_at}</p>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

function TrendRow({ row }: { row: OutlierVideo }) {
  return (
    <tr className="border-b border-border/40 hover:bg-muted/20">
      <td className="px-4 py-3">
        <ChannelLink row={row} />
      </td>
      <td className="max-w-[360px] px-4 py-3">
        <a
          href={row.video_url}
          target="_blank"
          rel="noopener noreferrer"
          className="line-clamp-2 font-medium hover:text-primary"
        >
          {row.video_title}
        </a>
      </td>
      <td className="px-4 py-3 font-semibold tabular-nums">{formatNumber(row.views)}</td>
      <td className="px-4 py-3 tabular-nums">{formatNumber(row.channel_average_views)}</td>
      <td className="px-4 py-3">
        <OutlierBadge score={row.outlier_score} />
      </td>
      <td className="px-4 py-3 text-muted-foreground">{row.published_at}</td>
    </tr>
  );
}

function ChannelLink({ row }: { row: OutlierVideo }) {
  return (
    <a
      href={row.channel_url}
      target="_blank"
      rel="noopener noreferrer"
      className="flex min-w-0 items-center gap-2 font-medium hover:text-primary"
    >
      {row.channel_avatar ? (
        <Image
          src={row.channel_avatar}
          alt={row.channel_name}
          width={32}
          height={32}
          unoptimized
          className="h-8 w-8 shrink-0 rounded-full object-cover ring-1 ring-border/60"
        />
      ) : (
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-muted text-xs uppercase text-muted-foreground">
          {row.channel_name.slice(0, 1) || "?"}
        </span>
      )}
      <span className="truncate">{row.channel_name}</span>
    </a>
  );
}

function OutlierBadge({ score }: { score: number }) {
  const isHot = score > 2;
  return (
    <Badge
      variant={isHot ? "success" : "secondary"}
      className={cn(isHot && "bg-rose-500/20 text-rose-200")}
    >
      x{score.toFixed(1)}
      {isHot ? " Взрыв" : ""}
    </Badge>
  );
}

function SummaryCard({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: "warning" | "success";
}) {
  return (
    <Card
      className={cn(
        highlight === "warning" && "border-amber-500/30",
        highlight === "success" && "border-emerald-500/30",
      )}
    >
      <CardContent className="p-4">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="mt-1 text-xl font-bold">{value}</p>
      </CardContent>
    </Card>
  );
}
