# Stage 1.20E.2 — Delayed Outcome Capture Scheduler

## A. Why monitoring cannot satisfy discovery-delay outcomes

Monitoring snapshots anchor on **`published_at` + {6,12,24,48,72}h** (video age).

Keyword delayed outcomes anchor on **`KeywordDiscoveryHit.discovered_at + 72h`**.

Stage 1.20E.1 production audit: **0** matured observations had in-window snapshots; nearest captures clustered ~**0.3h after discovery**, ~**72h early** relative to the outcome target.

## B. Two time axes

| Purpose | Axis | Source label |
|---------|------|----------------|
| Monitoring snapshot | Video age (`published_at`) | `monitoring_worker` |
| Outcome snapshot | Discovery delay (`discovered_at + 72h`) | `keyword_outcome_worker` |

Evaluators accept any snapshot with valid `captured_at` + `views` inside ±12h of the outcome target.

## C. Outcome window semantics

Per attributed `(keyword_id, video_id)` baseline (first hit):

- `target_at = discovered_at + 72h`
- Window: `[target_at - 12h, target_at + 12h]`

States at reference time `now`:

| State | Condition |
|-------|-----------|
| **satisfied** | Existing snapshot matches outcome rule |
| **pending** | `now < window_start` |
| **capture_due** | `window_start ≤ now ≤ target_at` |
| **capture_overdue** | `target_at < now ≤ window_end` |
| **expired** | `now > window_end` and not satisfied |

## D. Video-level dedupe

Planning is per observation; **fetch** is per **video_id**:

- Multiple keywords discovering the same video share one YouTube batch slot per cycle when any observation is due/overdue.
- Keyword attribution is unchanged (evaluation still per keyword×video baseline).
- A single capture at `now` only satisfies observations whose windows contain `now`.

## E. Budget

`OutcomeCaptureBudgetPolicy`:

- `max_videos_per_cycle` (default **100**)
- `batch_size` (default **50**, same as revisit executor)

Deferred videos remain **due/overdue** — not expired, not failed evidence.

Monitoring budget is untouched.

## F. Snapshot source

- `source = keyword_outcome_worker`
- `raw_metadata.capture_purpose = keyword_delayed_outcome`
- `raw_metadata.outcome_target_at` ISO timestamp when scheduled

## G. Historical limitations

Observations already **expired** without an in-window snapshot stay **missing** forever. A snapshot taken today cannot backfill a window that closed in the past.

## H. Worker operation

- One-shot: `python scripts/run_outcome_capture_cycle.py` (`--dry-run` for plan-only)
- Loop: `python scripts/run_outcome_capture_worker.py` (default interval **3600s** — justified by ±12h tolerance)
- Singleton lock: `outcome_capture_worker_state`
- Cycle history: `outcome_capture_cycle_runs`
- Operations API: `outcome_capture` block on `/api/operations/overview` (separate from `monitoring`)

## I. Tests

`scripts/test_delayed_outcome_capture.py` — states, dedupe, budget, source, evaluator acceptance, batch ≤50, idempotency, monitoring unchanged.

## J. Expected production ramp-up

After deploy:

- **Historical** matured rows: still missing (`expired`).
- **New** discoveries: first valid outcomes appear ~**72h after discovery** if the worker runs through the capture window.
- Calibration `valid_72h_outcome_count` rises **gradually**, not on deployment day.
