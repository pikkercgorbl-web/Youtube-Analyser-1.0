"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Bookmark, BookmarkCheck, Loader2 } from "lucide-react";

import { Button, buttonVariants } from "@/components/ui/button";
import {
  listSavedFamilies,
  listSavedVideos,
  saveDailyIntelligenceFamilyToResearch,
  saveDailyIntelligenceVideoToResearch,
} from "@/lib/api";

type BaseProps = {
  reportDate: string;
};

type VideoProps = BaseProps & {
  kind: "video";
  videoId: string;
};

type FamilyProps = BaseProps & {
  kind: "family";
  familyKey: string;
};

export function DailyIntelligenceSaveToResearchButton(props: VideoProps | FamilyProps) {
  const [savedId, setSavedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [archivedHint, setArchivedHint] = useState(false);

  const entityKey = props.kind === "video" ? props.videoId : props.familyKey;

  useEffect(() => {
    let cancelled = false;
    setChecking(true);
    const load =
      props.kind === "video"
        ? listSavedVideos({ archived: "all" }).then((response) => {
            const active = response.items.find(
              (row) => row.video_id === props.videoId && !row.archived_at,
            );
            const archived = response.items.find(
              (row) => row.video_id === props.videoId && row.archived_at,
            );
            return { activeId: active?.id ?? null, hasArchived: Boolean(archived) };
          })
        : listSavedFamilies({ archived: "all" }).then((response) => {
            const active = response.items.find(
              (row) => row.family_key === props.familyKey && !row.archived_at,
            );
            const archived = response.items.find(
              (row) => row.family_key === props.familyKey && row.archived_at,
            );
            return { activeId: active?.id ?? null, hasArchived: Boolean(archived) };
          });

    load
      .then(({ activeId, hasArchived }) => {
        if (cancelled) return;
        setSavedId(activeId);
        setArchivedHint(hasArchived && activeId === null);
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
  }, [props.kind, entityKey, props]);

  const onSave = useCallback(async () => {
    if (savedId !== null) return;
    setLoading(true);
    setError(null);
    setArchivedHint(false);
    try {
      const response =
        props.kind === "video"
          ? await saveDailyIntelligenceVideoToResearch(props.reportDate, props.videoId)
          : await saveDailyIntelligenceFamilyToResearch(props.reportDate, props.familyKey);
      setSavedId(response.item.id);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number; data?: { detail?: string } } })
        ?.response?.status;
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      if (status === 409) {
        setArchivedHint(true);
        setError(
          typeof detail === "string"
            ? detail
            : "Объект в архиве Saved Research. Восстановите его на странице «Сохранённое».",
        );
      } else {
        setError(
          typeof detail === "string"
            ? detail
            : err instanceof Error
              ? err.message
              : "Не удалось сохранить",
        );
      }
    } finally {
      setLoading(false);
    }
  }, [props, savedId]);

  const savedHref =
    props.kind === "video" ? `/saved/videos/${savedId}` : `/saved/families/${savedId}`;

  if (checking) {
    return (
      <Button type="button" variant="outline" size="sm" disabled data-testid="di-save-to-research">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      </Button>
    );
  }

  if (savedId !== null) {
    return (
      <Link
        href={savedHref}
        className={buttonVariants({ variant: "secondary", size: "sm" })}
        data-testid="di-save-to-research-saved"
      >
        <BookmarkCheck className="h-3.5 w-3.5" />
        В исследовании
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
        data-testid="di-save-to-research"
      >
        {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Bookmark className="h-3.5 w-3.5" />}
        Сохранить в исследование
      </Button>
      {archivedHint ? (
        <p className="text-xs text-muted-foreground max-w-prose">
          Есть архивированная запись с тем же ключом. Автовосстановление не выполняется.
        </p>
      ) : null}
      {error ? <p className="text-xs text-destructive max-w-prose">{error}</p> : null}
    </div>
  );
}
