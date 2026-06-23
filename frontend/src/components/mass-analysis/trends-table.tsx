"use client";

import type { DimensionAggregate, MassAnalysisResponse } from "@/lib/types";
import { formatNumber } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface TrendsTableProps {
  data: MassAnalysisResponse;
}

const dimensionLabels: Record<string, string> = {
  format: "Формат",
  topic: "Тема",
  tag: "Тег",
  title_keyword: "Ключевое слово",
};

export function TrendsTable({ data }: TrendsTableProps) {
  const rows = data.by_title_keyword.length
    ? data.by_title_keyword
    : [...data.by_topic, ...data.by_tag, ...data.by_format];

  const topRows = rows.slice(0, 20);

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
          label="Топ тема"
          value={topRows[0]?.dimension_value ?? "—"}
        />
      </div>

      {data.channels_not_found.length > 0 && (
        <Card className="border-amber-500/30 bg-amber-500/5">
          <CardContent className="p-4 text-sm text-amber-200">
            Не удалось загрузить: {data.channels_not_found.join(", ")}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Трендовые темы конкурентов</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto p-0">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b border-border/60 text-left text-muted-foreground">
                <th className="px-4 py-3 font-medium">#</th>
                <th className="px-4 py-3 font-medium">Тип</th>
                <th className="px-4 py-3 font-medium">Тема / ключевое слово</th>
                <th className="px-4 py-3 font-medium">Видео</th>
                <th className="px-4 py-3 font-medium">Ср. просмотры</th>
                <th className="px-4 py-3 font-medium">Ср. VPH</th>
                <th className="px-4 py-3 font-medium">Всего просмотров</th>
              </tr>
            </thead>
            <tbody>
              {topRows.map((row, index) => (
                <TrendRow key={`${row.dimension_type}-${row.dimension_value}`} row={row} rank={index + 1} />
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Каналы по эффективности (VPH)</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto p-0">
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="border-b border-border/60 text-left text-muted-foreground">
                <th className="px-4 py-3 font-medium">Канал</th>
                <th className="px-4 py-3 font-medium">Видео</th>
                <th className="px-4 py-3 font-medium">Просмотры</th>
                <th className="px-4 py-3 font-medium">Ср. VPH</th>
              </tr>
            </thead>
            <tbody>
              {data.channels.map((channel) => (
                <tr key={channel.channel_id} className="border-b border-border/40 hover:bg-muted/20">
                  <td className="px-4 py-3 font-medium">{channel.channel_title}</td>
                  <td className="px-4 py-3">{channel.videos_analyzed}</td>
                  <td className="px-4 py-3">{formatNumber(channel.total_views)}</td>
                  <td className="px-4 py-3 text-emerald-400">{formatNumber(Math.round(channel.avg_vph))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}

function TrendRow({ row, rank }: { row: DimensionAggregate; rank: number }) {
  return (
    <tr className="border-b border-border/40 hover:bg-muted/20">
      <td className="px-4 py-3 text-muted-foreground">{rank}</td>
      <td className="px-4 py-3">
        <Badge variant="secondary">{dimensionLabels[row.dimension_type] ?? row.dimension_type}</Badge>
      </td>
      <td className="px-4 py-3 font-medium">{row.dimension_value}</td>
      <td className="px-4 py-3">{row.video_count}</td>
      <td className="px-4 py-3">{formatNumber(Math.round(row.avg_views))}</td>
      <td className="px-4 py-3 text-emerald-400">{formatNumber(Math.round(row.avg_vph))}</td>
      <td className="px-4 py-3">{formatNumber(row.total_views)}</td>
    </tr>
  );
}

function SummaryCard({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: "warning";
}) {
  return (
    <Card className={highlight === "warning" ? "border-amber-500/30" : undefined}>
      <CardContent className="p-4">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="mt-1 text-xl font-bold">{value}</p>
      </CardContent>
    </Card>
  );
}
