# Automatic discovery worker (Stage 1.15B)

## What it does

Continuously acquires a process singleton lock, runs `run_discovery_cycle()` for a bounded keyword batch, sleeps for a configured interval, and repeats until shutdown. Keyword rotation uses existing `TargetKeyword.last_checked` + `select_discovery_keywords()` — no in-memory scheduler.

## How keyword rotation survives restart

After each successful keyword scan (non–dry-run), `last_checked` is updated (Stage 1.15A). On restart the worker picks the next due seeds from the DB automatically.

## Why discovery and monitoring are separate workers

| Worker | Responsibility |
|--------|----------------|
| Discovery | Acquire new videos via InnerTube keyword seeds → `videos` |
| Monitoring | Temporal observation → `video_snapshots` |

Different failure domains, intervals, and locks. Neither worker calls the other.

## How to run

One-shot cycle:

```bash
python scripts/run_discovery_cycle.py
python scripts/run_discovery_cycle.py --dry-run
```

Continuous discovery:

```bash
python scripts/run_discovery_worker.py
python scripts/run_discovery_worker.py --interval-seconds 300 --batch-size 5
```

Monitoring (separate process):

```bash
python scripts/run_monitoring_worker.py
```

Dry-run is **only** supported on the one-shot CLI. The continuous worker always persists normally (no `--dry-run`).

## Locking

- Table: `discovery_worker_state` (singleton row).
- Second process fails safely if lock is held.
- Stale lock takeover default: **90 minutes** (same pattern as monitoring worker).

## What it does NOT do

- LLM or keyword expansion
- Keyword scoring, archive, or deletion
- Related-query expansion
- Monitoring cycles or `VideoSnapshot` writes
- Alerts or ranking changes

## Architecture

```
TargetKeyword (seeds)
      ↓
Discovery Worker → videos
      ↓
Monitoring Worker → video_snapshots → dashboard
```
