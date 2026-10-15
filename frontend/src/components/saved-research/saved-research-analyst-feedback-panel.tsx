"use client";

import { useCallback, useEffect, useState } from "react";

import { SectionPanel } from "@/components/design-system";
import { Button } from "@/components/ui/button";
import {
  getSavedFamilyFeedback,
  getSavedVideoFeedback,
  postSavedFamilyFeedback,
  postSavedVideoFeedback,
} from "@/lib/api";
import type {
  SavedResearchAnalystVerdict,
  SavedResearchFeedbackEntry,
} from "@/lib/saved-research-analyst-feedback-types";
import { ANALYST_VERDICT_LABELS, ANALYST_VERDICT_OPTIONS } from "@/lib/saved-research-labels";

const PAGE = 10;

type Props = {
  kind: "video" | "family";
  entityId: number;
  archived: boolean;
};

export function SavedResearchAnalystFeedbackPanel({ kind, entityId, archived }: Props) {
  const [verdict, setVerdict] = useState<SavedResearchAnalystVerdict>("USEFUL");
  const [reason, setReason] = useState("");
  const [latest, setLatest] = useState<SavedResearchFeedbackEntry | null>(null);
  const [history, setHistory] = useState<SavedResearchFeedbackEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const loadFeedback = useCallback(
    async (nextOffset: number, append: boolean) => {
      setLoading(true);
      setError(null);
      try {
        const res =
          kind === "video"
            ? await getSavedVideoFeedback(entityId, { limit: PAGE, offset: nextOffset })
            : await getSavedFamilyFeedback(entityId, { limit: PAGE, offset: nextOffset });
        setLatest(res.latest);
        setTotal(res.total);
        setOffset(nextOffset + res.items.length);
        setHistory((prev) => (append ? [...prev, ...res.items] : res.items));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Не удалось загрузить оценки");
      } finally {
        setLoading(false);
      }
    },
    [kind, entityId],
  );

  useEffect(() => {
    void loadFeedback(0, false);
  }, [loadFeedback]);

  const onSubmit = async () => {
    setSubmitting(true);
    setError(null);
    setSuccess(null);
    try {
      if (kind === "video") {
        await postSavedVideoFeedback(entityId, {
          verdict,
          reason: reason.trim() || null,
        });
      } else {
        await postSavedFamilyFeedback(entityId, {
          verdict,
          reason: reason.trim() || null,
        });
      }
      setSuccess("Оценка сохранена");
      setReason("");
      await loadFeedback(0, false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <SectionPanel title="Оценка аналитика" description="Ваш вердикт о полезности идеи">
      {latest ? (
        <p className="text-sm mb-3">
          Текущая оценка:{" "}
          <span className="font-medium">{ANALYST_VERDICT_LABELS[latest.verdict]}</span>
          {latest.reason ? (
            <span className="text-muted-foreground"> — {latest.reason}</span>
          ) : null}
        </p>
      ) : (
        <p className="text-sm text-muted-foreground mb-3">Оценок пока нет.</p>
      )}

      {archived ? (
        <p className="text-sm text-amber-200 mb-3">
          В архиве новые оценки не принимаются. История сохранена.
        </p>
      ) : (
        <div className="space-y-3">
          <label className="block text-sm">
            <span className="text-muted-foreground">Вердикт</span>
            <select
              className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
              value={verdict}
              onChange={(e) => setVerdict(e.target.value as SavedResearchAnalystVerdict)}
            >
              {ANALYST_VERDICT_OPTIONS.map((v) => (
                <option key={v} value={v}>
                  {ANALYST_VERDICT_LABELS[v]}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            <span className="text-muted-foreground">Комментарий (необязательно)</span>
            <textarea
              className="mt-1 w-full min-h-[72px] rounded-md border border-border bg-background px-3 py-2 text-sm"
              maxLength={1000}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Почему такой вердикт"
            />
          </label>
          <Button type="button" disabled={submitting} onClick={() => void onSubmit()}>
            {submitting ? "Сохранение…" : "Сохранить оценку"}
          </Button>
        </div>
      )}

      {success ? <p className="mt-2 text-sm text-green-400">{success}</p> : null}
      {error ? <p className="mt-2 text-sm text-red-400">{error}</p> : null}

      {history.length > 0 ? (
        <div className="mt-4 border-t border-border pt-4">
          <h4 className="text-sm font-medium">История оценок</h4>
          <ul className="mt-2 space-y-2 text-sm">
            {history.map((entry) => (
              <li key={entry.id} className="rounded-lg border border-border/60 px-3 py-2">
                <div className="flex flex-wrap justify-between gap-2">
                  <span className="font-medium">{ANALYST_VERDICT_LABELS[entry.verdict]}</span>
                  <span className="text-xs text-muted-foreground">
                    {new Date(entry.created_at).toLocaleString()}
                  </span>
                </div>
                {entry.reason ? (
                  <p className="mt-1 text-muted-foreground">{entry.reason}</p>
                ) : null}
              </li>
            ))}
          </ul>
          {history.length < total ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="mt-2"
              disabled={loading}
              onClick={() => void loadFeedback(offset, true)}
            >
              {loading ? "Загрузка…" : "Показать ещё"}
            </Button>
          ) : null}
        </div>
      ) : null}
    </SectionPanel>
  );
}
