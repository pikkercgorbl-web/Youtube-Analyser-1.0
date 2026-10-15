"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { SAVED_RESEARCH_STATUS_LABELS } from "@/lib/saved-research-labels";
import type { SavedResearchStatus } from "@/lib/saved-research-types";

const STATUSES: SavedResearchStatus[] = [
  "WATCHING",
  "WANT_TO_TEST",
  "TESTING",
  "DROPPED",
];

type Props = {
  status: SavedResearchStatus;
  notes: string;
  tagsText: string;
  archivedAt: string | null;
  saving: boolean;
  saveMessage: string | null;
  saveError: string | null;
  onStatusChange: (status: SavedResearchStatus) => void;
  onNotesChange: (notes: string) => void;
  onTagsChange: (tags: string) => void;
  onSave: () => void;
  onArchive: () => void;
  onRestore: () => void;
};

export function SavedResearchMetadataForm({
  status,
  notes,
  tagsText,
  archivedAt,
  saving,
  saveMessage,
  saveError,
  onStatusChange,
  onNotesChange,
  onTagsChange,
  onSave,
  onArchive,
  onRestore,
}: Props) {
  return (
    <section className="rounded-xl border border-border p-4 space-y-4">
      <h2 className="font-semibold">Ваши заметки</h2>
      <label className="block text-sm">
        Статус
        <select
          className="mt-1 w-full rounded-md border border-input bg-transparent px-2 py-2"
          value={status}
          onChange={(e) => onStatusChange(e.target.value as SavedResearchStatus)}
          disabled={Boolean(archivedAt)}
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {SAVED_RESEARCH_STATUS_LABELS[s]}
            </option>
          ))}
        </select>
      </label>
      <label className="block text-sm">
        Заметки
        <Textarea
          className="mt-1"
          value={notes}
          onChange={(e) => onNotesChange(e.target.value)}
          disabled={Boolean(archivedAt)}
          rows={4}
        />
      </label>
      <label className="block text-sm">
        Теги (через запятую)
        <Input
          className="mt-1"
          value={tagsText}
          onChange={(e) => onTagsChange(e.target.value)}
          disabled={Boolean(archivedAt)}
        />
      </label>
      <div className="flex flex-wrap gap-2">
        <Button type="button" onClick={onSave} disabled={saving || Boolean(archivedAt)}>
          {saving ? "Сохранение…" : "Сохранить"}
        </Button>
        {archivedAt ? (
          <Button type="button" variant="secondary" onClick={onRestore}>
            Восстановить
          </Button>
        ) : (
          <Button type="button" variant="outline" onClick={onArchive}>
            Убрать из сохранённых
          </Button>
        )}
      </div>
      {saveMessage ? <p className="text-sm text-primary">{saveMessage}</p> : null}
      {saveError ? <p className="text-sm text-destructive">{saveError}</p> : null}
    </section>
  );
}
