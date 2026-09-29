# Automatic discovery cycle (Stage 1.15A)

## What the cycle does

One callable batch consumes keyword **seeds** from `target_keywords`, runs the existing InnerTube radar discovery path per keyword, collects `RadarCandidate` results, deduplicates videos, upserts `Video`/`Channel` rows for monitoring handoff, optionally registers **ExplosiveChannel** hits via the unchanged FR-5 qualification path, and returns structured metrics.

This stage is **one cycle only** — not a recurring worker (see 1.15B later).

## Keyword DB role

`TargetKeyword` is a **seed queue**, not a permanent boundary on what can be discovered later. Future stages may insert keywords from related queries, channel exploration, or LLM expansion into the same table; `select_discovery_keywords()` will consume them without schema changes to the cycle contract.

Selection policy (`select_discovery_keywords` → `TargetKeywordsService.pick_due_batch`):

- All rows in `target_keywords` are eligible (no separate enabled flag today).
- Default batch size: **5**.
- Order: never-checked first, then oldest `last_checked`, then `id`.

After a successful non–dry-run keyword scan, `last_checked` is updated (existing field).

## Discovery vs qualification

| Outcome | Meaning |
|---------|---------|
| **Discovered** | Format-filtered InnerTube video → candidate / optional `Video` upsert |
| **Qualification passed** | Legacy FR-5 thresholds in `process_radar_videos` |
| **ExplosiveChannel** | Registered only when qualification passes and `register_explosive_channels=True` |

A video **rejected by qualification** can still be persisted to `videos` when it is a valid regular video (monitoring handoff). ExplosiveChannel semantics are unchanged.

## Monitoring handoff

No direct call to the monitoring worker. Handoff is **only** via persisted `Video` rows (medium/regular format). The monitoring worker picks them up on its next cycle.

No `VideoSnapshot` writes in discovery.

## Dry-run semantics

`dry_run=True`:

- Selects keywords and runs InnerTube discovery + qualification logic.
- `register_explosive_channels=False` (no ExplosiveChannel writes/commits from qualification path).
- Does **not** upsert `Video`/`Channel`.
- Does **not** update `last_checked`.
- Session rolled back at end.

## Future hook: keyword expansion

New keyword sources should insert into `target_keywords` (or a future shared queue table). Do not embed expansion logic in the cycle. Optional future fields (`times_scanned`, `last_result_count`) can extend metadata without changing the orchestration entrypoint.

## Commands

```bash
python scripts/run_discovery_cycle.py
python scripts/run_discovery_cycle.py --dry-run
python scripts/run_discovery_cycle.py --batch-size 5
```

## What comes later

- Recurring discovery worker loop (1.15B+)
- Keyword performance scoring / archive
- Related-query and LLM keyword expansion
- Alerts and combined discovery+monitoring workers (explicitly out of scope)
