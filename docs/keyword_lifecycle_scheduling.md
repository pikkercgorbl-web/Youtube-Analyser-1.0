# Keyword lifecycle and scheduling (Stage 1.16B)

## Why lifecycle exists

Discovery capacity is finite. Keywords differ in maturity and priority; lifecycle + `next_scan_at` control **how often** each seed is scanned without implying validated breakout quality.

## Lifecycle meanings

| Status | Cadence (default) | Role |
|--------|-------------------|------|
| **probation** | 6h | New/unproven seeds (future expansion default) |
| **active** | 24h | Normal production seeds |
| **weak** | 72h | Low priority; still rotated when overdue |
| **archived** | none | Not scheduled; row retained for history |

## Why weak/archive are not automatic yet

T0→T72 outcome validation on the frozen Stage 1.10C cohort is still in progress. No automatic demotion from duplicate rate, qualification pass rate, or Tier A counts.

Informational only: after **3** successful scans, probation keywords expose `scheduling_hint=probation_ready_for_review` (no auto promotion).

## Scheduling

- **`next_scan_at`** is the primary due signal when set.
- Successful scan: `next_scan_at = finished_at + interval(lifecycle)`.
- Failed scan: `next_scan_at = finished_at + failed_scan_retry_hours` (default 2h).
- Lifecycle change via `set_keyword_lifecycle()` recomputes interval and `next_scan_at` (archived → `NULL`; reactivation → immediate due).

## Fairness

Selector ordering:

1. **Overdue seconds** (desc) — a weak keyword 5 days overdue beats an active keyword due 2 minutes ago.
2. Lifecycle tie-break: probation → active → weak.
3. Oldest `last_checked`.
4. `id`.

## Failure retries

Failures do not advance `last_checked`. Shorter retry delay avoids stalling the queue without changing lifecycle status.

## Future

Validated T72 outcomes → policy-driven lifecycle automation → keyword expansion / LLM sources feeding probation rows.
