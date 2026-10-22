"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Bookmark, BookmarkCheck, Loader2 } from "lucide-react";

import { Button, buttonVariants } from "@/components/ui/button";
import { listSavedVideos, saveManualSearchVideo, saveSavedVideo } from "@/lib/api";

type Props = {
  videoId: string;
  /** When set, skip list lookup and treat as already saved. */
  initialSavedId?: number | null;
  /** Use manual-search save endpoint (creates Video row from YouTube API). */
  fromManualSearch?: boolean;
  /** Skip initial listSavedVideos when context was loaded in batch. */
  skipInitialCheck?: boolean;
  onSaved?: (savedId: number) => void;
};

export function SaveVideoButton({
  videoId,
  initialSavedId = null,
  fromManualSearch = false,
  skipInitialCheck = false,
  onSaved,
}: Props) {
  const [savedId, setSavedId] = useState<number | null>(initialSavedId);
  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState(!skipInitialCheck && initialSavedId == null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSavedId(initialSavedId);
  }, [initialSavedId, videoId]);

  useEffect(() => {
    if (skipInitialCheck || initialSavedId != null) {
      setChecking(false);
      return;
    }
    let cancelled = false;
    setChecking(true);
    listSavedVideos({ archived: "all" })
      .then((response) => {
        if (cancelled) return;
        const item = response.items.find((row) => row.video_id === videoId && !row.archived_at);
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
  }, [videoId, skipInitialCheck, initialSavedId]);

  const onSave = useCallback(async () => {
    if (savedId !== null) return;
    setLoading(true);
    setError(null);
    try {
      const response = fromManualSearch
        ? await saveManualSearchVideo(videoId)
        : await saveSavedVideo(videoId);
      setSavedId(response.item.id);
      onSaved?.(response.item.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить видео");
    } finally {
      setLoading(false);
    }
  }, [fromManualSearch, savedId, videoId]);

  if (checking) {
    return (
      <Button type="button" variant="outline" size="sm" disabled data-testid="save-video">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      </Button>
    );
  }

  if (savedId !== null) {
    return (
      <Link
        href={`/saved/videos/${savedId}`}
        className={buttonVariants({ variant: "secondary", size: "sm" })}
        data-testid="save-video-saved"
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
        disabled={loading}
        onClick={() => void onSave()}
        data-testid="save-video"
      >
        {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Bookmark className="h-3.5 w-3.5" />}
        {loading ? "Сохраняется…" : "Сохранить"}
      </Button>
      {error ? <p className="text-xs text-destructive">{error}</p> : null}
    </div>
  );
}
