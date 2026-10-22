/** Layout constants for operator pages (desktop-first). */

export const pageLayout = {
  /** Main content padding */
  padding: "p-5 md:p-8 lg:p-10 w-full max-w-[1600px] mx-auto",
  /** Vertical rhythm between major sections */
  sectionGap: "space-y-8",
  /** Inner section spacing */
  blockGap: "space-y-4",
  /** Max readable width for summary strips */
  summaryMaxWidth: "max-w-4xl",
  /** Operator table minimum width before horizontal scroll */
  tableMinWidth: "min-w-[720px]",
  /** Two-column breakpoint for health panels */
  twoCol: "grid gap-4 lg:grid-cols-2",
  /** Metric grid inside one panel (not one card per metric) */
  metricGrid: "grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3",
} as const;

export const surfaces = {
  section: "rounded-xl border border-border/70 bg-surface-raised/80",
  sectionMuted: "rounded-xl border border-border/60 bg-card/40",
  sunken: "rounded-lg border border-border/50 bg-surface-sunken/50",
} as const;
