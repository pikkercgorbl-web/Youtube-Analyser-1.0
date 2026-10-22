# Stage 1.23C.1A — Corrected simulation notes (1.23C.0C follow-up)

## Right-censoring fix

Earlier counterfactual sim (`audit_1_23c0c_priority_feasibility_readonly.py`) replayed **226 cycles through 2026-10-10** while many DI appearance videos had **outcome window_end after the last cycle** (windows open Oct 11–14 UTC). Those videos were counted as **priority_missed** although they were **not yet observable**.

**Correct rule:** evaluate coverage only when `window_end <= last_cycle_started_at` (fully observable windows).

On restore_check (2026-10-12 ref): **4** appearance videos had closed windows without outcome; **163** still pending (not censorable as missed in Oct-10 replay).

## Invalid timeline (-0.64h discovery → Attention)

One appearance video had `source_computed_at` **before** earliest `discovered_at` (clock skew or hit reorder). Classify as **INVALID_TIMELINE** for analytics; **do not** use for priority eligibility timing. Planner uses discovery window + due state, not Attention delta.

## Priority join dedup

`SELECT DISTINCT video_id FROM daily_intelligence_run_winner_appearances` — one candidate per video_id per cycle regardless of multiple runs/report_dates.

## EXPLAIN (restore_check, read-only)

`Index Scan` on `daily_intelligence_run_winner_appearances` for distinct video_id; btree on `video_id` (`ix_di_run_winner_video_computed`). Single query per planner cycle when flag ON — no N+1.
