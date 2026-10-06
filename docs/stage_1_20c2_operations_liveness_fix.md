# Stage 1.20C.2 — Operations liveness fix

## A. Root cause

Operations and Monitoring UI treated **`lock_acquired_at`** as worker freshness. Long-running singleton workers keep the same lock timestamp while cycles continue, producing false **`stale_activity`** / **«давно не запускался»** after ~90 minutes.

## B. Lock vs activity

| Concept | Fields | Use |
|---------|--------|-----|
| **Lock ownership** | `lock_acquired_at`, `lock_holder`, `status` | Singleton acquire, foreign lock block, stale **lock** recovery |
| **Operational liveness** | `last_cycle_finished_at`, `MonitoringCycleRun.finished_at`, `updated_at` heartbeat | Operations badges, monitoring worker `running`/`stale` |

## C. Discovery activity rule

`classify_worker_activity()` in `worker_activity_policy.py`:

1. Latest cycle failed or `last_error` → **`error`**
2. Worker not `running` → **`unknown`** (e.g. stopped)
3. Else age since `last_cycle_finished_at` or `updated_at` ≤ threshold → **`active_recently`**
4. Else → **`stale_activity`**

**Not** using `lock_acquired_at`.

## D. Monitoring activity rule

Same classifier with:

- `last_activity` = max(`latest MonitoringCycleRun.finished_at`, `MonitoringWorkerState.updated_at`)
- `expected_running` = DB status `running`

`get_monitoring_worker_status()` maps **`stale_activity`/`error`** → label **`stale`**, recent activity → **`running`**.

## E. Stale thresholds

```text
stale_activity_threshold = max(600s, expected_interval_seconds × 4)
```

- Discovery default interval **300s** → activity stale after **1200s** (~20 min without cycle/heartbeat).
- Monitoring default interval **900s** → **3600s** (~1 h).

Lock recovery still uses **`DEFAULT_STALE_LOCK_MINUTES = 90`** on **`lock_acquired_at`** (unchanged).

## F. Heartbeat semantics

- **Discovery:** `record_discovery_worker_cycle()` already sets `updated_at` each cycle.
- **Monitoring:** `record_monitoring_worker_heartbeat()` after each cycle attempt (success or unexpected failure); owner session commits in `monitoring_worker_runtime`.

## G. Lock semantics preserved

`acquire_*_worker_lock()` still blocks foreign holders while lock age ≤ 90 minutes; stale foreign locks remain recoverable. **`is_lock_stale`** on monitoring API reflects **lock age**, separate from activity **`status`**.

## H. Tests

`scripts/test_operations_liveness.py` — old lock + recent cycle, genuinely stale activity, failed cycle, lock recovery.

## I. UI behavior

Backend `activity_state` drives Operations summaries. Monitoring page worker badge uses the same activity-based `get_monitoring_worker_status()`. Copy updated to refer to **cycle/heartbeat**, not lock age.
