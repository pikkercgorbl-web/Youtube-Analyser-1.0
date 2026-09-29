# Stage 1.19A — Runtime / Operations Design

**Status:** design only (no implementation in 1.19A).

**Purpose:** Give the operator one place to answer “Is the system alive, accumulating data, and doing useful work?” — **operational observability**, not business quality scoring.

**Related:** monitoring API (`GET /api/monitoring/status`, `/overview`, `/cycles`), keyword performance (1.18), discovery worker (1.15B), `MonitoringCycleRun` (1.14A), `KeywordScanRun` / `KeywordDiscoveryHit` (1.16A).

---

## A. Existing runtime data sources

### Discovery

| Source | Location | What it stores | Gaps |
|--------|----------|----------------|------|
| **Discovery cycle summary (in-memory per run)** | `app/services/discovery_cycle.py` → `DiscoveryCycleSummary` | `run_id`, timestamps, runtime, `selected_keyword_count`, `completed`/`failed` keyword counts, raw/unique/persisted/qualified counts, `cycle_status` (`ok`/`partial`/`failed`/`dry_run`), per-keyword summaries + errors | **Not persisted as a single row**; only logged via `log_discovery_cycle_summary` |
| **Discovery worker singleton state** | `DiscoveryWorkerState` (`discovery_worker_state`) | `status` (`idle`/`running`/`stopped`), lock holder/acquired_at, **`last_cycle_started_at`**, **`last_cycle_finished_at`**, **`last_run_id`**, **`last_cycle_status`**, **`last_error`**, `updated_at` | No volume counters on state row |
| **Keyword scan runs (per keyword × cycle)** | `KeywordScanRun` | `discovery_run_id`, `keyword_id`, `started_at`/`finished_at`, `status`, raw/unique/dup/persisted/qualification counts, `error_summary`, `runtime_seconds` | Reconstruct **last discovery cycle** by aggregating rows where `discovery_run_id = DiscoveryWorkerState.last_run_id` |
| **Discovery hits** | `KeywordDiscoveryHit` | Attribution grain; `discovered_at`, discovery-time metrics | Used for outcome maturity, not cycle health directly |
| **Worker loop** | `discovery_worker_runtime.py` | Default interval **300s**, error backoff **300s**, stale lock **90 min** | No public HTTP status endpoint today (unlike monitoring) |

**Last successful vs failed discovery run:** Infer from `DiscoveryWorkerState.last_cycle_status` + `last_error`. Historical failures before last success require **`KeywordScanRun.status`** or logs — no `discovery_cycle_runs` table.

**Selected keyword count (last cycle):** `COUNT(DISTINCT keyword_id)` on `KeywordScanRun` for `last_run_id`, or sum from aggregated scan runs.

### Monitoring

| Source | Location | What it stores |
|--------|----------|----------------|
| **Cycle summaries (persisted)** | `MonitoringCycleRun` | Full cycle metrics: loaded/eligible counts, tier A/B/C, **due/overdue** at cycle time, selected/deferred captures, inserted/duplicate snapshots, missing/fetch/validation/persistence failures, `error_summary`, `cycle_status`, runtime |
| **Latest / history** | `monitoring_cycle_run_storage.py` | `get_latest_monitoring_cycle_run`, `list_monitoring_cycle_runs(limit, cycle_status)` |
| **Worker singleton state** | `MonitoringWorkerState` | Lock + `status`; **`updated_at`** used as coarse last touch |
| **Worker status (HTTP)** | `GET /api/monitoring/status` → `MonitoringWorkerStatusData` | Labels: `running` / `stopped` / `stale` / `unknown`; stale if lock held > **90 min**; `worker_interval_seconds` = **900** |
| **Live planner counts (expensive)** | `get_monitoring_overview()` | Rebuilds enriched pool + `plan_video_revisits` for **all** regular videos → due/overdue/pending/stopped | **Must not** be default path for operations overview |

### Keyword scheduling

| Field / API | Semantics |
|-------------|-----------|
| `TargetKeyword.next_scan_at` | Next scheduled scan time (UTC) |
| `TargetKeyword.scan_interval_seconds` | Interval after successful scan |
| `TargetKeyword.lifecycle_status` | Includes `archived` (excluded from discovery selection) |
| `is_keyword_due()` / `select_discovery_keywords()` | Due if not archived and (`next_scan_at IS NULL` OR `next_scan_at <= now`) |
| `KeywordScanRun` | Historical proof of scans |
| `GET /api/radar/stats` | `total_keywords`, `checked_today` (last 24h by `last_checked`) — **legacy radar naming**, not full discovery ops |

### Snapshots

| Source | Notes |
|--------|--------|
| `VideoSnapshot` | Append-only; unique on `(video_id, captured_at, source, run_id)`; index `(video_id, captured_at)` |
| **No** `captured_at`-only index | Time-range counts may scan index range on large tables — acceptable with bounded windows; consider migration in 1.19B if slow |
| Latest per video | `get_latest_snapshots_for_videos` (aggregated SQL) — **avoid** in ops overview except `MAX(captured_at)` global |

### Keyword 72h outcomes (evaluation contract)

| Source | Notes |
|--------|--------|
| `KeywordDiscoveryHit` + `VideoSnapshot` | Baseline: **first hit** per `(keyword_id, video_id)` (`MIN(discovered_at)` in window) — same as `keyword_performance_evaluation.py` |
| Horizon | `target = discovery_at + 72h`; valid snapshot if \|Δ\| ≤ **12h** and `views` non-null; no imputation |
| Production today | Validation (1.18C) reported **0** valid 72h outcomes — ops UI must handle this |

### Other workers (context only)

| Worker | State table | Role |
|--------|-------------|------|
| **Explosive channels radar** | `RadarWorkerState` | Separate round-robin keyword path (FR-5), not discovery cycle |
| **Discovery worker** | `DiscoveryWorkerState` | Stage 1.15+ automatic discovery cycles |

Operations v1 focuses on **discovery + monitoring + snapshots + 72h maturity**. Radar worker MAY appear as a footnote (“legacy radar queue”) unless product wants it in 1.19C.

---

## B. Exact due / overdue semantics

### Keywords due (project definition)

**Due for discovery selection** (`select_discovery_keywords`):

- `lifecycle_status != archived`
- AND (`next_scan_at IS NULL` OR `next_scan_at <= now`)

**Ordering** when selecting batch: most overdue first (by seconds past `next_scan_at`), then lifecycle tie-break, then oldest `last_checked`, then `id`.

**UI “keywords due now”:** `COUNT(*)` with the same predicate.

**Due in next hour / 24h (cheap):**

- `next_scan_at > now AND next_scan_at <= now + interval`
- Exclude archived

**Not the same as:** “keyword is performing well” or probation readiness.

### Videos due / overdue (monitoring planner)

**Source of truth:** `snapshot_collection_policy.plan_video_revisits` + `_checkpoint_status` (`app/services/snapshot_collection_policy.py`).

Per checkpoint age `H` (from tier policy checkpoint list):

- **`pending`:** `current_age_hours < H`
- **`due`:** age in `[H, upper_match]` (capture window) and no matching snapshot
- **`overdue`:** age `> upper_match` (past match window) and no matching snapshot
- **`completed`:** matching snapshot exists
- **`expired`:** past checkpoint expiry without capture

**Capture requests** generated only for checkpoints in **`due`** or **`overdue`** (`build_capture_requests`).

**Monitoring list filters** (`monitoring_api_service`): video matches `due`/`overdue` if **any** checkpoint has that status.

**Operations MUST NOT redefine** `upper_match`, expiry, or tier checkpoints — only report planner-aligned counts.

**Two operational readings (document both in API):**

| Field | Meaning | Cost |
|-------|---------|------|
| `last_cycle.due_count` / `overdue_count` | Snapshot at **last monitoring cycle** start/plan | Cheap (read latest `MonitoringCycleRun`) |
| `planner.due_count` / `overdue_count` (optional) | **Live** counts from planner | Expensive (full pool) — **off by default**, same as monitoring overview |

---

## C. Discovery operational model

### Raw facts to expose (no invented thresholds)

| Fact | Primary source |
|------|----------------|
| Last cycle started / finished | `DiscoveryWorkerState.last_cycle_*` |
| Last cycle status | `last_cycle_status` (`ok`/`partial`/`failed`/…) |
| Last run id | `last_run_id` |
| Last error text | `last_error` (truncated in API) |
| Worker lock | `status`, `lock_holder`, `lock_acquired_at`, `updated_at` |
| Expected cadence | `DEFAULT_DISCOVERY_WORKER_INTERVAL_SECONDS` (300) |
| Keywords scanned (last cycle) | Aggregate `KeywordScanRun` for `last_run_id` |
| Raw / unique / persisted (last cycle) | Sum `KeywordScanRun.raw_candidates`, `.unique_candidates`, `.persisted_videos` |
| Failed keyword scans (last cycle) | `KeywordScanRun.status != ok` or cycle `failed_keyword_count` from logs only — **prefer DB:** count scan runs with failed status |
| Keywords due now | SQL on `TargetKeyword` |
| Due next 1h / 24h | SQL on `next_scan_at` |

### Derived operational labels (1.19B — **facts first**, labels optional)

Present **raw ages** (e.g. `seconds_since_last_finished_cycle`) and let UI copy describe concern. Suggested **non-threshold** labels for future policy (1.19D):

| Label | Suggested inputs (no numeric cutoffs in 1.19A) |
|-------|-----------------------------------------------|
| **healthy** | Recent finished cycle with `ok`/`partial`; worker not stopped; due queue not exploding |
| **warning** | Long gap since finish vs interval; `partial`; growing due count |
| **stale** | Lock running but stale (mirror monitoring 90m) OR no finish timestamp |
| **error** | `last_cycle_status == failed` or `last_error` set |
| **unknown** | Missing `DiscoveryWorkerState` row |

**Do not** interpret low discovery volume as poor keyword quality.

### Issue patterns (descriptive, not alarms)

- No cycles recently → show `last_cycle_finished_at` age + worker `status`
- Repeated failures → `last_cycle_status`, `last_error`, recent scan `error_summary` samples
- Due queue growing → time series of `due_now_count` (optional later)

---

## D. Monitoring operational model

### Raw facts (prefer `MonitoringCycleRun`)

| Fact | Field |
|------|--------|
| Last cycle time / status / runtime | Latest row by `started_at` |
| Loaded / eligible videos | `loaded_video_count`, `eligible_video_count` |
| Tier A/B/C | `tier_*_count` (operational capture budget only) |
| Selected / deferred captures | `selected_request_count`, `deferred_request_count` |
| Snapshots inserted / duplicates | `inserted_snapshot_count`, `duplicate_snapshot_count` |
| Failures | `missing_count`, `fetch_failed_count`, `validation_failed_count`, `persistence_failed_count` |
| Errors text | `error_summary` |
| Due / overdue at cycle | `due_count`, `overdue_count` |

### Worker alive vs last activity

| Signal | Meaning |
|--------|---------|
| `GET /api/monitoring/status` | Lock-based **running/stale/stopped** |
| Latest `MonitoringCycleRun.finished_at` | Last **completed work** |
| `MonitoringWorkerState.updated_at` | Last state mutation (weak heartbeat) |

Same distinction as discovery (Section H).

---

## E. Snapshot accumulation model

### Summary metrics (SQL-friendly)

| Metric | Definition |
|--------|------------|
| `latest_snapshot_captured_at` | `MAX(VideoSnapshot.captured_at)` |
| `snapshots_last_1h` | `COUNT(*)` where `captured_at >= now - 1h` |
| `snapshots_last_24h` | `COUNT(*)` where `captured_at >= now - 24h` |
| `unique_videos_snapshotted_24h` | `COUNT(DISTINCT video_id)` same window |
| `snapshots_today` (calendar) | Optional: UTC day boundary — document timezone (**UTC** in backend) |

### Optional 7-day trend

`GROUP BY date(captured_at)` last 7 days — bounded 7 rows, no full history scan of metrics beyond one week.

**Exclude** from v1: per-source breakdown unless `GROUP BY source` is cheap enough in profiling.

---

## F. 72h outcome maturity model

### Observation grain

One **baseline observation** per **`(keyword_id, video_id)`**:

- Baseline hit = earliest `KeywordDiscoveryHit.discovered_at` for that pair (global corpus, not per evaluation window — ops uses **all hits** unless product adds window filter later).
- **Rescans:** later hits for same pair do **not** reset maturity clock (same rule as 1.18A/B).

Optional ops modes (1.19B):

- **`attribution_mode=all_hits`:** count all baselines.
- **`first_discovery`:** count only pairs where this keyword owns first global discovery (same tie-break as evaluation).

Default for maturity dashboard: **`all_hits`** (max transparency); show attribution in API envelope.

### Definitions

Let `maturity_at = discovery_at + 72 hours` (wall clock UTC).

| Bucket | Predicate |
|--------|-----------|
| **attributed_observation_count** | Baselines with non-null `views_at_discovery` (required for outcome attempt) |
| **pending_72h** | `now < maturity_at` |
| **matured_72h** | `now >= maturity_at` |
| **valid_72h_outcome** | Matured AND `match_horizon_outcome` returns non-null (reuse evaluation function) |
| **missing_72h_outcome** | Matured AND NOT valid (includes no snapshot in window, null views at discovery excluded from attempt) |

### Upcoming maturity windows

On **pending** observations only:

| Metric | Predicate |
|--------|-----------|
| `matures_next_6h` | `maturity_at <= now + 6h` AND still pending |
| `matures_next_24h` | `maturity_at <= now + 24h` AND pending |
| `matures_next_48h` | `maturity_at <= now + 48h` AND pending |

### Implementation note (1.19B performance)

**Do not** run full keyword performance evaluation.

**Acceptable batch approach:**

1. One query: distinct `(keyword_id, video_id)` baselines (min `discovered_at`, carry `views_at_discovery`, `video_id`).
2. Compute pending/matured/upcoming in SQL or Python on **O(observations)** rows.
3. For **valid/missing** among **matured only:** load snapshots in **global** `[min(maturity_at)-12h, max(maturity_at)+12h]` window per distinct `video_id` set (reuse 1.18D1 bounded horizon pattern), single batch — **not** per keyword.

**Cheap upper bound when matured count = 0:** skip snapshot load; `valid = 0`, `missing = matured`.

---

## G. Error model

### Discovery

| Class | Source |
|-------|--------|
| Cycle status | `DiscoveryWorkerState.last_cycle_status`, `DiscoveryCycleSummary.cycle_status` |
| Worker exception | `last_error` |
| Per-keyword | `KeywordScanRun.error_summary`, `status` |
| Keyword-level errors in cycle | `DiscoveryKeywordSummary.errors` (logs only unless aggregated from scan runs) |
| InnerTube / client | Embedded in exception strings — **sanitize** in API (truncate, no tokens/keys) |

**Grouped counters (last cycle via `last_run_id`):**

- `keyword_scan_ok_count` / `keyword_scan_failed_count`
- Sum of qualification rejected vs passed (informational, not “errors”)

### Monitoring

From latest / recent `MonitoringCycleRun` rows:

- `missing_count`, `fetch_failed_count`, `validation_failed_count`, `persistence_failed_count`
- `error_summary` (semicolon-joined in storage)

**Recent failures block:** last **N** cycles (default 5) with non-zero failure fields + truncated `error_summary`.

---

## H. Worker-alive limitation / heartbeat recommendation

### Today

| Subsystem | “Process alive?” | “Last useful work?” |
|-----------|------------------|---------------------|
| Monitoring | Lock + stale heuristic (`/api/monitoring/status`) | `MonitoringCycleRun` + `inserted_snapshot_count` |
| Discovery | Lock + `status=running` (no HTTP) | `DiscoveryWorkerState.last_cycle_finished_at` + scan runs |

**DB “last cycle” ≠ guaranteed live process:** crash after commit may leave stale lock until timeout; conversely process may be idle between intervals.

### Recommendation for 1.19D (optional)

**Minimal heartbeat:** extend worker loops to bump `DiscoveryWorkerState.updated_at` / optional `last_heartbeat_at` every interval while idle, and expose mirror of monitoring status for discovery.

**Do not implement in 1.19A/B unless profiling shows operators cannot distinguish idle vs dead.**

Operations UI copy:

- **Last successful activity:** timestamp + counts
- **Worker signal:** running / stale / stopped / unknown (discovery status API in 1.19B)

---

## I. Operations API contract

### Primary endpoint

`GET /api/operations/overview`

**Query params (1.19B):**

| Param | Default | Purpose |
|-------|---------|---------|
| `include_live_monitoring_planner` | `false` | If true, run expensive due/overdue recompute (document cost) |
| `discovery_cycle_history_limit` | `5` | Recent discovery cycles via scan-run aggregation |
| `monitoring_cycle_history_limit` | `5` | Recent `MonitoringCycleRun` rows |
| `outcome_attribution_mode` | `all_hits` | Maturity counts |

**Response sketch:**

```json
{
  "generated_at": "2026-09-28T12:00:00Z",
  "discovery": {
    "worker": {
      "status": "idle",
      "lock_holder": null,
      "lock_acquired_at": null,
      "last_seen_at": "...",
      "expected_interval_seconds": 300,
      "stale_lock_minutes": 90
    },
    "last_cycle": {
      "run_id": "discovery_...",
      "started_at": "...",
      "finished_at": "...",
      "runtime_seconds": 0.0,
      "cycle_status": "ok",
      "selected_keyword_count": 5,
      "completed_keyword_count": 5,
      "failed_keyword_count": 0,
      "raw_candidate_count": 0,
      "unique_video_count": 0,
      "persisted_video_count": 0,
      "error_count": 0,
      "last_error": null
    },
    "keywords_due": {
      "due_now": 3,
      "due_next_1h": 1,
      "due_next_24h": 12,
      "total_non_archived": 89
    },
    "recent_cycles": []
  },
  "monitoring": {
    "worker": { "status": "stale", "lock_holder": "...", "...": "..." },
    "last_cycle": { "...": "MonitoringCycleRun fields" },
    "planner": {
      "source": "last_cycle",
      "due_count": 12,
      "overdue_count": 1
    },
    "recent_cycles": []
  },
  "snapshots": {
    "latest_captured_at": "...",
    "count_last_1h": 0,
    "count_last_24h": 384,
    "unique_videos_last_24h": 120,
    "daily_counts_last_7d": [{ "date": "2026-09-22", "count": 100 }]
  },
  "keyword_outcomes": {
    "attribution_mode": "all_hits",
    "horizon_hours": 72,
    "tolerance_hours": 12,
    "attributed_observation_count": 7900,
    "pending_72h_count": 7800,
    "matured_72h_count": 100,
    "valid_72h_outcome_count": 0,
    "missing_72h_outcome_count": 100,
    "matures_next_6h": 143,
    "matures_next_24h": 500,
    "matures_next_48h": 900
  },
  "errors": {
    "discovery_last_cycle": null,
    "monitoring_recent": []
  }
}
```

### Secondary endpoints (only if overview too heavy)

- `GET /api/operations/discovery` — discovery + keyword due only
- `GET /api/operations/monitoring` — monitoring + snapshots only

Prefer **one** round trip for `/operations` UI.

**Reuse (internal, not chained by frontend):**

- Logic mirrors `get_monitoring_worker_status`, `get_latest_monitoring_cycle_run`, `list_monitoring_cycle_runs`
- New: `get_discovery_worker_status` (symmetric to monitoring)
- New: `aggregate_discovery_cycle(discovery_run_id)`

---

## J. Query / performance plan

### Allowed

- `COUNT` / `COUNT DISTINCT` with indexed filters (`next_scan_at`, `lifecycle_status`, `captured_at` ranges)
- `MAX(captured_at)`, `MAX(started_at)`
- `KeywordScanRun` aggregate `WHERE discovery_run_id = ?`
- `list_monitoring_cycle_runs(limit=N)`
- Maturity: one baseline query + one bounded snapshot query for matured subset
- Discovery due counts: 3–4 indexed counts on `target_keywords`

### Forbidden in operations path

- `load_monitored_video_states` for full pool (unless `include_live_monitoring_planner=true`)
- `get_monitoring_overview()` as default
- `build_global_breakout_map` / breakout ranking
- `evaluate_keywords_batch` / keyword performance list
- Loading all `VideoSnapshot` history
- Per-keyword or per-video HTTP from frontend

### Target (1.19B profiling)

- Overview **< 2s** on production-scale DB (89 keywords, ~8k hits, ~6k videos) with defaults
- Bounded SQL statement count (document in tests, e.g. **< 25** queries)

### Index considerations (1.19B optional migration)

- `VideoSnapshot(captured_at)` or `(captured_at, video_id)` if time-range counts slow
- `KeywordScanRun(discovery_run_id)` already indexed

---

## K. `/operations` UI layout

**Route:** `/operations` (new sidebar entry, e.g. “Операции” / “Runtime”).

### Sections (no single system score)

1. **System summary (facts only)**  
   - Discovery: last finish age, last status, due keywords  
   - Monitoring: last finish age, last inserted snapshots, worker labels  
   - Snapshots: latest capture age, 24h count  
   - 72h: valid / pending / matures next 24h  

2. **Discovery** — table/cards from `discovery.last_cycle` + due counts + worker signal  

3. **Monitoring** — last cycle metrics + tier counts (operational) + due/overdue (label source: last cycle vs live if toggled)  

4. **Snapshot accumulation** — 1h/24h counts, latest timestamp, optional 7-day mini bar  

5. **72h outcome maturity** — bucket counts + upcoming windows + short contract reminder (±12h snapshot)  

6. **Recent cycles** — two compact tables: discovery (from aggregated scan runs), monitoring (from DB rows)  

**Visual rules:** neutral badges; no green/red “good/bad keyword”; no lifecycle action buttons; no keyword score.

**Cross-links (read-only):** Monitoring dashboard, Keyword performance (analytics, not ops).

---

## L. Refresh behavior

| Factor | Recommendation |
|--------|----------------|
| Expected overview cost | ~0.5–2s with defaults (after 1.19B profiling) |
| Default poll interval | **60s** |
| Aggressive poll | 30s only if p95 latency < 1s |
| Tab hidden | Pause polling (`document.visibilityState`) |
| Manual refresh | Button invalidates client cache |

Do not poll keyword performance or monitoring overview from this page.

---

## M. Test plan (1.19B / 1.19C)

### Backend

1. Keyword due count matches `select_discovery_keywords` eligibility SQL  
2. Due next 1h/24h boundary conditions (exclusive/inclusive documented)  
3. Latest monitoring cycle mapping matches `MonitoringCycleRun`  
4. Discovery last cycle aggregate matches fixture scan runs for `run_id`  
5. Snapshot counts in window vs seeded rows  
6. Maturity: pending/matured split at `discovery_at + 72h`  
7. Valid/missing matches `match_horizon_outcome` on fixtures  
8. Rescan second hit does not duplicate baseline (same pair)  
9. Overview does **not** call breakout / keyword performance (mock guard)  
10. SQL query count upper bound with mocks or instrumentation  
11. Empty DB: null-safe zeros, `unknown` worker states  
12. Stale lock representation matches monitoring status logic for discovery mirror  

### Frontend

1. Renders all sections from fixture overview  
2. Distinguishes error vs empty vs “no outcomes yet”  
3. No score widget  
4. Polling interval / pause when hidden  
5. Does not fire monitoring overview or keyword performance APIs  

---

## N. Stage 1.19B implementation plan

1. **`app/services/operations_overview_service.py`** — pure read model assembling sections J  
2. **`get_discovery_worker_status`** — parallel to monitoring status (lock stale rules)  
3. **`aggregate_discovery_cycle(session, discovery_run_id)`** — from `KeywordScanRun`  
4. **`keyword_outcome_maturity_stats(session, attribution_mode)`** — batch baselines + bounded snapshots  
5. **`GET /api/operations/overview`** + Pydantic schemas in `schemas.py`  
6. **Optional migration:** `discovery_cycle_runs` table — **defer** unless aggregation proves fragile; document reconstruction from scan runs  
7. **Benchmark script:** `scripts/benchmark_operations_overview.py`  
8. **Tests:** `scripts/test_operations_overview.py`  

**1.19C:** `/operations` page + poll + recent cycles tables  

**1.19D:** Heartbeat fields, optional alerting thresholds (after operator feedback)

---

## O. Risks / open questions

| Risk | Mitigation |
|------|------------|
| **No persisted discovery cycle row** | Aggregate `KeywordScanRun`; 1.19B may add append-only `DiscoveryCycleRun` if history/reconciliation is painful |
| **Live video due counts vs last cycle** | Default to last cycle; explicit flag for live planner with warning in UI |
| **72h batch cost as matured set grows** | Horizon-bounded snapshot load; nightly pre-aggregate deferred until needed |
| **Radar worker vs discovery worker** | Clarify in UI; two queues share `TargetKeyword` |
| **SQLite vs Postgres** | Date grouping for 7-day trend may differ — use UTC date truncation portable SQL |
| **Operator timezone** | Backend UTC; UI local for display |
| **Error text leakage** | Truncate/sanitize `last_error`, `error_summary` |
| **Threshold policy** | Explicitly out of scope for 1.19A — expose ages and counts only |

### Open questions for product

1. Should operations include **explosive radar worker** state (`RadarWorkerState`) in v1?  
2. Should maturity stats use **all-time** baselines or rolling window (e.g. 90d)? Default proposal: **all-time** with optional `window_days` later.  
3. Is **`discovery_cycle_runs` persistence** worth adding in 1.19B for parity with monitoring?  

---

## Constraints honored (1.19A)

- No changes to discovery, monitoring, lifecycle, breakout, or keyword score  
- No heavy analytics in operations endpoint design  
- No alerts/heartbeat implementation in this stage  
