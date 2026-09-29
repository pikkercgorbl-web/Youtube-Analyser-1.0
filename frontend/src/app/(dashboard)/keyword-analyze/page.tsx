"use client";

import { useState } from "react";
import { KeyRound, Search, Tag } from "lucide-react";
import { analyzeKeyword } from "@/lib/api";
import type { KeywordAnalyzeResponse } from "@/lib/types";
import { cn, formatNumber, formatPercent, scoreColor } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { StateMessage } from "@/components/ui/state-message";

/** Legacy evergreen opportunity analyzer (route moved from /keywords in 1.21F). */
export default function KeywordAnalyzePage() {
  const [keyword, setKeyword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<KeywordAnalyzeResponse | null>(null);

  const handleAnalyze = async () => {
    if (!keyword.trim()) return;
    setLoading(true);
    setError(null);

    try {
      const data = await analyzeKeyword(keyword.trim());
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка анализа");
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <header>
        <div className="flex items-center gap-2">
          <KeyRound className="h-6 w-6 text-primary" />
          <h1 className="text-2xl font-bold tracking-tight">Анализ ключевых слов</h1>
        </div>
        <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
          Оценка вечнозелёного трафика: объём поиска, конкуренция и opportunity score для туториалов и обзоров.
        </p>
      </header>

      <Card>
        <CardContent className="flex flex-col gap-4 p-4 sm:flex-row">
          <Input
            placeholder="python tutorial, notion обзор, life hack..."
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleAnalyze()}
          />
          <Button onClick={handleAnalyze} disabled={loading || !keyword.trim()} className="gap-2 sm:w-auto">
            <Search className="h-4 w-4" />
            {loading ? "Анализ..." : "Анализировать"}
          </Button>
        </CardContent>
      </Card>

      {loading && <KeywordReportSkeleton />}

      {!loading && error && (
        <StateMessage variant="error" title="Не удалось проанализировать ключевое слово" description={error} />
      )}

      {!loading && result && <KeywordReport data={result} />}

      {!loading && !error && !result && (
        <StateMessage
          title="Введите ключевое слово"
          description="Мы проанализируем топ-20 выдачи YouTube и рассчитаем score возможности."
        />
      )}
    </div>
  );
}

function KeywordReport({ data }: { data: KeywordAnalyzeResponse }) {
  const competitionVariant =
    data.competition.competition_level === "low"
      ? "success"
      : data.competition.competition_level === "high"
        ? "danger"
        : "warning";

  return (
    <div className="space-y-6">
      <Card className="overflow-hidden">
        <CardContent className="grid gap-6 p-6 lg:grid-cols-[auto_1fr]">
          <div className="flex flex-col items-center justify-center rounded-2xl border border-border/60 bg-secondary/30 px-8 py-6">
            <p className="text-xs uppercase tracking-wider text-muted-foreground">Opportunity Score</p>
            <p className={cn("mt-2 text-5xl font-black tabular-nums", scoreColor(data.opportunity_score))}>
              {data.opportunity_score}
            </p>
            <p className="mt-1 text-sm text-muted-foreground">из 100</p>
          </div>
          <div className="space-y-3">
            <h2 className="text-xl font-semibold">«{data.keyword}»</h2>
            <p className="text-sm leading-relaxed text-muted-foreground">{data.recommendation}</p>
            <div className="flex flex-wrap gap-2">
              <Badge variant="secondary">Объём: {Math.round(data.volume.volume_score)}/100</Badge>
              <Badge variant={competitionVariant}>
                Конкуренция: {data.competition.competition_level}
              </Badge>
              <Badge variant="outline">{data.analyzed_videos} видео в SERP</Badge>
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <MetricCard title="Объём поиска">
          <MetricRow label="Сумма просмотров топ-20" value={formatNumber(data.volume.total_views)} />
          <MetricRow label="Средние просмотры" value={formatNumber(Math.round(data.volume.avg_views))} />
          <MetricRow label="Медиана просмотров" value={formatNumber(data.volume.median_views)} />
          <MetricRow label="Упоминание в тегах" value={formatPercent(data.volume.tag_mention_rate * 100, 1)} />
          <MetricRow label="Упоминание в названии" value={formatPercent(data.volume.title_mention_rate * 100, 1)} />
          <MetricRow label="Score объёма" value={`${Math.round(data.volume.volume_score)}/100`} />
        </MetricCard>

        <MetricCard title="Конкуренция">
          <MetricRow label="Средние подписчики" value={formatNumber(data.competition.avg_channel_subscribers)} />
          <MetricRow
            label="Медиана подписчиков"
            value={formatNumber(data.competition.median_channel_subscribers)}
          />
          <MetricRow label="Миллионники в топе" value={String(data.competition.mega_channel_count)} />
          <MetricRow label="Малые каналы (<50K)" value={String(data.competition.small_channel_count)} />
          <MetricRow label="Score конкуренции" value={`${data.competition.competition_score}/100`} />
        </MetricCard>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Формула расчёта</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-muted-foreground">
          <p>
            <span className="font-medium text-foreground">Объём поиска</span> = 55% медиана просмотров
            топ-20 + 25% средние просмотры + 20% релевантность запроса в названиях и тегах.
          </p>
          <p>
            <span className="font-medium text-foreground">Конкуренция</span> = 55% медиана
            подписчиков + 25% доля каналов 1M+ + 20% точные совпадения запроса в названии − 15%
            доля малых каналов.
          </p>
          <p>
            <span className="font-medium text-foreground">Opportunity Score</span> = 60% объём
            поиска + 40% лёгкость входа, где лёгкость входа = 100 − конкуренция.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Tag className="h-4 w-4" />
            Похожие теги
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {data.similar_tags.map((tag) => (
            <Badge key={tag.tag} variant="outline" className="px-3 py-1">
              {tag.tag}
              <span className="ml-2 text-muted-foreground">×{tag.frequency}</span>
            </Badge>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

function MetricCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">{children}</CardContent>
    </Card>
  );
}

function MetricRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}

function KeywordReportSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-40 w-full" />
      <div className="grid gap-4 md:grid-cols-2">
        <Skeleton className="h-48" />
        <Skeleton className="h-48" />
      </div>
      <Skeleton className="h-32" />
    </div>
  );
}
