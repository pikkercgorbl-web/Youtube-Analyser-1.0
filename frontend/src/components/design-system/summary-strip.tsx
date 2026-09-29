"use client";

import { AlertCircle, AlertTriangle, Info } from "lucide-react";

import { Button } from "@/components/ui/button";
import { surfaces } from "@/lib/design-system/layout";
import { textRoles } from "@/lib/design-system/typography";
import { cn } from "@/lib/utils";

export type SummaryTone = "neutral" | "informational" | "warning" | "error";

const toneStyles: Record<
  SummaryTone,
  { border: string; icon: typeof Info; iconClass: string }
> = {
  neutral: {
    border: "border-border/70",
    icon: Info,
    iconClass: "text-muted-foreground",
  },
  informational: {
    border: "border-primary/25",
    icon: Info,
    iconClass: "text-primary/80",
  },
  warning: {
    border: "border-status-warn/40",
    icon: AlertTriangle,
    iconClass: "text-status-warn",
  },
  error: {
    border: "border-status-error/40",
    icon: AlertCircle,
    iconClass: "text-status-error",
  },
};

export type SummaryLine = {
  id?: string;
  text: string;
  emphasis?: boolean;
};

export function SummaryStrip({
  tone = "neutral",
  lines,
  onDetails,
  detailsLabel = "Подробнее",
  className,
  "data-testid": testId,
}: {
  tone?: SummaryTone;
  lines: SummaryLine[];
  onDetails?: () => void;
  detailsLabel?: string;
  className?: string;
  "data-testid"?: string;
}) {
  const style = toneStyles[tone];
  const Icon = style.icon;

  return (
    <div
      className={cn(
        surfaces.sectionMuted,
        "flex flex-col gap-3 p-4 sm:flex-row sm:items-start sm:gap-4",
        style.border,
        className,
      )}
      data-testid={testId ?? "summary-strip"}
    >
      <Icon className={cn("mt-0.5 h-5 w-5 shrink-0", style.iconClass)} aria-hidden />
      <div className="min-w-0 flex-1 space-y-1">
        {lines.map((line, index) => (
          <p
            key={line.id ?? index}
            className={line.emphasis ? textRoles.summaryHeadline : textRoles.summarySupport}
          >
            {line.text}
          </p>
        ))}
      </div>
      {onDetails ? (
        <Button type="button" variant="ghost" size="sm" className="shrink-0" onClick={onDetails}>
          {detailsLabel}
        </Button>
      ) : null}
    </div>
  );
}
