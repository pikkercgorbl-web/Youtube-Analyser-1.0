"use client";

import { ChevronDown } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { textRoles } from "@/lib/design-system/typography";
import { cn } from "@/lib/utils";

export function Disclosure({
  summary,
  children,
  defaultOpen = false,
  className,
}: {
  summary: React.ReactNode;
  children: React.ReactNode;
  defaultOpen?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className={cn("border-t border-border/50 pt-3", className)}>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="h-8 gap-1 px-0 text-muted-foreground hover:text-foreground"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <ChevronDown className={cn("h-4 w-4 transition-transform", open && "rotate-180")} />
        {summary}
      </Button>
      {open ? <div className="mt-3 space-y-2">{children}</div> : null}
    </div>
  );
}

export function ExpandableTableRow({
  colSpan,
  summary,
  children,
}: {
  colSpan: number;
  summary: React.ReactNode;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <tr className="border-b border-border/40">
        <td colSpan={colSpan} className="px-3 py-1">
          <button
            type="button"
            className={cn(textRoles.helper, "flex items-center gap-1 hover:text-foreground")}
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            <ChevronDown className={cn("h-3 w-3", open && "rotate-180")} />
            {summary}
          </button>
        </td>
      </tr>
      {open ? (
        <tr className="border-b border-border/30 bg-surface-sunken/30">
          <td colSpan={colSpan} className="px-3 py-3">
            {children}
          </td>
        </tr>
      ) : null}
    </>
  );
}
