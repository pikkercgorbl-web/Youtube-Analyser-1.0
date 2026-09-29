# Design system — Stage 1.21B

Reference for operator/analyst UI. Canonical UX audit: [stage_1_21a_product_ux_audit.md](./stage_1_21a_product_ux_audit.md).

## Existing visual audit (1.21B Task 1)

Before 1.21B, the frontend already used **shadcn/ui** (`Badge`, `Button`, `Card`, `Select`, `Skeleton`, `StateMessage`) on a **dark zinc** theme in `globals.css` (`--background`, `--card`, `--muted`, `--destructive`). Gaps found:

| Area | Issue | Direction |
|------|--------|-----------|
| Colors | Ad-hoc Tailwind (`amber-500`, `sky-500`) on tier badges; no semantic tokens for lifecycle/evidence/checkpoint | Semantic CSS vars + Tailwind maps |
| Typography | Page titles ad hoc (`text-2xl font-semibold`); tables all `text-sm` with equal weight | `textRoles` + L1/L2/L3 in `typography.ts` |
| Spacing | Mixed `space-y-3/4/6`, duplicate stat **Card** grids | `pageLayout`, `MetricGroup` (no card-per-number) |
| Badges | One generic outline badge; English enums (`due`, `probation`) in UI | Family-specific badges + `labels.ts` |
| Tables | Dense, all columns equal emphasis; raw API fields visible | `DataTable*` primitives, progressive disclosure |
| States | Loading/error copy inconsistent; empty vs zero blurred | `states.tsx` variants |
| Tooltips | Inline `title=` and one-off help strings | `InfoTooltip` + `METRIC_TOOLTIPS` |

Pages were **not** redesigned in 1.21B; only thin compatibility (monitoring checkpoint badge, KP lifecycle labels).

## Visual direction

Dark analytical workspace: restrained contrast, soft raised surfaces (`surface-raised`), neutral tables, **color reserved for state and attention** — not decoration. No card-per-metric layouts. Desktop-first (≥1280px comfortable).

## Tokens

CSS variables in `frontend/src/app/globals.css`:

- Surfaces: `--surface-raised`, `--surface-sunken`
- Status: `--status-ok|warn|error|unknown`
- Lifecycle, evidence, checkpoint families (see globals.css)

Tailwind: `status.*`, `lifecycle.*`, `evidence.*`, `checkpoint.*`, `surface.*`

## Typography roles

`frontend/src/lib/design-system/typography.ts` — `textRoles.pageTitle`, `summaryHeadline`, `metricValue`, `tableHeader`, `code`, etc.

## Hierarchy

| Level | Role | Treatment |
|-------|------|-----------|
| L1 | Human summary | `SummaryStrip`, `summaryHeadline` |
| L2 | Operational metrics | `MetricGroup`, `Metric` |
| L3 | Technical | `DataTable*`, `Disclosure`, `code` |

## Badges

`frontend/src/components/design-system/status-badges.tsx`

- `SystemStatusBadge` — worker / activity
- `LifecycleBadge` — keyword queue
- `EvidenceBadge` — data readiness
- `CheckpointBadge` / `CheckpointBadgeFromVideo`
- `CycleStatusBadge` — cycle result (RU label, optional raw in title)

Labels: `frontend/src/lib/design-system/labels.ts`

## Components

| Component | Path |
|-----------|------|
| SummaryStrip | `summary-strip.tsx` |
| Metric / MetricGroup | `metric.tsx` |
| InfoTooltip / HelpText | `info-tooltip.tsx` |
| Disclosure / ExpandableTableRow | `disclosure.tsx` |
| DataTableShell + cells | `data-table.tsx` |
| Loading / Empty / Error / Stale / Zero | `states.tsx` |
| FreshnessTime | `freshness.tsx` |
| PageShell / PageHeader / SectionPanel | `page-shell.tsx` |
| SidebarNavGroup (1.21F) | `sidebar-nav.tsx` |

## Layout

`frontend/src/lib/design-system/layout.ts` — `pageLayout.padding`, `sectionGap`, `metricGrid`, `surfaces.section`.

## Sample usage

```tsx
import { PageShell, PageHeader, SummaryStrip, MetricGroup, Metric } from "@/components/design-system";
import { LifecycleBadge } from "@/components/design-system/status-badges";
import { METRIC_TOOLTIPS } from "@/lib/design-system/labels";

<PageShell>
  <PageHeader title="Операции" lead="…" />
  <SummaryStrip tone="warning" lines={[{ text: "…", emphasis: true }]} onDetails={() => {}} />
  <MetricGroup title="Discovery">
    <Metric label="Ждут сканирования" value={89} tooltip={METRIC_TOOLTIPS.dueKeyword} />
  </MetricGroup>
</PageShell>
```

## Tests

`frontend/src/components/design-system/design-system.test.tsx`

## Migration (1.21C–F)

1. Replace ad-hoc stat cards with `SummaryStrip` + `MetricGroup`.
2. Swap `monitoring-badges` imports to `status-badges` (re-export remains).
3. Use `DataTableShell` for cycle tables; move Raw/Run ID columns behind `Disclosure`.
4. Replace English filter labels when touching monitoring page.
5. Apply `SidebarNavGroup` in 1.21F without route changes.
