"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Bookmark, BookmarkCheck, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { listSavedTopics, saveSavedTopic } from "@/lib/api";
import { savedTopicAffordance } from "@/lib/saved-topics";

type Props = {
  familyKey: string;
  runId: string | null;
};

export function SaveTopicButton({ familyKey, runId }: Props) {
  const affordance = savedTopicAffordance({ familyKey, runId });
  const [savedTopicId, setSavedTopicId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setChecking(true);
    listSavedTopics({ family_key: familyKey, archived: "all" })
      .then((response) => {
        if (cancelled) return;
        const item = response.items[0];
        if (item && !item.archived_at) {
          setSavedTopicId(item.id);
        } else {
          setSavedTopicId(null);
        }
      })
      .catch(() => {
        if (!cancelled) setSavedTopicId(null);
      })
      .finally(() => {
        if (!cancelled) setChecking(false);
      });
    return () => {
      cancelled = true;
    };
  }, [familyKey]);

  const onSave = useCallback(async () => {
    if (!affordance.enabled || savedTopicId !== null) return;
    setLoading(true);
    setError(null);
    try {
      const response = await saveSavedTopic(familyKey);
      if (response.archived_requires_restore) {
        setError(response.message ?? "Тема в архиве — восстановите из списка сохранённых");
        return;
      }
      setSavedTopicId(response.item.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить тему");
    } finally {
      setLoading(false);
    }
  }, [affordance.enabled, familyKey, savedTopicId]);

  if (checking) {
    return (
      <Button type="button" variant="outline" size="sm" disabled data-testid="save-pattern">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        …
      </Button>
    );
  }

  if (savedTopicId !== null) {
    return (
      <Link href={`/saved-topics/${savedTopicId}`} className="inline-flex">
        <Button type="button" variant="secondary" size="sm" data-testid="save-pattern-saved">
          <BookmarkCheck className="h-3.5 w-3.5" />
          Сохранено
        </Button>
      </Link>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={!affordance.enabled || loading}
        title={affordance.hint}
        onClick={() => void onSave()}
        data-testid="save-pattern"
      >
        {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Bookmark className="h-3.5 w-3.5" />}
        Сохранить
      </Button>
      {error ? <p className="text-xs text-destructive">{error}</p> : null}
    </div>
  );
}
