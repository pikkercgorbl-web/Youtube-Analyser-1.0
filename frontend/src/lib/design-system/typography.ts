/** Typography roles — compose with cn() (Stage 1.21B). */

export const textRoles = {
  pageTitle: "text-2xl font-semibold tracking-tight text-foreground",
  pageLead: "mt-1 max-w-3xl text-sm text-muted-foreground leading-relaxed",
  sectionTitle: "text-base font-medium text-foreground",
  sectionDescription: "text-xs text-muted-foreground leading-relaxed",
  /** Level 1 human summary */
  summaryHeadline: "text-base font-medium text-foreground leading-snug",
  summarySupport: "text-sm text-muted-foreground leading-relaxed",
  /** Level 2 metrics */
  metricValue: "text-lg font-semibold tabular-nums text-foreground",
  metricValueSm: "text-base font-semibold tabular-nums text-foreground",
  metricLabel: "text-xs text-muted-foreground",
  /** Level 3 */
  tableHeader: "text-xs font-medium text-muted-foreground",
  tableCell: "text-sm text-foreground",
  tableCellMuted: "text-sm text-muted-foreground",
  metadata: "text-xs text-muted-foreground tabular-nums",
  helper: "text-xs text-muted-foreground leading-relaxed",
  code: "font-mono text-xs text-muted-foreground",
} as const;

export const hierarchy = {
  l1: "space-y-1",
  l2: "space-y-3",
  l3: "space-y-2 opacity-95",
} as const;
