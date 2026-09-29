"use client";

import { CircleHelp } from "lucide-react";

import { textRoles } from "@/lib/design-system/typography";
import { cn } from "@/lib/utils";

export function InfoTooltip({
  content,
  className,
  label = "Подсказка",
}: {
  content: string;
  className?: string;
  label?: string;
}) {
  return (
    <button
      type="button"
      className={cn(
        "inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
        className,
      )}
      aria-label={label}
      title={content}
      data-testid="info-tooltip"
    >
      <CircleHelp className="h-3.5 w-3.5" aria-hidden />
    </button>
  );
}

export function HelpText({ children, className }: { children: React.ReactNode; className?: string }) {
  return <p className={cn(textRoles.helper, className)}>{children}</p>;
}
