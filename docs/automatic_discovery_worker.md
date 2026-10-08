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

## Radar enrichment pass (Stage 2.5)

When `RADAR_ENRICHMENT_AFTER_DISCOVERY=1`, each completed discovery iteration runs a **small enrichment pass** in a **separate DB session** (failures do not roll back discovery):

1. `channels.list` — unknown / due subscriber checks (budget: `CHANNEL_SUBSCRIBER_ENRICHMENT_*`)
2. `videos.list` — UNKNOWN and unconfirmed MEDIUM/LONG on channels with known subs ≤100k (`UNKNOWN_FORMAT_ENRICHMENT_DAILY_VIDEO_LIMIT`, `VIDEO_FORMAT_ENRICHMENT_PASS_LIMIT`)

Runs even when no keywords were due or no new videos were persisted. HTTP calls happen **after** commit (no long open transactions).

One-shot (same orchestrator, supports `--dry-run`):

```bash
python scripts/run_radar_enrichment_pass.py
python scripts/run_radar_enrichment_pass.py --dry-run
```

Attention refresh remains a separate one-shot (`scripts/refresh_attention_engine.py`); it reads the DB only.

## Keyword expansion pass (Stage 5)

When `KEYWORD_EXPANSION_AFTER_DISCOVERY=1` (default **off**), after enrichment (if any) the worker runs **one expansion batch** in a **separate DB session** (errors do not roll back discovery):

- Seeds = keywords that **completed discovery successfully** in that cycle (`DiscoveryKeywordSummary.status == ok`).
- Reuses `run_keyword_expansion_orchestrated_batch` (admission, dedup, cooldown, depth, budgets).
- Sources: autocomplete (`suggestion`, `related` via InnerTube) and `channel` (`Video.topic` from persisted hits). **No LLM source** in this pipeline (stage 7 is separate).
- New keywords: `probation` + `source_type` + `parent_keyword_id`; not expanded again in the same orchestration run.

Manual / API (unchanged):

```bash
python scripts/run_keyword_expansion_orchestrator.py --seed-id ID [--dry-run]
python scripts/run_keyword_expansion.py --seed-id ID [--dry-run]
POST /api/keywords/{id}/expand
```

## What it does NOT do

- LLM keyword expansion (planned stage 7; `SOURCE_LLM` not wired to orchestrator)
- Keyword scoring, archive, or deletion
- Automatic lifecycle promotion/demotion
- Monitoring cycles or `VideoSnapshot` writes (monitoring worker still separate)
- Alerts or ranking changes

## Architecture

```
TargetKeyword (seeds)
      ↓
Discovery Worker → videos
      ↓ (optional enrichment pass)
channels.list + videos.list → eligibility metadata
      ↓
Monitoring Worker → video_snapshots → dashboard
      ↓
Attention refresh (snapshot) → /api/attention
```
