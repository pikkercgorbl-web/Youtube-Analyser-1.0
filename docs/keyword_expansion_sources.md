# Keyword expansion sources (Stage 1.16C)

## Why expansion exists

`TargetKeyword` is a **seed queue**, not a permanent search boundary. Expansion proposes new queries from existing seeds while keeping lifecycle, scheduling, and performance metrics unified.

## Sources (non-LLM)

| Source | Signal | Notes |
|--------|--------|-------|
| **suggestion** | InnerTube `get_search_suggestions` (+ optional trailing-space query) | Reliable autocomplete text |
| **related** | `get_related_search_suggestions` (filtered autocomplete) | No refinement chips in current parsers |
| **channel** | Distinct `Video.topic` from `KeywordDiscoveryHit` for the seed | Empty when no persisted topics |

## Why new keywords start in probation

Expansion does not prove breakout value. New rows use `lifecycle_status=probation`, immediate `next_scan_at`, and provenance via `source_type` + `parent_keyword_id` + `KeywordExpansionEvent`.

## Caps and cooldown

Defaults: **20** raw candidates/source/seed, **10** new/seed/run, **50** new/run, **7-day** cooldown per seed/source (from expansion events). Prevents combinatorial explosion; new keywords are **not** expanded again in the same run.

## Why no LLM yet

We need measured non-LLM yield and T72 validation before automated quality or LLM expansion.

## Future

T72 outcomes → lifecycle automation → LLM / related-query workers → optional periodic expansion orchestration (not wired to discovery worker in 1.16C).

## Commands

```bash
python scripts/run_keyword_expansion.py --seed-id 1
python scripts/run_keyword_expansion.py --seed-ids 1,2,3 --dry-run
POST /api/keywords/{id}/expand
```
