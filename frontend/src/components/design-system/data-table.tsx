"use client";

import { Skeleton } from "@/components/ui/skeleton";
import { pageLayout } from "@/lib/design-system/layout";
import { textRoles } from "@/lib/design-system/typography";
import { cn } from "@/lib/utils";

import { EmptyState, ErrorState, LoadingState } from "./states";

export function DataTableShell({
  children,
  minWidthClassName = pageLayout.tableMinWidth,
  className,
  "data-testid": testId,
}: {
  children: React.ReactNode;
  minWidthClassName?: string;
  className?: string;
  "data-testid"?: string;
}) {
  return (
    <div
      className={cn("overflow-x-auto rounded-xl border border-border/70", className)}
      data-testid={testId}
    >
      <table className={cn("w-full text-left", minWidthClassName)}>{children}</table>
    </div>
  );
}

export function DataTableStickyHead({ children }: { children: React.ReactNode }) {
  return (
    <thead className={cn("sticky top-0 z-10 bg-card/95 backdrop-blur-sm", textRoles.tableHeader)}>
      {children}
    </thead>
  );
}

export function DataTableHead({ children }: { children: React.ReactNode }) {
  return (
    <thead className={cn("border-b border-border/60 bg-muted/20", textRoles.tableHeader)}>
      {children}
    </thead>
  );
}

export function DataTableRow({
  children,
  className,
  ...rest
}: {
  children: React.ReactNode;
  className?: string;
} & React.ComponentPropsWithoutRef<"tr">) {
  return (
    <tr
      className={cn("border-b border-border/40 transition-colors hover:bg-muted/15", className)}
      {...rest}
    >
      {children}
    </tr>
  );
}

export function DataTableTh({
  children,
  align = "left",
  className,
}: {
  children: React.ReactNode;
  align?: "left" | "right";
  className?: string;
}) {
  return (
    <th
      className={cn(
        "px-3 py-2 font-medium",
        align === "right" && "text-right",
        className,
      )}
    >
      {children}
    </th>
  );
}

export function DataTableTd({
  children,
  align = "left",
  emphasis,
  muted,
  className,
}: {
  children: React.ReactNode;
  align?: "left" | "right";
  emphasis?: boolean;
  muted?: boolean;
  className?: string;
}) {
  return (
    <td
      className={cn(
        "px-3 py-2",
        align === "right" && "text-right tabular-nums",
        emphasis ? "font-medium text-foreground" : muted ? textRoles.tableCellMuted : textRoles.tableCell,
        className,
      )}
    >
      {children}
    </td>
  );
}

export function DataTableBodyState({
  colSpan,
  variant,
  title,
  description,
}: {
  colSpan: number;
  variant: "loading" | "empty" | "error" | "unavailable";
  title: string;
  description?: string;
}) {
  return (
    <tbody>
      <tr>
        <td colSpan={colSpan} className="p-0">
          {variant === "loading" ? (
            <div className="space-y-2 p-4">
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
            </div>
          ) : variant === "error" ? (
            <ErrorState title={title} description={description} compact />
          ) : variant === "unavailable" ? (
            <EmptyState title={title} description={description} variant="unavailable" compact />
          ) : (
            <EmptyState title={title} description={description} compact />
          )}
        </td>
      </tr>
    </tbody>
  );
}

/** Wrapper when table is loading with no rows yet */
export function DataTableLoading({ rows = 5 }: { rows?: number }) {
  return <LoadingState rows={rows} variant="table" />;
}
