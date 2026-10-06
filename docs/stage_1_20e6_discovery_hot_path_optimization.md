# Stage 1.20E.6 — Discovery Hot Path Optimization

## A. Qualification dependency findings

| Question | Answer |
|----------|--------|
| Canonical **Video** persistence? | **No.** `run_discovery_cycle_async` persists every `scan.unique_videos` regular row via `batch_persist_discovered_videos` / `persist_discovered_video`, independent of qualification outcome. |
| **KeywordDiscoveryHit** persistence? | **No (gate).** Hits are written for all unique videos per keyword; `qualification_state` / `first_failure_reason` come from the matching `RadarCandidate` but rejection does not skip the hit. |
| **Monitoring** handoff? | **No (gate).** Monitoring marks hits when the video was inserted/updated through discovery persistence (format filter only: shorts/live skipped). |
| **ExplosiveChannel**? | **Yes.** Legacy qualification + `_register_channel_video` only when `register_channels=True` and the candidate passes FR-5 thresholds. |

Qualification is a **side-path** for the explosive watchlist, not a blocking gate for core Radar discovery persistence.

## B. Qualification time breakdown (production profile baseline)

Baseline dry-run (~646s / 5 keywords): **qualification ≈ 258s** (included homepage subscriber I/O; channel phase incorrectly ≈ 0).

After 1.20E.6 instrumentation:

- **Channel/subscriber network** → `profile_phase_seconds.channel_enrichment` and `subscriber_fetch_seconds` on `RadarProcessResult`.
- **CPU-only qualification** → `qualification` phase (date, views, language, blacklist, virality math, explosive DB for passes).
- **Rejection counts by reason** → `filter_metrics_summary.filter_skip_reasons` (unchanged keys).

Sub-phases inside legacy qualification (conceptual):

1. Settings — **once per keyword scan** via `RadarQualificationContext` (was once per InnerTube page).
2. Cheap skips — date, min_views, channel_id, language, blacklist (no network).
3. Subscriber resolution — DB batch prefill (`prefill_subscriber_cache_from_db`) then homepage fetch (deduped, bounded concurrency).
4. Virality / explosive register — batch `ExplosiveChannel` preload + per-pass flush semantics preserved.

## C–E. Repeated SQL / HTTP / N+1

| Pattern | Before | After |
|---------|--------|--------|
| `explosive_channel_settings` / thresholds | `get_thresholds` + `_get_or_create_settings` **per page batch** | **Once per keyword** (`load_radar_qualification_context`) |
| `Channel.subscribers_count` | N/A (homepage only) | **`WHERE id IN (...)`** prefill per page eligible set |
| `ExplosiveChannel` lookup | `db.get` per pass | **Batch `IN` query** + in-memory map |
| `Video` existence on persist | `session.get` per video | **One `SELECT … IN` per keyword** + upsert without extra gets |
| Homepage subscriber fetch | Sequential per channel, counted as qualification | **Deduped**; max **3** concurrent fetches; time attributed to **channel enrichment** |

Cheap-first check order unchanged (see `radar_filter_metrics.FILTER_SKIP_*` order).

## F–G. Channel fetch dedupe & concurrency

- At most **one homepage fetch per channel_id per scan** (shared `subscriber_cache` across pages).
- Multiple videos on the same channel reuse cache after first resolution.
- Fetches run only for candidates that **passed cheap rules** and still lack subscriber counts after shelf + DB prefill.
- `RADAR_SUBSCRIBER_FETCH_CONCURRENCY = 3` with existing per-fetch delay preserved.

## H. Core discovery vs legacy qualification

No separate worker: same scan pipeline, but semantics were already decoupled — **core persistence does not depend on qualification success**. Optimizations reduce shared work (settings, DB, network) without moving qualification off the hot path.

## I. Metric semantics

- `unique_video_count` — distinct `video_id` across keywords (within-keyword dedupe).
- `qualification_passed_count` / `qualification_rejected_count` — **per `RadarCandidate` evaluation** (append per search page; same video on multiple pages counted multiple times).

So `passed + rejected` can exceed `unique_video_count` **by design** (documented in 1.20E.5). Not changed in 1.20E.6.

## J. Performance targets

Re-measure on your environment:

```powershell
python scripts/run_discovery_cycle.py --dry-run --profile
```

Report before/after: total cycle, qualification vs channel enrichment seconds, SQL statement count, HTTP InnerTube vs homepage counts.

Expected wins: fewer settings SQL round trips, fewer homepage calls when `Channel` already has subs, faster non-dry-run persistence via batch video lookup, shorter wall time on subscriber phase via concurrency (bounded).

## K. Tests

`scripts/test_discovery_hot_path_1_20e6.py` covers settings-once, DB prefill vs homepage, channel dedupe, cheap reject without fetch, batch video SELECT, rejected qual still persists in cycle, candidate-level qual counts.

## Files touched

- `app/services/explosive_channels_service.py` — two-phase qual, prefetch, batch explosive map, context API
- `app/services/radar_qualification_context.py`, `radar_subscriber_cache.py`
- `app/services/discovery_keyword_scan.py` — context + profiler split
- `app/services/discovered_video_batch.py`, `discovered_video_persistence.py`
- `app/services/discovery_cycle.py` — batch persist
