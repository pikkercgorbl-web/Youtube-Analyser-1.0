# Fix 3B — Discovery queue & Monitoring missing (report)

Snapshot: `2026-10-13T10:35:45Z` (see `artifacts/audit_3b_discovery_monitoring_report.json`).

## Part A — Discovery queue vs policy

### A.1 Required scan frequency (current policy)

From `KeywordSchedulingPolicy` (`app/services/keyword_scheduling_policy.py`):

| Lifecycle | Interval |
|-----------|----------|
| probation | 6 h |
| active | 24 h |
| weak | 72 h |
| failed scan retry | 2 h |
| archived | no schedule |

Seed/manual/suggestion share the same lifecycle intervals; source does not change the interval.

### A.2 Measured overdue (`now − next_scan_at`) for due keywords

| Source \| lifecycle | Due count | p50 overdue | p90 | max |
|---------------------|-----------|-------------|-----|-----|
| seed \| active | 53 | 11.75 h | 14.32 h | **39.5 h** |
| suggestion \| probation | 1592 | **26.8 h** | **46.8 h** | 51.5 h |
| channel \| probation | 4 | 26.3 h | 45.3 h | 47.4 h |
| related \| probation | 10 | 34.8 h | 42.8 h | 48.2 h |

Probation keys are overdue by ~1–2× the **6 h** target (median ~27 h ≈ 4.5 missed cycles). Active seeds in the due set are overdue ~0.5× the **24 h** target but examples reach **~40 h**.

### A.3 Inflow vs scans (history limits)

| Window | New non-archived keywords | Notes |
|--------|---------------------------|--------|
| 24 h | **0** (by `created_at`) | Cannot reconstruct “became due” moment from DB alone |
| 72 h | 8 × suggestion/probation | |

Scanned (distinct `keyword_id` in `keyword_scan_runs`):

| Window | suggestion/probation | seed/active |
|--------|----------------------|-------------|
| 24 h | 694 | 27 |
| 72 h | 1767 | 80 |

728 unique keywords / 24 h (3A) aligns with ~694 probation + other sources. Over 72 h, probation scans (1767) exceed the ~1592 probation pool size → most probation keys got **about one scan in 72 h**, not one every 6 h.

### A.4 Selection order & examples

Ordering: most overdue first; tie-break **source** (seed before suggestion, Fix 3B) then lifecycle (probation before active).

Despite seed tie-break, suggestion/probation dominates the due set (1592 vs 53 seeds). With **batch_size=5** and **interval=300 s** (`discovery_worker_runtime`), theoretical max ≈ **1 440 keyword-slots/day** (5 × 12/h × 24), vs probation **steady-state demand** ≈ `N_probation × (24/6)` ≈ **6 400 slots/day** for ~1600 probation keys.

Example overdue **seed/active** (still waiting):

- `127` «странная история» — 39.5 h overdue  
- `128` «забытые истории» — 39.4 h  
- `129` «история России» — 39.4 h  

### A.5 Capacity conclusion (no interval/batch changes in 3B)

**Current throughput cannot sustain 6 h probation intervals at this pool size.** The worker is active, but the due count reflects **backlog**, not a stopped worker.

**Options requiring separate approval** (not applied in 3B):

1. **Raise effective throughput** — higher batch size and/or shorter worker interval (quantify: need ~4× current unique/day to approach 6 h for full probation pool).
2. **Admission / creation control** — slow suggestion→probation inflow when `due_now / not_archived` exceeds a threshold.
3. **Relax probation interval** — e.g. 12–24 h until backlog clears (changes product semantics).
4. **Selection weighting** — Fix 3B added seed source tie-break after overdue; further weighting (cap suggestion share per cycle) needs policy sign-off.

---

## Part B — Monitoring missing

### B.1 Last 10 missing `video_id`s (persisted)

Table `monitoring_capture_outcomes` — **all 10 latest rows are the same video**:

`YXodhWM0RiI`, checkpoint **24 h**, outcome `missing`, ~every **15 min** (monitoring cycle cadence).

Top missing counts (72 h): `unmayvJb-18`, `ssYuuEWAFSA`, `FYQn6PsdRaE` (48 each), `YXodhWM0RiI` (40).  
Same `missing_count=1` per cycle does **not** imply the same ID across history; here recent cycles **do** share one ID.

### B.2 Retry behavior (code + test)

- `revisit_executor`: API batch without item → `missing`, **no snapshot persisted**.
- `snapshot_collection_policy`: checkpoint completes only on successful capture (`snapshot_fulfills_checkpoint_late` / age-matched snapshot). **Missing does not clear the checkpoint.**
- Next cycle: `plan_video_revisits` → same checkpoint still **due/overdue** → same `video_id` selected again.

Verified: `scripts/test_monitoring_missing_retry_3b.py`.

**Proposed rule (design only, not implemented):**

- After **K** consecutive `missing` outcomes for `(video_id, checkpoint)` within **T** hours, mark checkpoint **terminal_missing** (UI: “нет в API”) and stop selecting until manual refresh or **long** cooldown (e.g. 7 d) for “video may appear later” cases.
- Keep **fetch_failed** on short retry (2 h style) to separate transient API errors.
- Requires product decision on K/T and on saved-video manual refresh path.

### B.3 Diagnostics

`monitoring_capture_outcomes` already stores `monitoring_run_id`, `video_id`, `checkpoint_age_hours`, `outcome`, `attempted_at` (`monitoring_capture_outcome_storage.py`). No full API body or secrets. **No new persistence added in 3B** — audit proves repeat selection for `YXodhWM0RiI`.

---

## Part C — UI / API (implemented)

### Keywords (`/keywords`)

- `GET /api/keywords/pool-summary` — due counts, **unique keywords scanned last 24 h**, policy intervals.
- Dashboard shows queue context: due = **waiting for scan**, plus 24 h throughput; **no ETA**.

### Monitoring (`/monitoring`)

- Additive fields on cycle responses: `execution_error_count`, `partial_primary_cause`, `cycle_status_detail`.
- UI columns: **«Нет в API»** (`missing`) vs **«Ошибки захвата»** (fetch/validation/persistence).
- Partial badge retains **«Частично»** with explanatory detail when errors=0 but missing>0.

---

## Tests & checks

| Check | Location |
|-------|----------|
| Seed tie-break / large probation queue | `scripts/test_discovery_keyword_selection_3b.py` |
| Partial presentation | `scripts/test_monitoring_cycle_presentation_3b.py` |
| Missing retry logic | `scripts/test_monitoring_missing_retry_3b.py` |
| Monitoring UI | `frontend/src/lib/monitoring-cycle-presentation.test.ts`, `monitoring-dashboard.test.tsx` |
| Keywords queue context | `keyword-pool-dashboard.test.tsx` |
| Read-only audit | `artifacts/audit_3b_discovery_monitoring_readonly.py` → JSON |

Browser smoke: `frontend/scripts/fix-3b-keywords-monitoring-smoke.cjs` — see `artifacts/fix_3b_browser_acceptance.md`. Acceptance **build** updated; restart port **3100** then run smoke for screenshots.

---

## What changed in 3B (summary)

- Discovery selection: **seed-before-suggestion** tie-break when overdue is similar.
- Keyword pool summary API + honest due/throughput copy on `/keywords`.
- Monitoring cycle **presentation** layer + UI split missing vs execution errors.
- Tests and audit script; **no** worker interval, batch size, schedule, budget, or checkpoint manual edits.

**Stop point:** Fix 3B complete; capacity and missing cooldown remain **decisions for follow-up**, not auto-applied config.
