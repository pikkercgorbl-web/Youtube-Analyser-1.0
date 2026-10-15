"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Bookmark, BookmarkCheck, Loader2 } from "lucide-react";

import { Button, buttonVariants } from "@/components/ui/button";
import { listSavedFamilies, saveSavedFamily } from "@/lib/api";

type Props = {
  familyKey: string;
  runId: string | null;
  label?: string;
};

export function SaveFamilyButton({ familyKey, runId, label = "Сохранить тему" }: Props) {
  const [savedId, setSavedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const enabled = Boolean(familyKey && runId);

  useEffect(() => {
    let cancelled = false;
    setChecking(true);
    listSavedFamilies({ archived: "all" })
      .then((response) => {
        if (cancelled) return;
        const item = response.items.find(
          (row) => row.family_key === familyKey && !row.archived_at,
        );
        setSavedId(item?.id ?? null);
      })
      .catch(() => {
        if (!cancelled) setSavedId(null);
      })
      .finally(() => {
        if (!cancelled) setChecking(false);
      });
    return () => {
      cancelled = true;
    };
  }, [familyKey]);

  const onSave = useCallback(async () => {
    if (!enabled || savedId !== null) return;
    setLoading(true);
    setError(null);
    try {
      const response = await saveSavedFamily(familyKey);
      setSavedId(response.item.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить тему");
    } finally {
      setLoading(false);
    }
  }, [enabled, familyKey, savedId]);

  if (checking) {
    return (
      <Button type="button" variant="outline" size="sm" disabled data-testid="save-family">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      </Button>
    );
  }

  if (savedId !== null) {
    return (
      <Link
        href={`/saved/families/${savedId}`}
        className={buttonVariants({ variant: "secondary", size: "sm" })}
        data-testid="save-family-saved"
      >
        <BookmarkCheck className="h-3.5 w-3.5" />
        Сохранено
      </Link>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={!enabled || loading}
        title={enabled ? undefined : "Нет активного снимка Attention"}
        onClick={() => void onSave()}
        data-testid="save-family"
      >
        {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Bookmark className="h-3.5 w-3.5" />}
        {label}
      </Button>
      {error ? <p className="text-xs text-destructive">{error}</p> : null}
    </div>
  );
}
