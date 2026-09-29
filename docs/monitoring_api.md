# Monitoring API (Stage 1.14A)

Frontend contract for automatic revisit monitoring. Base path: `/api/monitoring`.

Worker control is **not** exposed via POST start/stop — the monitoring worker runs as a separate OS process (`python scripts/run_monitoring_worker.py`). This API is read-only for worker orchestration.

## Data precedence

| Field | Source |
|-------|--------|
| Views / VPH | Latest `VideoSnapshot`, then `Video.views_count` + age |
| Title / channel title | `Video` + `Channel` |
| Tier | Computed per request from current VPH percentiles and caps (1.13A) |
| Checkpoints / due / overdue | Planner from snapshots + `published_at` + now (1.12B) |
| List baseline fields | Only if already on loaded state (usually null); no per-row baseline compute |
| Detail `channel_baseline` | One bounded 1.12A computation for that video |

---

## GET `/api/monitoring/status`

Worker lock / process coordination view (not a heartbeat stream).

```json
{
  "status": "unknown",
  "lock_holder": null,
  "lock_acquired_at": null,
  "worker_interval_seconds": 900,
  "stale_after_seconds": 5400,
  "last_seen": null,
  "is_lock_stale": false,
  "current_time": "2026-09-15T12:00:00+00:00"
}
```

`status`: `running` | `stopped` | `stale` | `unknown`

- `running`: lock held and not stale
- `stale`: DB says running but lock age exceeds `stale_after_seconds`
- `stopped`: explicit stop flag in `monitoring_worker_state`
- `unknown`: idle / no active lock (typical when worker process is not running)

---

## GET `/api/monitoring/overview`

Live counts from current tier + planner state, plus last persisted cycle summary.

```json
{
  "active_monitored_count": 42,
  "tier_counts": {"A": 5, "B": 12, "C": 25},
  "unmonitored_count": 10,
  "due_count": 3,
  "overdue_count": 1,
  "pending_count": 120,
  "stopped_count": 2,
  "latest_cycle": {
    "run_id": "monitoring_20260915T120000Z_a1b2c3d4",
    "started_at": "2026-09-15T12:00:00+00:00",
    "finished_at": "2026-09-15T12:01:30+00:00",
    "runtime_seconds": 90.1,
    "cycle_status": "ok",
    "loaded_video_count": 100,
    "selected_request_count": 5,
    "inserted_snapshot_count": 5,
    "duplicate_snapshot_count": 0,
    "missing_count": 0,
    "fetch_failed_count": 0,
    "validation_failed_count": 0,
    "persistence_failed_count": 0
  }
}
```

`latest_cycle` is `null` until at least one non–dry-run cycle has completed.

---

## GET `/api/monitoring/videos`

Query parameters:

| Param | Description |
|-------|-------------|
| `tier` | `A`, `B`, or `C` |
| `status` | `due`, `overdue`, `pending`, `active`, `stopped` |
| `channel_id` | Exact channel id |
| `keyword` | Substring match on video title |
| `sort` | `priority` (default), `vph_desc`, `views_desc`, `age_asc`, `latest_snapshot_desc` |
| `limit` | Default 50, max 200 |
| `offset` | Pagination offset |

Default sort (`priority`): overdue → due → tier A → B → C → higher VPH → `video_id`.

```json
{
  "items": [
    {
      "video_id": "abc123",
      "channel_id": "UCxxx",
      "title": "Example",
      "channel_title": "Channel Name",
      "tier": "A",
      "current_views": 12000,
      "current_vph": 500.0,
      "age_hours": 24.0,
      "published_at": "2026-09-14T12:00:00+00:00",
      "latest_snapshot_at": "2026-09-15T11:00:00+00:00",
      "next_checkpoint_hours": 48,
      "monitoring_status": "active",
      "due_checkpoint_hours": [24],
      "overdue_checkpoint_hours": [],
      "baseline_status": null,
      "vph_vs_channel_median": null,
      "content_format": "regular"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

---

## GET `/api/monitoring/videos/{video_id}`

404 if the video id is not in the database.

Includes full checkpoint planner view and optional channel velocity baseline (1.12A).

---

## GET `/api/monitoring/videos/{video_id}/snapshots`

Chronological ascending snapshots for charts.

Query: `limit`, `from`, `to` (capture time bounds).

404 if video id unknown.

---

## GET `/api/monitoring/cycles`

Recent persisted cycle summaries (newest first).

Query: `limit` (default 20), optional `status` (cycle_status filter).

No stack traces in responses; optional `error_summary` is stored server-side only (not exposed on list items in v1).

---

## Errors

- **400** — invalid `tier`, `status`, or `sort`
- **404** — unknown `video_id`
- **500** — unexpected failure (no internal exception text)
