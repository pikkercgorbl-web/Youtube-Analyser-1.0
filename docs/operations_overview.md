# Operations overview (Stage 1.19B)

Operational observability for discovery, monitoring, snapshots, and 72h outcome maturity. **Not** a system score, keyword quality score, or breakout analytics.

Design: [stage_1_19a_operations_design.md](stage_1_19a_operations_design.md)

## Endpoint

`GET /api/operations/overview`

| Parameter | Default | Description |
|-----------|---------|-------------|
| `include_live_monitoring_planner` | `false` | When true, runs expensive live due/overdue planner (same cost as monitoring overview). |
| `discovery_history_limit` | `10` | Recent discovery cycles reconstructed from `KeywordScanRun` (max 50). |
| `monitoring_history_limit` | `10` | Recent `MonitoringCycleRun` rows (max 50). |
| `outcome_attribution_mode` | `all_hits` | `all_hits` or `first_discovery` for 72h maturity baselines. |

## Keyword due semantics

Non-archived keywords only.

| Bucket | Rule |
|--------|------|
| **due_now** | `next_scan_at IS NULL` OR `next_scan_at <= now` |
| **due_next_1h** | `now < next_scan_at <= now + 1h` |
| **due_next_24h** | `now < next_scan_at <= now + 24h` (**cumulative**, includes the 1h window) |

`due_now` keywords are not counted in the upcoming buckets.

## 72h maturity semantics

Same baseline as keyword performance (Stage 1.18B):

- One observation per `(keyword_id, video_id)` using **earliest** hit (rescans do not duplicate).
- `maturity_at = discovery_at + 72h`
- **Pending:** `now < maturity_at`
- **Matured:** `now >= maturity_at`
- **Valid:** matured + horizon snapshot within ±12h with non-null views
- **Missing:** matured but no valid outcome

**Upcoming** counts apply to **pending** observations only (`maturity_at` within next 6h / 24h / 48h).

All-time totals (not rolling window).

## Worker activity vs liveness

Response separates:

- **last_activity_at** / last cycle timestamps (last useful work)
- **lock_status** / **activity_state** (coarse signal, not proof of live process)

True heartbeat is **Stage 1.19D** — not implemented in 1.19B.

## Discovery cycles

No `DiscoveryCycleRun` table. Cycles are **reconstructed** by grouping `KeywordScanRun` on `discovery_run_id`. Worker state fills last status/error when present.

## Performance expectations

Target: default overview **&lt; ~2s** on a low-latency DB when query round-trips are consolidated (Stage **1.19B2**: ~**9 SQL** statements default; median ~**2s** on production-like remote Postgres with ~8.4k hits). Stage **1.19B1** added set-based maturity (1 query); **1.19B2** batches keyword due, snapshots, discovery cycles, and monitoring history.

**1.19B1 maturity path:** one SQL statement per attribution mode — `ROW_NUMBER` baseline dedupe, aggregate pending/matured/upcoming, horizon snapshot match via join + nearest-rank within ±12h. Legacy Python path kept as `compute_keyword_outcome_maturity_legacy` for parity tests only.

Benchmark: `python scripts/benchmark_operations_overview.py`  
Profile (legacy phases + EXPLAIN): `python scripts/profile_operations_maturity.py`  
Parity tests: `python scripts/test_operations_maturity_performance_1_19b1.py`

**Baseline tie-break (`all_hits`):** same `discovered_at` → lowest hit `id`.  
**First discovery tie:** same `discovered_at` → lowest `keyword_id`.

Default path avoids:

- Breakout ranking
- Keyword performance evaluation
- Live monitoring planner

Benchmark: `python scripts/benchmark_operations_overview.py`

Tests: `python scripts/test_operations_overview.py`

## Frontend

Stage **1.19C:** `/operations` dashboard consuming this endpoint.
