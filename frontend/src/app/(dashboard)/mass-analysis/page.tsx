"use client";

import { useState } from "react";
import { Play, Users } from "lucide-react";
import { runMassAnalysis } from "@/lib/api";
import type { MassAnalysisResponse } from "@/lib/types";
import { parseChannelRefs } from "@/lib/utils";
import { TrendsTable } from "@/components/mass-analysis/trends-table";
import { TrendsTableSkeleton } from "@/components/mass-analysis/trends-table-skeleton";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { StateMessage } from "@/components/ui/state-message";
import { Textarea } from "@/components/ui/textarea";

const MIN_CHANNELS = 3;
const MAX_CHANNELS = 20;

export default function MassAnalysisPage() {
  const [rawInput, setRawInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<MassAnalysisResponse | null>(null);

  const refs = parseChannelRefs(rawInput);
  const count = refs.length;
  const isValidCount = count >= MIN_CHANNELS && count <= MAX_CHANNELS;

  const handleAnalyze = async () => {
    if (!isValidCount) return;

    setLoading(true);
    setError(null);

    try {
      const data = await runMassAnalysis(refs);
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
          <Users className="h-6 w-6 text-primary" />
          <h1 className="text-2xl font-bold tracking-tight">Outlier-анализ видео</h1>
        </div>
        <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
          Вставьте от 3 до 20 ссылок на YouTube-каналы конкурентов — система загрузит последние 30 видео,
          сравнит каждое видео со средними просмотрами канала и покажет самые аномально популярные ролики.
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Ссылки на каналы</CardTitle>
          <CardDescription>
            По одной ссылке на строку: ID канала, URL или @handle. Сейчас: {count} / {MAX_CHANNELS}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Textarea
            placeholder={`https://youtube.com/@channel1\nUCxxxxxxxxxxxxxxxx\nhttps://youtube.com/channel/UC...\n...`}
            value={rawInput}
            onChange={(e) => setRawInput(e.target.value)}
            rows={10}
            className="font-mono text-xs"
          />

          {count > 0 && !isValidCount && (
            <p className="text-sm text-amber-400">
              Нужно от {MIN_CHANNELS} до {MAX_CHANNELS} каналов (сейчас {count}).
            </p>
          )}

          <Button onClick={handleAnalyze} disabled={loading || !isValidCount} className="gap-2">
            <Play className="h-4 w-4" />
            {loading ? "Анализируем..." : "Запустить анализ"}
          </Button>
        </CardContent>
      </Card>

      {loading && <TrendsTableSkeleton />}

      {!loading && error && (
        <StateMessage variant="error" title="Анализ не выполнен" description={error} />
      )}

      {!loading && result && <TrendsTable data={result} />}

      {!loading && !error && !result && (
        <StateMessage
          title="Добавьте каналы конкурентов"
          description="Вставьте 3–20 ссылок и запустите анализ, чтобы увидеть единую ленту outlier-видео."
        />
      )}
    </div>
  );
}
