# Stage 1.20B — Keyword evidence read model

**Status:** implemented (read-only). No lifecycle automation, no scores, no scheduling changes.

---

## A. Evidence schema

HTTP responses use `KeywordEvidenceResponse` (`app/models/schemas.py`) with nested families:

| Family | Type | Role (1.20A policy) |
|--------|------|------------------------|
| `scan` | `ScanEvidenceResponse` | **Primary** |
| `discovery` | `DiscoveryEvidenceResponse` | **Primary** |
| `redundancy` | `RedundancyEvidenceResponse` | **Supporting** |
| `discovery_vph` | `DiscoveryVphEvidenceResponse` | **Supporting** |
| `breakout` | `BreakoutEvidenceResponse` | **Supporting** (optional) |
| `delayed_outcome` | `DelayedOutcomeEvidenceResponse` | **Not ready** for Phase 1 lifecycle auto |
| `lifecycle_context` | `LifecycleContextEvidenceResponse` | **Primary** (operational) |
| `scheduling` | `SchedulingEvidenceResponse` | **Primary** (operational) |

Each family includes `meta: { availability, role }` where `availability ∈ { available, insufficient, unavailable }`.

Internal dataclasses: `app/services/keyword_evidence_types.py`.

---

## B. Source mapping

| Evidence field | Source |
|----------------|--------|
| Identity / scheduling columns | `TargetKeyword` |
| Scan counts, sums, latest status | `KeywordScanRun` (batch SQL in `keyword_evidence_service._load_scan_batch`) |
| Hit/yield/VPH/breakout/72h aggregates | `evaluate_keywords_batch` (`keyword_performance_evaluation.py`) |
| Breakout ranks | `build_global_breakout_bundle` + `breakout_v1` (`breakout_ranking_service`) |
| 72h outcomes | `match_horizon_outcome` (same tolerance/horizon as performance API) |
| Manual lifecycle | `KeywordLifecycleEvent` (batch load) |
| `probation_ready_for_review` hint | `PROBATION_READY_SCAN_COUNT` + successful scan count from batch scan row |

**Not used in this stage:** qualification pass rate as lifecycle input (available only via performance API as diagnostic).

---

## C. Aggregation semantics

- **Scans:** `successful_scan_count` = runs with `status == "ok"`; `failed_scan_count` = `status == "failed"`. Infrastructure failures are isolated from yield metrics.
- **Discovery:** Hits aggregated per keyword; attribution mode filters attributed video set.
- **Ratios:** `unique_candidate_rate = sum(unique_candidates)/sum(raw_candidates)` from scan runs; rates are `null` when denominator is 0.
- **VPH:** Discovery-time only (`vph_at_discovery` on first hit per keyword×video baseline). `median_current_vph` is intentionally **not** exposed on evidence API (monitoring VPH stays separate).
- **Breakout:** Reuses global pool at `evaluated_at`. Rate is `null` when `breakout_eligible_count == 0`.
- **72h:** `matured_72h_count` = attributed baselines with views at discovery where `evaluated_at >= discovery_at + 72h`. Valid/missing counts follow existing evaluation loop (no imputation).

---

## D. Availability semantics

| Situation | Handling |
|-----------|----------|
| No scans | Scan family `insufficient`; discovery `insufficient` |
| No VPH observations | `discovery_vph.insufficient`; medians `null` |
| `include_breakout=false` | Breakout family `unavailable` |
| `include_delayed=false` | Delayed family `unavailable`; growth fields `null` |
| Zero eligible breakout | Rate `null`; meta `insufficient` or `unavailable` if global pool empty |
| Zero valid 72h outcomes | Median/p90 growth `null` — **not** zero growth |
| Failed scans | Increment `failed_scan_count` only |

---

## E. Attribution semantics

Query param `attribution_mode`:

- **`all_hits`** (default): distinct videos with ≥1 hit for keyword.
- **`first_discovery`**: videos whose globally first hit (tie: lowest `keyword_id`) belongs to this keyword.

Documented as scan-order-sensitive; not causal. Exposed on each item and list envelope.

---

## F. Query strategy

For `list_keyword_evidence` / `get_keyword_evidence`:

1. Load `TargetKeyword` rows (filter/limit).
2. **One grouped query** for scan aggregates + latest status per keyword.
3. **One query** for lifecycle events (derive latest actor + last manual change).
4. **One** `build_global_breakout_bundle` when `include_breakout=true`.
5. **One** `evaluate_keywords_batch` for all keyword IDs (shared hit load + optional snapshot window).

Scheduling due/hint uses in-memory `TargetKeyword` + successful scan count (no per-keyword `get_keyword_schedule_state`).

---

## G. API

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/keywords/evidence` | `limit`, `lifecycle_status`, `attribution_mode`, `include_breakout` (default false), `include_delayed` (default false) |
| GET | `/api/keywords/{keyword_id}/evidence` | Detail; breakout/delayed default **true** |

Router: `app/api/routes/keyword_evidence.py`.

---

## H. Tests

`scripts/test_keyword_evidence.py` — scan success/failure, zero yield, duplicates, VPH missing, breakout eligible zero, 72h valid/missing, attribution modes, division by zero, delayed disabled, manual lifecycle, SQL round-trip guard.

---

## I. Performance

List path targets batch aggregation (see test `test_batch_list_no_per_keyword_scan_query_explosion`). Expensive families off by default on list endpoint.

No caching layer in 1.20B.

---

## J. Known limitations

- List defaults omit breakout/delayed for speed; clients must opt in.
- `p90_72h_growth` only populated when ≥1 valid outcome (same as median guard).
- Lifecycle batch loads all events for selected keywords (acceptable for current pool sizes).
- Genealogy depth not computed in evidence model (1.20A follow-up).

---

## K. What this stage deliberately does NOT decide

- Promotion, demotion, archival, or expansion orchestration
- Keyword quality score or weighted recommendation
- Changes to discovery scheduling, monitoring, or expansion caps
- UI for evidence (API-only)

See `docs/stage_1_20a_keyword_pool_governance.md` for policy intent.
