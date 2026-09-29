"use client";

import { AlertCircle, CloudOff, Inbox, Loader2, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { StateMessage } from "@/components/ui/state-message";
import { textRoles } from "@/lib/design-system/typography";
import { cn } from "@/lib/utils";

export function LoadingState({
  title = "Загрузка…",
  variant = "block",
  rows = 3,
}: {
  title?: string;
  variant?: "block" | "table" | "inline";
  rows?: number;
}) {
  if (variant === "inline") {
    return (
      <span className="inline-flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        {title}
      </span>
    );
  }
  if (variant === "table") {
    return (
      <div className="space-y-2 p-4" role="status" aria-live="polite">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="h-9 animate-pulse rounded bg-muted/40" />
        ))}
        <span className="sr-only">{title}</span>
      </div>
    );
  }
  return <StateMessage variant="loading" title={title} />;
}

export function RefreshingIndicator({ visible }: { visible: boolean }) {
  if (!visible) {
    return null;
  }
  return (
    <p className={cn(textRoles.metadata, "flex items-center gap-1")} role="status">
      <RefreshCw className="h-3 w-3 animate-spin" aria-hidden />
      Обновление…
    </p>
  );
}

export function EmptyState({
  title,
  description,
  variant = "empty",
  compact,
  action,
}: {
  title: string;
  description?: string;
  variant?: "empty" | "unavailable";
  compact?: boolean;
  action?: React.ReactNode;
}) {
  const Icon = variant === "unavailable" ? CloudOff : Inbox;

  if (compact) {
    return (
      <div className="flex flex-col items-center px-4 py-10 text-center" data-testid="empty-state">
        <Icon className="mb-2 h-7 w-7 text-muted-foreground" aria-hidden />
        <p className={textRoles.summaryHeadline}>{title}</p>
        {description ? <p className={cn(textRoles.summarySupport, "mt-1 max-w-md")}>{description}</p> : null}
        {action ? <div className="mt-3">{action}</div> : null}
      </div>
    );
  }

  return (
    <div data-testid="empty-state">
      <StateMessage
        variant="empty"
        title={title}
        description={
          description ??
          (variant === "unavailable"
            ? "Данные по этому срезу пока недоступны (не путать с нулевым значением)."
            : undefined)
        }
      />
      {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
    </div>
  );
}

export function UnavailableState(props: Omit<React.ComponentProps<typeof EmptyState>, "variant">) {
  return <EmptyState {...props} variant="unavailable" />;
}

export function ErrorState({
  title,
  description,
  compact,
  onRetry,
}: {
  title: string;
  description?: string;
  compact?: boolean;
  onRetry?: () => void;
}) {
  if (compact) {
    return (
      <div
        className="flex flex-col items-center gap-2 px-4 py-10 text-center text-destructive"
        data-testid="error-state"
      >
        <AlertCircle className="h-7 w-7" aria-hidden />
        <p className={textRoles.summaryHeadline}>{title}</p>
        {description ? <p className={cn(textRoles.summarySupport, "text-muted-foreground")}>{description}</p> : null}
        {onRetry ? (
          <Button type="button" variant="outline" size="sm" onClick={onRetry}>
            Повторить
          </Button>
        ) : null}
      </div>
    );
  }

  return (
    <div data-testid="error-state">
      <StateMessage variant="error" title={title} description={description} />
      {onRetry ? (
        <Button type="button" className="mt-4" onClick={onRetry}>
          Повторить
        </Button>
      ) : null}
    </div>
  );
}

export function StaleDataWarning({
  message,
  generatedAtLabel,
}: {
  message: string;
  generatedAtLabel?: string;
}) {
  return (
    <div
      className="rounded-lg border border-status-warn/35 bg-status-warn/5 px-4 py-3 text-sm"
      role="status"
      data-testid="stale-data-warning"
    >
      <p className="font-medium text-status-warn">{message}</p>
      {generatedAtLabel ? (
        <p className={cn(textRoles.helper, "mt-1")}>Срез API: {generatedAtLabel}</p>
      ) : null}
    </div>
  );
}

/** Zero with context — not unavailable, not error */
export function ZeroContextNote({ children }: { children: React.ReactNode }) {
  return (
    <p className={cn(textRoles.helper, "rounded-md border border-border/50 bg-muted/20 px-3 py-2")} data-testid="zero-context">
      {children}
    </p>
  );
}
