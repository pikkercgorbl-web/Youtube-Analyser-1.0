"use client";

import { useCallback, useEffect, useState } from "react";
import { TrendingUp, Trophy } from "lucide-react";
import { fetchYouTubeLeaders } from "@/lib/api";
import type { YouTubeLeadersResponse } from "@/lib/types";
import { formatNumber } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { StateMessage } from "@/components/ui/state-message";

export default function LeadersPage() {
  const [windowDays, setWindowDays] = useState(7);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<YouTubeLeadersResponse | null>(null);

  const loadLeaders = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const data = await fetchYouTubeLeaders(windowDays, 10);
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка загрузки");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }, [windowDays]);

  useEffect(() => {
    loadLeaders();
  }, [loadLeaders]);

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <TrendingUp className="h-6 w-6 text-primary" />
            <h1 className="text-2xl font-bold tracking-tight">Лидеры YouTube</h1>
          </div>
          <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
            Топ-10 самых быстрорастущих каналов из базы — микро-тренды за последние 3–7 дней.
          </p>
        </div>

        <Select
          label="Окно роста"
          value={String(windowDays)}
          onChange={(e) => setWindowDays(Number(e.target.value))}
          className="w-full sm:w-48"
        >
          <option value="3">3 дня</option>
          <option value="5">5 дней</option>
          <option value="7">7 дней</option>
        </Select>
      </header>

      {loading && <LeadersTableSkeleton />}

      {!loading && error && (
        <StateMessage variant="error" title="Не удалось загрузить лидеров" description={error} />
      )}

      {!loading && result && (
        <div className="space-y-4">
          {result.channels_without_baseline > 0 && (
            <p className="text-sm text-muted-foreground">
              Пропущено каналов без истории: {result.channels_without_baseline}
            </p>
          )}

          {result.leaders.length === 0 ? (
            <StateMessage
              title="Нет данных о росте"
              description="Добавьте каналы в базу и дождитесь снимков метрик для расчёта трендов."
            />
          ) : (
            <>
              <Card className="hidden md:block">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-base">
                    <Trophy className="h-4 w-4 text-amber-400" />
                    Топ быстрорастущих каналов
                  </CardTitle>
                </CardHeader>
                <CardContent className="overflow-x-auto p-0">
                  <table className="w-full min-w-[800px] text-sm">
                    <thead>
                      <tr className="border-b border-border/60 text-left text-muted-foreground">
                        <th className="px-4 py-3 font-medium">#</th>
                        <th className="px-4 py-3 font-medium">Канал</th>
                        <th className="px-4 py-3 font-medium">Ниша</th>
                        <th className="px-4 py-3 font-medium">Подписчики</th>
                        <th className="px-4 py-3 font-medium">Рост подписчиков</th>
                        <th className="px-4 py-3 font-medium">Рост просмотров</th>
                        <th className="px-4 py-3 font-medium">Score</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.leaders.map((leader, index) => (
                        <tr key={leader.channel_id} className="border-b border-border/40 hover:bg-muted/20">
                          <td className="px-4 py-3">
                            {index < 3 ? (
                              <Badge variant={index === 0 ? "warning" : "secondary"}>{index + 1}</Badge>
                            ) : (
                              index + 1
                            )}
                          </td>
                          <td className="px-4 py-3 font-medium">{leader.channel_title}</td>
                          <td className="px-4 py-3 text-muted-foreground">{leader.topic ?? "—"}</td>
                          <td className="px-4 py-3">{formatNumber(leader.current_subscribers)}</td>
                          <td className="px-4 py-3 text-emerald-400">+{leader.subscribers_growth_pct}%</td>
                          <td className="px-4 py-3 text-emerald-400">+{leader.views_growth_pct}%</td>
                          <td className="px-4 py-3 font-bold text-primary">{leader.growth_score}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </CardContent>
              </Card>

              <div className="space-y-3 md:hidden">
                {result.leaders.map((leader, index) => (
                  <Card key={leader.channel_id}>
                    <CardContent className="space-y-3 p-4">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="mb-1 flex items-center gap-2">
                            {index < 3 ? (
                              <Badge variant={index === 0 ? "warning" : "secondary"}>{index + 1}</Badge>
                            ) : (
                              <span className="text-sm text-muted-foreground">#{index + 1}</span>
                            )}
                            <span className="font-bold text-primary">{leader.growth_score}</span>
                          </div>
                          <p className="font-medium leading-snug">{leader.channel_title}</p>
                          {leader.topic ? (
                            <p className="mt-1 text-xs text-muted-foreground">{leader.topic}</p>
                          ) : null}
                        </div>
                      </div>
                      <div className="grid grid-cols-2 gap-2 text-sm">
                        <div className="rounded-md bg-muted/30 px-3 py-2">
                          <p className="text-[10px] uppercase text-muted-foreground">Подписчики</p>
                          <p className="mt-1 font-semibold">{formatNumber(leader.current_subscribers)}</p>
                        </div>
                        <div className="rounded-md bg-muted/30 px-3 py-2">
                          <p className="text-[10px] uppercase text-muted-foreground">Рост подпис.</p>
                          <p className="mt-1 font-semibold text-emerald-400">+{leader.subscribers_growth_pct}%</p>
                        </div>
                        <div className="col-span-2 rounded-md bg-muted/30 px-3 py-2">
                          <p className="text-[10px] uppercase text-muted-foreground">Рост просмотров</p>
                          <p className="mt-1 font-semibold text-emerald-400">+{leader.views_growth_pct}%</p>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function LeadersTableSkeleton() {
  return (
    <Card>
      <div className="space-y-3 p-4">
        {Array.from({ length: 10 }).map((_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    </Card>
  );
}
