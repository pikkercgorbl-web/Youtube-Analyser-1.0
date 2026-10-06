# Stage 1.20E.3 — Monitoring Videos SQL Pagination + Bounded Enrichment

## A. Old architecture

`GET /api/monitoring/videos` (priority sorts):

1. Route → `list_monitoring_videos()`
2. `build_active_monitoring_enriched()` — entire monitorable active pool
3. Tier assignment + caps + planner snapshots for **all** active videos
4. Python filter (tier, channel, keyword, status)
5. Python sort
6. Python slice `[offset:offset+limit]`

Pagination happened **after** full-universe enrichment. Snapshot load scaled with active pool size (~tens of seconds on remote PostgreSQL).

## B. Why it was slow

- One (or few) large `video_snapshots` reads for planner window over all active IDs
- `get_latest_snapshots_for_videos` over the same ID set
- Per-video planner CPU in Python
- Sort/filter on thousands of rows before returning 50

## C. New read path (default UI)

1. Resolve latest **ok/partial** `MonitoringCycleRun` with a non-empty `monitoring_video_queue` for that `run_id`
2. SQL `COUNT(*)` with same filters (tier, status, channel, keyword/title)
3. SQL `ORDER BY` + `LIMIT/OFFSET` on `monitoring_video_queue` (join `videos`/`channels` for display + search)
4. `get_latest_snapshots_for_videos(page_video_ids)` only (~page size)
5. Response includes `queue_run_id`, `queue_generated_at`, `queue_source`

**Diagnostic:** `?live_planner=true` keeps the legacy full recompute path (explicit, unbounded).

**No queue yet:** `queue_source=unavailable`, empty items — no silent 60s fallback.

## D. Tier / priority persistence

At end of each non–dry-run monitoring cycle (after capture):

1. `build_active_monitoring_enriched()` once (worker path, not UI)
2. Sort by existing `_priority_sort_key`
3. Persist rows to `monitoring_video_queue` with `priority_rank`, tier, checkpoint flags, sort columns, checkpoint hour JSON

Tier meaning and caps unchanged; queue may be a few minutes stale between cycles.

## E. Query count (typical page)

Target **&lt;10** statements:

1. Latest cycle lookup (often cached in app flow)
2. Queue row existence check / count
3. Filtered count
4. Paginated queue + video + channel join
5. Latest snapshots batch for page IDs

Does **not** scale with total pool size on the default path.

## F. Latency

Measure with:

```powershell
python scripts/profile_monitoring_api.py
```

Compare `list_cycle_snapshot.list_page_sec` vs `list_live_planner.list_page_sec`.

Remote target: **&lt;3s** for `page_size=50` on cycle snapshot path (after at least one post-deploy monitoring cycle has populated the queue).

## G. Staleness semantics

- `queue_run_id` = monitoring cycle that materialized the queue
- `queue_generated_at` = that cycle’s `finished_at`
- UI should treat ordering/tier/checkpoint flags as **last cycle snapshot**, not live planner

## H. Fallback behavior

| Condition | Behavior |
|-----------|----------|
| No cycle / failed cycle / empty queue | `queue_source=unavailable`, `total=0` |
| `live_planner=true` | Full enrich (legacy) |
| `sort=breakout_v1` | Unchanged breakout path (still full eligible universe) |

## I. Tests

- `scripts/test_monitoring_sql_pagination.py`
- `scripts/test_monitoring_api.py` (queue seed helper + unavailable/live_planner)

## J. Remaining limitations

- **Breakout list** (`sort=breakout_v1`) still ranks the breakout-eligible universe in Python (by design, separate from priority queue).
- **Video detail** still uses live/single-video enrichment.
- **First deploy** until one monitoring cycle completes: priority list empty until queue is populated. Run the monitoring worker once, or:

```powershell
python scripts/backfill_monitoring_video_queue.py
```

Use `?live_planner=true` only for diagnostics (unbounded latency).
