"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";

import {
  ErrorState,
  LoadingState,
  PageHeader,
  PageShell,
  SectionPanel,
} from "@/components/design-system";
import { Input } from "@/components/ui/input";
import { buttonVariants } from "@/components/ui/button";
import { listSavedTopics } from "@/lib/api";
import { familyDetailHref } from "@/lib/attention-format";
import { SAVED_TOPIC_STATUS_LABELS } from "@/lib/saved-topics";
import type { SavedTopicListItem } from "@/lib/saved-topics-types";
import { cn } from "@/lib/utils";

type ArchiveFilter = "active" | "archived" | "all";

export function SavedTopicsListView() {
  const [items, setItems] = useState<SavedTopicListItem[]>([]);
  const [state, setState] = useState<"loading" | "error" | "ready">("loading");
  const [message, setMessage] = useState("");
  const [query, setQuery] = useState("");
  const [archived, setArchived] = useState<ArchiveFilter>("active");

  const load = useCallback(async () => {
    setState("loading");
    try {
      const data = await listSavedTopics({ archived, q: query.trim() || undefined });
      setItems(data.items);
      setState("ready");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Не удалось загрузить список");
      setState("error");
    }
  }, [archived, query]);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = useMemo(() => items, [items]);

  return (
    <PageShell>
      <PageHeader
        title="Сохранённые темы"
        lead="Watchlist по семействам паттернов (family_key). «Тогда» — замороженный снимок при сохранении; «Сейчас» — последнее observation."
      />
      <SectionPanel title="Фильтры">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <Input
            placeholder="Поиск по названию, тегам, заметкам…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="max-w-md"
          />
          <select
            className="h-9 rounded-md border border-input bg-background px-3 text-sm"
            value={archived}
            onChange={(event) => setArchived(event.target.value as ArchiveFilter)}
          >
            <option value="active">Активные</option>
            <option value="archived">Архив</option>
            <option value="all">Все</option>
          </select>
        </div>
      </SectionPanel>
      {state === "loading" ? <LoadingState title="Загрузка сохранённых тем…" /> : null}
      {state === "error" ? <ErrorState title={message} onRetry={() => void load()} /> : null}
      {state === "ready" ? (
        <SectionPanel title={`Записи (${filtered.length})`}>
          {filtered.length === 0 ? (
            <p className="text-sm text-muted-foreground">Нет сохранённых тем для выбранного фильтра.</p>
          ) : (
            <ul className="divide-y divide-border/60">
              {filtered.map((item) => (
                <li key={item.id} className="flex flex-col gap-2 py-4 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <Link href={`/saved-topics/${item.id}`} className="text-sm font-semibold hover:underline">
                      {item.label}
                    </Link>
                    <p className="text-xs text-muted-foreground">{item.family_key}</p>
                    <p className="mt-1 text-xs">
                      {SAVED_TOPIC_STATUS_LABELS[item.status] ?? item.status}
                      {item.tags.length ? ` · ${item.tags.join(", ")}` : ""}
                    </p>
                    {item.latest_observation_at ? (
                      <p className="text-xs text-muted-foreground">
                        Последнее observation: {new Date(item.latest_observation_at).toLocaleString()}
                        {item.present_in_latest_snapshot === false ? " · нет в текущей выборке" : ""}
                      </p>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Link href={`/saved-topics/${item.id}`} className={cn(buttonVariants({ variant: "secondary", size: "sm" }))}>
                      Карточка
                    </Link>
                    <Link
                      href={familyDetailHref(item.family_key)}
                      className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
                    >
                      Семейство
                    </Link>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </SectionPanel>
      ) : null}
    </PageShell>
  );
}
