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
      const data = await listSavedTopics({
        archived,
        q: query.trim() || undefined,
      });
      setItems(data.items);
      setState("ready");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Не удалось загрузить список",
      );
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
        lead="Ваши темы для дальнейшей разведки. Сравнивайте изменения, оставляйте заметки и фиксируйте решения."
      />
      <SectionPanel title="Фильтры">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <Input
            aria-label="Поиск сохранённых тем"
            placeholder="Поиск по названию, тегам, заметкам…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="max-w-md"
          />
          <select
            aria-label="Показать активные или архивные темы"
            className="h-9 rounded-md border border-input bg-background px-3 text-sm"
            value={archived}
            onChange={(event) =>
              setArchived(event.target.value as ArchiveFilter)
            }
          >
            <option value="active">Активные</option>
            <option value="archived">Архив</option>
            <option value="all">Все</option>
          </select>
        </div>
      </SectionPanel>
      {state === "loading" ? (
        <LoadingState title="Загрузка сохранённых тем…" />
      ) : null}
      {state === "error" ? (
        <ErrorState title={message} onRetry={() => void load()} />
      ) : null}
      {state === "ready" ? (
        <SectionPanel title={`Записи (${filtered.length})`}>
          {filtered.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-border p-8">
              <p className="text-lg font-medium">Здесь пока нет тем</p>
              <p className="mt-2 text-muted-foreground">
                Измените фильтр или сохраните интересную подборку в
                «Возможностях».
              </p>
              <Link
                href="/opportunities"
                className="mt-4 inline-block text-primary hover:underline"
              >
                Найти тему для разведки →
              </Link>
            </div>
          ) : (
            <ul className="space-y-4">
              {filtered.map((item) => (
                <li
                  key={item.id}
                  className="flex flex-col gap-4 rounded-2xl border border-border bg-card p-5 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div>
                    <Link
                      href={`/saved-topics/${item.id}`}
                      className="text-lg font-semibold hover:text-primary"
                    >
                      {item.label}
                    </Link>

                    <p className="mt-1 text-xs">
                      {SAVED_TOPIC_STATUS_LABELS[item.status] ?? item.status}
                      {item.tags.length ? ` · ${item.tags.join(", ")}` : ""}
                    </p>
                    {item.latest_observation_at ? (
                      <p className="text-xs text-muted-foreground">
                        Последнее наблюдение:{" "}
                        {new Date(item.latest_observation_at).toLocaleString()}
                        {item.present_in_latest_snapshot === false
                          ? " · нет в текущей выборке"
                          : ""}
                      </p>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Link
                      href={`/saved-topics/${item.id}`}
                      className={cn(
                        buttonVariants({ variant: "secondary", size: "sm" }),
                      )}
                    >
                      Карточка
                    </Link>
                    <Link
                      href={familyDetailHref(item.family_key)}
                      className={cn(
                        buttonVariants({ variant: "outline", size: "sm" }),
                      )}
                    >
                      Исходная подборка
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
