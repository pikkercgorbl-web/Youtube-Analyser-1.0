"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { PageHeader, PageShell, LoadingState, ErrorState } from "@/components/design-system";
import { SavedResearchFeedbackPanel } from "@/components/saved-research/saved-research-feedback-panel";
import { SavedVideoListItem } from "@/components/saved-research/saved-video-list-item";
import { listSavedFamilies, listSavedVideos } from "@/lib/api";
import {
  ANALYST_VERDICT_LABELS,
  SAVED_RESEARCH_STATUS_LABELS,
} from "@/lib/saved-research-labels";
import { formatFamilyCountLine } from "@/lib/saved-research-list-format";
import type { SavedFamilyListItem, SavedVideoListItem as SavedVideoRow } from "@/lib/saved-research-types";
import { cn } from "@/lib/utils";

type Tab = "videos" | "families";

export default function SavedResearchPage() {
  const [tab, setTab] = useState<Tab>("videos");
  const [videos, setVideos] = useState<SavedVideoRow[]>([]);
  const [families, setFamilies] = useState<SavedFamilyListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [v, f] = await Promise.all([
        listSavedVideos({ archived: "active" }),
        listSavedFamilies({ archived: "active" }),
      ]);
      setVideos(v.items);
      setFamilies(f.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <PageShell>
      <PageHeader title="Сохранённое" lead="Видео и темы для наблюдения и ваших оценок." />
      <SavedResearchFeedbackPanel />
      <div className="mb-4 flex gap-2">
        {(
          [
            ["videos", `Видео (${videos.length})`],
            ["families", `Темы (${families.length})`],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={cn(
              "rounded-full px-4 py-2 text-sm font-medium",
              tab === key ? "bg-primary text-primary-foreground" : "bg-muted",
            )}
          >
            {label}
          </button>
        ))}
      </div>
      {loading ? <LoadingState title="Загрузка…" /> : null}
      {error ? <ErrorState title="Ошибка" description={error} onRetry={load} /> : null}
      {!loading && !error && tab === "videos" ? (
        <ul className="max-w-full space-y-2 overflow-x-hidden">
          {videos.length === 0 ? (
            <p className="text-sm text-muted-foreground">Нет сохранённых видео.</p>
          ) : (
            videos.map((row) => <SavedVideoListItem key={row.id} row={row} />)
          )}
        </ul>
      ) : null}
      {!loading && !error && tab === "families" ? (
        <ul className="space-y-2">
          {families.length === 0 ? (
            <p className="text-sm text-muted-foreground">Нет сохранённых тем.</p>
          ) : (
            families.map((row) => (
              <li key={row.id} className="rounded-xl border border-border p-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <Link href={`/saved/families/${row.id}`} className="font-semibold hover:text-primary">
                    {row.label}
                  </Link>
                  <span className="text-xs text-muted-foreground">
                    {SAVED_RESEARCH_STATUS_LABELS[row.status]}
                  </span>
                </div>
                <p className="mt-2 text-sm">{formatFamilyCountLine(row)}</p>
                {row.latest_analyst_verdict ? (
                  <p className="mt-1 text-xs">
                    Оценка: {ANALYST_VERDICT_LABELS[row.latest_analyst_verdict]}
                  </p>
                ) : null}
              </li>
            ))
          )}
        </ul>
      ) : null}
    </PageShell>
  );
}
