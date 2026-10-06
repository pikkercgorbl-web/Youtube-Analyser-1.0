# Stage 1.20E.5 — Discovery Cycle Performance Profiling

## CLI

```powershell
python scripts/run_discovery_cycle.py --dry-run --profile
```

Profiling is **opt-in** (`--profile`). Normal runs are unchanged.

## Instrumented phases

| Phase | Where |
|-------|--------|
| cycle_bootstrap | Run id, config |
| keyword_selection | `select_discovery_keywords` |
| per_keyword_total | Each keyword scan + persistence loop body |
| per_keyword_fetch / parse / qualification / channel / database | Inside `scan_keyword_for_discovery` |
| database | Existing video preload, hit persistence |
| db_flush_commit | commit / rollback |
| cycle_summary | Profile print |

Per keyword logs include subphase seconds and candidate counts when `--profile` is set.

## HTTP counts

- **InnerTube**: `InnerTubeMetrics.request_count` per keyword (summed at cycle).
- **HTML fallback**: `RadarFilterMetrics.html_fallback_count`.
- **Channel/homepage**: `RadarProcessResult.subscriber_fetch_count` per page (Stage 1.20E.6). Wall time for those fetches is attributed to **channel enrichment**, not qualification.

## SQL

SQLAlchemy `before/after_cursor_execute` listener (truncated statements, no huge IN lists in output).

Warnings when: network sample ≥10s, SQL ≥2s, keyword ≥60s, phase ≥30s (`[discovery:slow]`).

## Metric semantics: `qualification_rejected_count` vs `unique_video_count`

**Not a bug.**

| Metric | Level | Definition |
|--------|--------|------------|
| `unique_video_count` (cycle) | **Distinct `video_id`** | Union of `scan.unique_videos` across keywords after dedupe by `video_id` within each keyword (`unique_by_id` dict). |
| `qualification_rejected_count` (cycle) | **RadarCandidate evaluations** | Sum over keywords of candidates in `keyword_candidates` with `qualification_state == rejected`. |

Why rejected can exceed unique:

1. **Per-page candidate list is append-only** — the same `video_id` appearing on multiple search pages produces **multiple** `RadarCandidate` rows; each is qualified and counted separately.
2. **`raw_candidate_count`** counts every shelf row occurrence; **unique** dedupes by id; **qualification counts** follow the candidate list, not the unique list.

Changing these metrics would break Stage 1.16A/1.18 reporting; profiling documents the scope only.

## Tests

`scripts/test_discovery_cycle_profiling.py`
