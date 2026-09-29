# Automatic monitoring worker (Stage 1.13C)

## What this worker does

The monitoring worker repeatedly loads **already known** regular videos from the database, assigns monitoring tiers, plans snapshot revisits from persisted history, allocates API budget, and executes approved capture requests. Each successful fetch appends a `VideoSnapshot` row.

Discovery (keyword radar) is **not** part of this worker.

## What state survives restart

- `VideoSnapshot` rows (append-only capture history)
- `Video` and channel metadata in the database
- `monitoring_worker_state` singleton lock row (process coordination only)

There is no in-memory schedule to restore.

## Why no in-memory schedule is required

Checkpoint status (pending, due, overdue, completed, expired) is recomputed on every cycle from:

1. `published_at` and current time
2. Existing snapshots matched to tier-specific checkpoint windows (Stage 1.12B)

After a crash or deploy, the next cycle picks up due and overdue work automatically.

## Why cycles do not overlap

A single worker process runs **one cycle at a time**: run cycle → finish → sleep → next cycle. If a cycle takes longer than the interval, the next cycle starts only after the previous one completes (no wall-clock overlap scheduling).

## Monitored video source

Videos are loaded from the `videos` table:

- Excludes `SHORT` and `LIVE` formats at query time
- Input precedence: latest `VideoSnapshot` (views/VPH) → `Video` entity fields

Stage 1.10C frozen cohort artifacts are never read by this worker.

## What this worker does NOT do

- Keyword / radar discovery
- Ranking, alerts, or ML scoring
- Stage 1.10C experiment refresh or T24/T48/T72 artifact writes
- Celery, Redis, or distributed queues

## Configuration

| Setting | Default | Meaning |
|--------|---------|---------|
| `monitoring_worker_interval_seconds` | 900 (15 min) | Sleep between completed cycles |
| Error backoff after fatal cycle exception | 300 (5 min) | Worker loop retry delay |

Tier thresholds, checkpoint hours, and API budget caps remain defined in Stage 1.13A / 1.12B policies (unchanged).

## How to run

One-shot cycle (debug or smoke test):

```bash
python scripts/run_monitoring_cycle.py
```

Dry-run (plan + budget only, no YouTube, no persistence):

```bash
python scripts/run_monitoring_cycle.py --dry-run
```

Continuous worker (explicit process; not auto-started with the web app):

```bash
python scripts/run_monitoring_worker.py
```

Optional flags:

```bash
python scripts/run_monitoring_worker.py --interval-seconds 900 --error-backoff-seconds 300
```

## Singleton lock

Only one monitoring worker should hold the DB lock (`monitoring_worker_state`, row id 1). A second process exits if the lock is held and not stale. Stale locks (default 90 minutes) can be taken over after restart. The lock is released on graceful shutdown (SIGINT/SIGTERM).

## Run identity

Each cycle gets `run_id` like `monitoring_20260915T120000Z_a1b2c3d4`. Capture requests use deterministic child ids: `{run_id}:{video_id}:cp{checkpoint}` for provenance and idempotent persistence.
