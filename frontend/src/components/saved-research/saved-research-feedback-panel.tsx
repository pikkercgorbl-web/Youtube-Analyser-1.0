"use client";



import Link from "next/link";

import { useCallback, useEffect, useState } from "react";



import { ErrorState, LoadingState } from "@/components/design-system";

import { getSavedResearchFeedbackOverview } from "@/lib/api";

import { EVIDENCE_STATE_LABELS, SAVED_RESEARCH_STATUS_LABELS } from "@/lib/saved-research-labels";

import type {

  SavedResearchFeedbackItem,

  SavedResearchFeedbackOverview,

} from "@/lib/saved-research-feedback-types";

import type { SavedResearchStatus } from "@/lib/saved-research-types";



function itemHref(item: SavedResearchFeedbackItem): string {

  return item.kind === "video" ? `/saved/videos/${item.id}` : `/saved/families/${item.id}`;

}



function itemTitle(item: SavedResearchFeedbackItem): string {

  if (item.kind === "video") {

    return item.title ?? `Видео #${item.id}`;

  }

  return item.label ?? `Тема #${item.id}`;

}



function evidenceLabel(state: string): string {

  return EVIDENCE_STATE_LABELS[state] ?? state;

}



export function SavedResearchFeedbackPanel() {

  const [data, setData] = useState<SavedResearchFeedbackOverview | null>(null);

  const [loading, setLoading] = useState(true);

  const [error, setError] = useState<string | null>(null);



  const load = useCallback(async () => {

    setLoading(true);

    setError(null);

    try {

      const overview = await getSavedResearchFeedbackOverview();

      setData(overview);

    } catch (err) {

      setError(err instanceof Error ? err.message : "Ошибка загрузки");

    } finally {

      setLoading(false);

    }

  }, []);



  useEffect(() => {

    void load();

  }, [load]);



  if (loading) {

    return <LoadingState title="Сводка…" />;

  }

  if (error) {

    return <ErrorState title={error} onRetry={() => void load()} />;

  }

  if (!data) {

    return null;

  }



  const summary = data.evidence_summary;



  return (

    <section className="mb-6 rounded-xl border border-border bg-card/40 p-4">

      <h2 className="text-base font-semibold">Сводка</h2>

      <div className="mt-3 grid gap-2 sm:grid-cols-3">

        <div className="rounded-lg border border-border/80 px-3 py-2">

          <p className="text-xs text-muted-foreground">Есть данные для сравнения</p>

          <p className="text-xl font-semibold tabular-nums">{summary.validated ?? 0}</p>

        </div>

        <div className="rounded-lg border border-border/80 px-3 py-2">

          <p className="text-xs text-muted-foreground">Нужно больше наблюдений</p>

          <p className="text-xl font-semibold tabular-nums">{summary.pending ?? 0}</p>

        </div>

        <div className="rounded-lg border border-border/80 px-3 py-2">

          <p className="text-xs text-muted-foreground">Недостаточно наблюдений</p>

          <p className="text-xl font-semibold tabular-nums">{summary.insufficient ?? 0}</p>

        </div>

      </div>



      {Object.keys(data.status_counts).length > 0 ? (

        <p className="mt-3 text-xs text-muted-foreground">

          Статусы:{" "}

          {Object.entries(data.status_counts)

            .map(([key, count]) => {

              const label =

                key in SAVED_RESEARCH_STATUS_LABELS

                  ? SAVED_RESEARCH_STATUS_LABELS[key as SavedResearchStatus]

                  : key;

              return `${label}: ${count}`;

            })

            .join(" · ")}

        </p>

      ) : null}



      {data.measurable_growth_videos.length > 0 ? (

        <p className="mt-2 text-xs">

          Рост просмотров:{" "}

          {data.measurable_growth_videos.slice(0, 4).map((item, i) => (

            <span key={`g-${item.kind}-${item.id}`}>

              {i > 0 ? ", " : ""}

              <Link href={itemHref(item)} className="text-primary hover:underline">

                {itemTitle(item)}

              </Link>

            </span>

          ))}

        </p>

      ) : null}



      {data.recently_updated.length > 0 ? (

        <p className="mt-2 text-xs text-muted-foreground">

          Недавно обновлено:{" "}

          {data.recently_updated.slice(0, 5).map((item, i) => (

            <span key={`r-${item.kind}-${item.id}`}>

              {i > 0 ? " · " : ""}

              <Link href={itemHref(item)} className="text-primary hover:underline">

                {itemTitle(item)}

              </Link>{" "}

              ({evidenceLabel(String(item.validation.evidence_state ?? ""))})

            </span>

          ))}

        </p>

      ) : null}

    </section>

  );

}

