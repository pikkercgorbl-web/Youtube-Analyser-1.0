# Keyword performance metrics (Stage 1.16A)

## Why this exists

Keyword seeds must evolve from **measured evidence**, not assumptions. This stage adds durable instrumentation so we can inspect scan yield, uniqueness, duplicates, qualification mix, and monitoring coverage before any lifecycle or scoring policy.

## What is measured

| Area | Source |
|------|--------|
| Scan activity | `KeywordScanRun` (includes zero-result and failed scans) |
| Discovery yield | `KeywordDiscoveryHit` per `(keyword_id, video_id, discovery_run_id)` |
| Uniqueness / duplicates | Hit flags + aggregates |
| Qualification | Discovery-time `qualification_state` on hits |
| Monitoring handoff | `persisted_for_monitoring` on hits |
| Snapshot coverage | `VideoSnapshot.age_hours` for attributed videos |

Operational Tier A/B/C counts are optional (`include_current_tiers=true`) and reflect **current monitoring policy**, not keyword quality.

## Stage 1.18B additions

- Batched evaluation (no list N+1)
- Global breakout context on list/detail (`evaluated_at`, `global_eligible_video_count`, `ranking_version`, `attribution_mode`)
- Delayed 72h growth from discovery-anchored horizon (±12h snapshot match)
- `attribution_mode`: `all_hits` (default) or `first_discovery`

See [stage_1_18a_keyword_performance_feedback_design.md](stage_1_18a_keyword_performance_feedback_design.md).

## Stage 1.18D1 read-path performance

- Query params (list + detail): `include_breakout` (default `true`), `include_delayed` (default `true`).
- Dashboard can request **base discovery metrics first** (`include_breakout=false&include_delayed=false`), then load breakout and/or 72h blocks.
- Global breakout still uses the **full monitorable pool** when `include_breakout=true` (not keyword-local ranks).
- Benchmark artifact: `artifacts/keyword_performance_read_benchmark_1_18d1.json`.

## Stage 1.18C historical validation

- Leakage-safe early features use **discovery-time VPH** and cohort-local top decile — **not** live `breakout_v1` rank after the outcome horizon.
- Artifacts: `artifacts/keyword_performance_validation_1_18c.json` / `.md` (SHA256 in JSON footer via runner output).
- **`confirmed_breakout_count`** in API is a **compatibility alias** for live `top_decile_breakout_count` at `evaluated_at`; it is **not** delayed 72h confirmation. See validation artifact §J.

## What is NOT measured yet

- Final keyword quality or `keyword_score`
- T24/T48 delayed horizons (72h only for v1)
- Keyword lifecycle automation from performance

## Why no score yet

Validated breakout targets and outcome joins are still being defined on frozen cohorts. Ranking keywords now would bake in unvalidated assumptions.

## Data model

```
TargetKeyword
    → KeywordScanRun     (one row per keyword per discovery cycle scan)
    → KeywordDiscoveryHit (many-to-many attribution; unique per keyword/video/run)
    → Video (canonical entity; optional topic hint only)
    → VideoSnapshot (monitoring coverage)
```

## How this feeds later stages

Metrics → keyword lifecycle states → scan scheduling → related-query / LLM expansion → outcome feedback loops.

## API (read-only)

- `GET /api/keywords/performance`
- `GET /api/keywords/{keyword_id}/performance`

Query params: `from_timestamp`, `to_timestamp`, `include_current_tiers`, `limit` (list only).
