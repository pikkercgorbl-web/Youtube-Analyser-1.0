"use client";

import { Loader2, Sparkles, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface AiIdeasModalProps {
  open: boolean;
  loading: boolean;
  error: string | null;
  ideas: string[];
  onClose: () => void;
}

export function AiIdeasModal({ open, loading, error, ideas, onClose }: AiIdeasModalProps) {
  if (!open) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 p-0 sm:items-center sm:p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="ai-ideas-modal-title"
        className="flex max-h-[92vh] w-full flex-col overflow-hidden rounded-t-xl border border-border/60 bg-card shadow-2xl sm:max-h-[85vh] sm:max-w-lg sm:rounded-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-border/60 bg-gradient-to-r from-indigo-500/10 to-violet-500/10 px-5 py-4">
          <div className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-indigo-400" />
            <h2 id="ai-ideas-modal-title" className="text-lg font-semibold">
              Идеи для видео от AI
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            aria-label="Закрыть"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          {loading ? (
            <div className="flex flex-col items-center justify-center gap-3 py-10 text-muted-foreground">
              <Loader2 className="h-8 w-8 animate-spin text-indigo-400" />
              <p className="text-sm">Gemini анализирует названия...</p>
            </div>
          ) : null}

          {!loading && error ? (
            <p className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
              {error}
            </p>
          ) : null}

          {!loading && !error && ideas.length > 0 ? (
            <ol className="space-y-3">
              {ideas.map((idea, index) => (
                <li
                  key={`${index}-${idea.slice(0, 24)}`}
                  className={cn(
                    "flex gap-3 rounded-lg border border-border/60 bg-muted/20 px-4 py-3",
                    "transition-colors hover:border-indigo-500/40 hover:bg-indigo-500/5",
                  )}
                >
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-indigo-500/20 text-xs font-bold text-indigo-300">
                    {index + 1}
                  </span>
                  <p className="text-sm leading-snug text-foreground">{idea}</p>
                </li>
              ))}
            </ol>
          ) : null}
        </div>

        <div className="border-t border-border/60 px-5 py-4">
          <Button type="button" variant="outline" className="w-full" onClick={onClose}>
            Закрыть
          </Button>
        </div>
      </div>
    </div>
  );
}
