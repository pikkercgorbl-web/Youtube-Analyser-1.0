"use client";

import { useCallback, useEffect, useState } from "react";
import { Bookmark, Loader2, Pencil, Trash2, X } from "lucide-react";

import { deleteSavedKeyword, fetchSavedKeywords, saveSavedKeyword } from "@/lib/api";
import type { SavedKeywordItem } from "@/lib/types";
import { cn, keywordScoreTextColor } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { StateMessage } from "@/components/ui/state-message";

export default function SavedKeywordsPage() {
  const [items, setItems] = useState<SavedKeywordItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [editingItem, setEditingItem] = useState<SavedKeywordItem | null>(null);

  const loadItems = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const data = await fetchSavedKeywords();
      setItems(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить ключи");
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadItems();
  }, [loadItems]);

  const handleDelete = async (id: number) => {
    setDeletingId(id);
    setError(null);

    try {
      await deleteSavedKeyword(id);
      setItems((current) => current.filter((item) => item.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось удалить ключ");
    } finally {
      setDeletingId(null);
    }
  };

  const handleCategorySave = async (item: SavedKeywordItem, category: string) => {
    const updated = await saveSavedKeyword({
      keyword: item.keyword,
      volume: item.volume,
      competition: item.competition,
      score: item.score,
      category,
    });
    setItems((current) =>
      current
        .map((row) => (row.id === updated.id ? updated : row))
        .sort((a, b) => b.score - a.score || b.id - a.id),
    );
  };

  return (
    <div className="space-y-6">
      <header>
        <div className="flex items-center gap-2">
          <Bookmark className="h-6 w-6 text-primary" />
          <h1 className="text-2xl font-bold tracking-tight">Сохраненные идеи</h1>
        </div>
        <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
          База ключевых слов с метриками SEO. Группируйте идеи по категориям ниш — расследования, k-pop,
          теории заговора и другие.
        </p>
      </header>

      {loading && <SavedKeywordsSkeleton />}

      {!loading && error && (
        <StateMessage variant="error" title="Ошибка загрузки" description={error} />
      )}

      {!loading && !error && items.length === 0 && (
        <StateMessage
          title="Пока нет сохранённых ключей"
          description="Проанализируйте ключ на странице «Ключевые слова» и нажмите «Сохранить в базу»."
        />
      )}

      {!loading && !error && items.length > 0 && (
        <>
          <Card className="hidden md:block">
            <CardHeader>
              <CardTitle className="text-base">
                Сохранено ключей: {items.length}
              </CardTitle>
            </CardHeader>
            <CardContent className="overflow-x-auto p-0">
              <table className="w-full min-w-[760px] text-sm">
                <thead>
                  <tr className="border-b border-border/60 text-left text-muted-foreground">
                    <th className="px-4 py-3 font-medium">Ключевое слово</th>
                    <th className="px-4 py-3 font-medium">Категория</th>
                    <th className="px-4 py-3 font-medium">Объем</th>
                    <th className="px-4 py-3 font-medium">Конкуренция</th>
                    <th className="px-4 py-3 font-medium">Оценка</th>
                    <th className="px-4 py-3 font-medium">Действия</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr
                      key={item.id}
                      className="border-b border-border/40 transition-colors hover:bg-muted/20"
                    >
                      <td className="px-4 py-3 font-medium">{item.keyword}</td>
                      <td className="px-4 py-3">
                        <button
                          type="button"
                          onClick={() => setEditingItem(item)}
                          className="group flex max-w-[220px] items-center gap-2 rounded-md border border-transparent px-2 py-1 text-left transition-colors hover:border-border/60 hover:bg-muted/40"
                          title="Изменить категорию"
                        >
                          <span className={cn("truncate", !item.category && "text-muted-foreground italic")}>
                            {item.category || "Без категории"}
                          </span>
                          <Pencil className="h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
                        </button>
                      </td>
                      <td className={cn("px-4 py-3 tabular-nums", keywordScoreTextColor(item.volume, "volume"))}>
                        {item.volume}
                      </td>
                      <td
                        className={cn(
                          "px-4 py-3 tabular-nums",
                          keywordScoreTextColor(item.competition, "competition"),
                        )}
                      >
                        {item.competition}
                      </td>
                      <td className={cn("px-4 py-3 tabular-nums", keywordScoreTextColor(item.score, "overall"))}>
                        {item.score.toFixed(1)}
                      </td>
                      <td className="px-4 py-3">
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => void handleDelete(item.id)}
                          disabled={deletingId === item.id}
                          className="h-8 w-8 text-muted-foreground hover:text-rose-400"
                          title="Удалить"
                        >
                          {deletingId === item.id ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <Trash2 className="h-4 w-4" />
                          )}
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>

          <div className="space-y-3 md:hidden">
            <p className="text-sm font-medium text-muted-foreground">Сохранено ключей: {items.length}</p>
            {items.map((item) => (
              <Card key={item.id}>
                <CardContent className="space-y-3 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <p className="min-w-0 flex-1 font-medium leading-snug">{item.keyword}</p>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => void handleDelete(item.id)}
                      disabled={deletingId === item.id}
                      className="h-8 w-8 shrink-0 text-muted-foreground hover:text-rose-400"
                      title="Удалить"
                    >
                      {deletingId === item.id ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Trash2 className="h-4 w-4" />
                      )}
                    </Button>
                  </div>

                  <button
                    type="button"
                    onClick={() => setEditingItem(item)}
                    className="flex w-full items-center gap-2 rounded-md border border-border/60 bg-muted/20 px-3 py-2 text-left text-sm"
                  >
                    <span className={cn("min-w-0 flex-1 truncate", !item.category && "text-muted-foreground italic")}>
                      {item.category || "Без категории"}
                    </span>
                    <Pencil className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  </button>

                  <div className="grid grid-cols-3 gap-2 text-center text-sm">
                    <div className="rounded-md bg-muted/30 px-2 py-2">
                      <p className="text-[10px] uppercase text-muted-foreground">Объём</p>
                      <p className={cn("mt-1 font-semibold tabular-nums", keywordScoreTextColor(item.volume, "volume"))}>
                        {item.volume}
                      </p>
                    </div>
                    <div className="rounded-md bg-muted/30 px-2 py-2">
                      <p className="text-[10px] uppercase text-muted-foreground">Конкур.</p>
                      <p
                        className={cn(
                          "mt-1 font-semibold tabular-nums",
                          keywordScoreTextColor(item.competition, "competition"),
                        )}
                      >
                        {item.competition}
                      </p>
                    </div>
                    <div className="rounded-md bg-muted/30 px-2 py-2">
                      <p className="text-[10px] uppercase text-muted-foreground">Оценка</p>
                      <p className={cn("mt-1 font-semibold tabular-nums", keywordScoreTextColor(item.score, "overall"))}>
                        {item.score.toFixed(1)}
                      </p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </>
      )}

      {editingItem ? (
        <CategoryEditModal
          item={editingItem}
          onClose={() => setEditingItem(null)}
          onSave={handleCategorySave}
        />
      ) : null}
    </div>
  );
}

function CategoryEditModal({
  item,
  onClose,
  onSave,
}: {
  item: SavedKeywordItem;
  onClose: () => void;
  onSave: (item: SavedKeywordItem, category: string) => Promise<void>;
}) {
  const [category, setCategory] = useState(item.category);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);

    try {
      await onSave(item, category.trim());
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить категорию");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="w-full max-w-md rounded-xl border border-border/60 bg-card p-5 shadow-xl"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="category-modal-title"
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2 id="category-modal-title" className="text-base font-semibold">
              Категория ниши
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">«{item.keyword}»</p>
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} className="h-8 w-8 shrink-0">
            <X className="h-4 w-4" />
          </Button>
        </div>

        <form onSubmit={(event) => void handleSubmit(event)} className="space-y-4">
          <div className="space-y-2">
            <label htmlFor="category-input" className="text-sm text-muted-foreground">
              Категория
            </label>
            <Input
              id="category-input"
              value={category}
              onChange={(event) => setCategory(event.target.value)}
              placeholder="расследования, k-pop, теории заговора..."
              maxLength={128}
              autoFocus
            />
          </div>

          {error ? <p className="text-sm text-rose-400">{error}</p> : null}

          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose} disabled={saving}>
              Отмена
            </Button>
            <Button type="submit" disabled={saving} className="gap-2">
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {saving ? "Сохранение..." : "Сохранить"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

function SavedKeywordsSkeleton() {
  return (
    <Card>
      <CardContent className="p-4">
        <Skeleton className="mb-4 h-6 w-48" />
        <Skeleton className="h-64 w-full" />
      </CardContent>
    </Card>
  );
}
