# Stage 1.18A — Keyword performance feedback (design)

**Status:** design approved (with final contracts below) — no lifecycle automation, no keyword score, no threshold policy.

**Product question:** Which keywords consistently discover videos that later show strong breakout behavior?

---

## Final contracts (implementation prerequisites)

### 1. Global breakout context

`top_decile_breakout_rate` (and any rank-percentile / top-k breakout rate) is **relative to the global breakout-eligible pool at `evaluated_at`**, not an absolute measure of keyword quality.

- Top decile cutoff: rank ≤ ⌈0.1 × **global_eligible_video_count**⌉ using production `breakout_v1` ordering at that moment.
- A keyword with high rate in a small window may still reflect few videos; interpret with counts.

**Required on every breakout percentile/rate evaluation** (API response block or list envelope):

| Field | Meaning |
|-------|---------|
| `evaluated_at` | Timestamp when global breakout ordering was computed |
| `global_eligible_video_count` | N in global eligible pool at `evaluated_at` |
| `ranking_version` | e.g. `breakout_v1` (`BREAKOUT_RANK_VERSION`) |
| `attribution_mode` | `all_hits` or `first_discovery` (see §2) |

**Not** a standalone “keyword quality score” — descriptive yield vs global context only.

### 2. Attribution semantics (v1)

| Mode | Role |
|------|------|
| **`all_hits`** | **Default.** Distinct `(keyword_id, video_id)` with ≥1 hit in the evaluation window. Answers: “What videos did this keyword surface?” |
| **`first_discovery`** | **Secondary.** Each `video_id` credited to the keyword with earliest `discovered_at` globally (ties: lowest `keyword_id`). Answers: “Incremental discovery credit under a scan-order-sensitive rule.” |

**`first_discovery` is scan-order sensitive and must NOT be treated as ground-truth causal attribution.** It is an incremental-discovery view for comparison only.

**No fractional credit in v1.**

### 3. Delayed outcome baseline (72h growth)

Observation clock is anchored to the **keyword×video discovery event** under evaluation, not video `published_at` alone.

**Per keyword×video observation** (after dedupe — see below):

| Field | Definition |
|-------|------------|
| `discovery_at` | `discovered_at` on the selected hit |
| `views_at_discovery` | `views_at_discovery` on that hit (if null → outcome **missing**, no imputation) |
| `target_horizon_at` | `discovery_at + 72 hours` (wall clock, UTC) |
| `selected outcome snapshot` | Among `VideoSnapshot` rows for `video_id` with non-null `views` and valid `captured_at`: choose the snapshot whose `captured_at` is **closest** to `target_horizon_at`. **Eligible only if** \|`captured_at` − `target_horizon_at`\| ≤ **`HORIZON_SNAPSHOT_TOLERANCE_HOURS` (default 12h)**. If none qualify → outcome **missing**. |
| `actual_elapsed_hours` | (`selected_snapshot.captured_at` − `discovery_at`) in hours |
| `absolute_view_growth` | `outcome_views` − `views_at_discovery` |

**Multiple hits for same keyword×video:** for aggregates, use the **first hit in the evaluation window** (`MIN(discovered_at)` per `(keyword_id, video_id)` among hits matching window filters). **Do not** reset baseline on every rescan.

**Missing horizon snapshot:** exclude from `observed_72h_*` aggregates; **do not impute**.

Keyword-level delayed metrics (`median_absolute_view_growth_72h`, top-decile growth rates) are computed only over observations with a valid paired outcome.

### 4. Storage (Stage 1.18B)

- **Compute / read model only** (batch service + API).
- **Deterministic analysis artifact** (e.g. JSON under `artifacts/`) is allowed for regression and 1.18C prep.
- **Do NOT** add a new evaluation-snapshot **DB table** in 1.18B.
- Revisit persistent evaluation snapshots **only after** Stage 1.18C validates metric usefulness.

---

## A. Current provenance / data flow

### Entities (source: `app/models/orm.py`, services as cited)

| Entity | Role |
|--------|------|
| **TargetKeyword** | Queue row: `keyword`, `lifecycle_status`, `source_type`, `parent_keyword_id`, scheduling (`last_checked`, `next_scan_at`, `scan_interval_seconds`), audit (`status_changed_at`, `status_reason`). |
| **KeywordLifecycleEvent** | Append-only lifecycle transitions (`from_status`, `to_status`, `reason`, `actor_source`). |
| **KeywordScanRun** | One row per `(keyword_id, discovery_run_id)`: scan aggregates (`raw_candidates`, `unique_candidates`, dup counts, `persisted_videos`, qualification counts, `status`, timestamps). |
| **KeywordDiscoveryHit** | Attribution grain: unique per `(keyword_id, video_id, discovery_run_id)`. Stores discovery-time context: `discovered_at`, `channel_id`, dup flags, `video_existed_before_discovery`, `content_format`, `views_at_discovery`, `vph_at_discovery`, `qualification_state`, `persisted_for_monitoring`. **No FK to `Video`** — join on `video_id` string. |
| **Video** | Canonical monitored entity (`published_at`, `content_format`, `views_count`, optional `topic` — not reliable keyword provenance). |
| **VideoSnapshot** | Time series metrics (`captured_at`, `age_hours`, `views`, `vph`, …). |
| **Breakout v1** | Pure service (`breakout_ranking_service.rank_breakout_v1`) over `MonitoredVideoState` — **not persisted** on rows. API exposes ranks via `sort=breakout_v1`. |

### Trace: keyword → outcome

```
TargetKeyword
  └─ KeywordScanRun (discovery_run_id, started_at, run-level yield)
       └─ KeywordDiscoveryHit (video_id, discovered_at, T0 views/vph, flags)
            └─ Video (same video_id)
                 └─ VideoSnapshot(s) (monitoring outcomes over age_hours)
                      └─ (derived) breakout rank / growth at horizon
```

**Writes:** `discovery_cycle.py` → `persist_keyword_scan_run`, `persist_keyword_discovery_hits`, `mark_hits_persisted_for_monitoring` (`keyword_discovery_metrics_storage.py`).

**Reads today:** `keyword_performance_service.get_keyword_performance` aggregates hits + scan runs in a time window; snapshot coverage via grouped `VideoSnapshot`; optional current tier counts (explicitly **not** keyword quality).

### Is provenance sufficient?

**Yes, for keyword ↔ video attribution**, with caveats:

- **Strengths:** Durable hit rows; run linkage; discovery-time VPH/views; monitoring handoff flag; duplicate / already-known flags.
- **Gaps:**
  - Same video on **later scans** → **new hit row** (not upserted). Lifetime “unique videos” must use `DISTINCT video_id`, not hit count.
  - **Multi-keyword:** independent hit rows per keyword; no fractional credit stored.
  - **No “first discoverer” column** — derivable as `MIN(discovered_at)` per `video_id` across hits.
  - **Breakout / 72h outcomes** not on hit row — must join monitoring state + snapshots (or materialized evaluation).
  - **`Video.topic`** is not the attribution source of truth.

---

## B. Recommended observation units

Use **three layers**; do not collapse into one number.

| Layer | Unit | Use |
|-------|------|-----|
| **Event** | `KeywordDiscoveryHit` (or deduped **keyword × video** first hit) | Raw attribution, dup flags, discovery-time metrics, per-event outcome join. |
| **Run** | `KeywordScanRun` + hits in that `discovery_run_id` | Scan yield stability, “what did this scan produce?” |
| **Aggregate** | `keyword_id` over **window** (rolling or lifetime) | Product ranking / dashboards / future lifecycle **inputs**. |

**Window vs lifetime:**

- **Lifetime aggregates** — auditability, long-tail keywords, expansion genealogy (`parent_keyword_id`).
- **Operational recent view** — default UI window (e.g. last 30d or last *N* scans) so old behavior does not mask current quality.

**Recommendation:** Persist facts at **event** grain (already done). Compute **run** and **window/lifetime** metrics in read model / snapshots (below).

---

## C. Proposed keyword metrics (v1 descriptive, no score)

Grouped by theme; names align with existing `KeywordPerformanceMetrics` where possible.

### Discovery yield (existing + clarify)

- From **ScanRun:** `raw_candidates`, `unique_candidates`, within/cross dup at scan level.
- From **Hits:** `discovery_hit_count`, `unique_video_count`, `unique_channel_count`, rates per scan.
- **New emphasis:** `new_to_corpus_video_count` = distinct videos with `video_existed_before_discovery = false`.

### Monitoring / breakout eligibility yield

- `persisted_for_monitoring_count` / distinct persisted videos (existing).
- **`monitorable_video_count`:** distinct attributed videos present in `load_monitored_video_states` (regular, not SHORT/LIVE).
- **`breakout_eligible_video_count`:** subset passing `breakout_fundamental_eligibility` (same rules as production breakout v1).

### Breakout yield (online — see §E)

Per keyword (window/lifetime), over **attributed video set** (policy: see §D):

- `breakout_ranked_video_count` — eligible videos with a rank in global breakout ordering at `evaluated_at`.
- `top_decile_breakout_count` / `top_decile_breakout_rate` — count/rate with rank ≤ ⌈0.1 × eligible_population⌉ (population = global eligible N at evaluation, not keyword-local).
- `top_quartile_breakout_count` / rate (optional descriptive).
- **Discovery-time velocity:** `median_vph_at_discovery`, `p90_vph_at_discovery` on hits (fields already on hit).
- **Current velocity:** join latest snapshot / state VPH for attributed videos (staleness noted).

**Not** a composite keyword score — report counts, rates, and percentiles separately.

### Consistency / outlier sensitivity

- `scan_count`, `unique_videos_per_scan` variance (or IQR across runs).
- **`top_video_share`:** max single-video contribution to breakout top-decile count (detect one-hit wonders).
- `runs_with_zero_persisted` count.

### Redundancy (existing)

- `cross_keyword_duplicate_count`, `already_known_video_count`, `duplicate_rate`.
- **`exclusive_discovery_count`:** videos where this keyword was **first** discoverer (derived).

### Delayed outcome (offline — see §Final contracts §3)

- `observed_72h_video_count` — keyword×video observations with valid horizon-matched snapshot (§3).
- `median_absolute_view_growth_72h` on that subset.
- `top_decile_growth_72h_count` / rate — videos above **global** p90 growth among all observed 72h outcomes in the same evaluation batch (not keyword-local p90 until validated).

Placeholder fields in API (`t24_outcome_count`, `confirmed_breakout_count`) should be **filled with defined semantics** or renamed — avoid “confirmed_breakout” without definition.

---

## D. Multi-keyword attribution strategy

**Principle:** Preserve **raw multi-credit facts** first; publish **derived views** with explicit bias.

| Strategy | Pros | Cons |
|----------|------|------|
| **Full credit to every keyword** | Simple; rewards coverage | Inflates all overlapping keywords; overstates niche duplicates |
| **Fractional 1/k** | Budgets total credit | Loses interpretability; k changes over time |
| **First-discovery credit only** | Clear “origin” story | Penalizes valid alternate queries; sensitive to scan order |
| **Primary + secondary metrics** | Transparent | More columns |

**Recommendation (v1):** See **Final contracts §2**.

1. **Store (already):** every `KeywordDiscoveryHit` as full credit event.
2. **Report two modes:** `all_hits` (default), `first_discovery` (secondary, not causal).
3. **Redundancy context:** `cross_keyword_duplicate_rate`, `shared_video_count`.

No fractional credit in v1.

---

## E. Online vs delayed feedback

### Online (minutes–hours after discovery)

Available from hits + current monitoring read path:

- Discovery yield, qualification, persisted counts.
- **Breakout rank percentile** at `last_evaluated_at` (global eligible pool, cap-independent — same as `sort=breakout_v1`).
- Current VPH / views / eligibility flags.
- Snapshot **recency** (latest `captured_at`) — staleness for cap-excluded videos.

**Use:** Steer analyst attention, compare keywords on early velocity surfacing, safe near-real-time dashboards.

### Delayed (72h primary for v1)

Available after discovery + horizon:

- **72h growth** per **Final contracts §3** (discovery-anchored clock, tolerance-matched snapshot).
- Legacy snapshot coverage counts (`videos_with_snapshot_72h_count` by max `age_hours`) remain **informational only** — not the delayed outcome definition.
- Validated against frozen cohort spirit (`absolute_view_growth` in Stage 1.9D / 1.10C); cohort clock differs (T0 freeze) — 1.18C compares methodology, not numeric equality.

**Use:** Validate whether online breakout surfacing predicts delayed growth; calibrate lifecycle **later** (1.18E).

**Breakout for keyword feedback — metric choice:**

| Signal | Role |
|--------|------|
| **A. Breakout rank percentile** | Aligns with product breakout list; relative among live monitorable videos; online. |
| **B. Raw VPH** | Interpretable; comparable to discovery-time VPH on hit; online. |
| **C. 72h absolute growth** | Outcome-grounded; delayed; best for validation / lifecycle. |
| **D. Combination** | Report **side-by-side**, not weighted score. |

Stage 1.17C showed breakout v1 ≈ VPH ordering for prediction — keyword layer should track **both** breakout rank stats and discovery VPH, plus **delayed growth** when available.

---

## F. Evidence / confidence model

Expose explicit **evidence state** (labels only in 1.18A — **no hard thresholds** in code until 1.18C validation):

Suggested inputs:

- `scan_count`
- `unique_video_count` (or first-discovery unique)
- `breakout_eligible_video_count`
- `observed_72h_video_count`

Suggested states (conceptual):

| State | Meaning |
|-------|---------|
| **insufficient** | Too few scans or zero attributable monitorable videos — hide rates or show “—”. |
| **early** | Some signal (e.g. hits exist) but minimal delayed outcomes. |
| **established** | Enough scans **and** enough eligible/outcome videos to interpret rates. |

**Existing lifecycle hint:** `PROBATION_READY_SCAN_COUNT = 3` (`keyword_scheduling_policy.py`) → `scheduling_hint=probation_ready_for_review` — **scheduling only**, not quality. Do not reuse as breakout evidence threshold without validation.

Always return **counts** alongside any rate.

---

## G. Proposed KeywordPerformance contract (v1.18B target)

Extend current `KeywordPerformanceMetrics` / `KeywordPerformanceMetricsResponse` — additive fields, snake_case, optional sections.

```text
# Identity (existing)
keyword_id, keyword, lifecycle_status, source_type, scheduling fields…

# Window
window_from, window_to

# Required breakout / evaluation context (every response that includes breakout or delayed rates)
evaluated_at
global_eligible_video_count
ranking_version          # breakout_v1
attribution_mode         # all_hits | first_discovery
horizon_hours            # 72
horizon_snapshot_tolerance_hours  # 12

# Activity (existing)
scan_count, first_scan_at, last_scan_at

# Discovery yield (existing + new)
discovery_hit_count, unique_video_count, new_to_corpus_video_count, …

# Monitoring / breakout eligibility (new)
monitorable_video_count
breakout_eligible_video_count

# Online breakout (keyword-attributed subset vs GLOBAL pool at evaluated_at)
breakout_ranked_video_count
top_decile_breakout_count
top_decile_breakout_rate   # NOT absolute quality; requires global context fields above
median_vph_at_discovery
p90_vph_at_discovery
median_current_vph

# Consistency (new)
top_video_share_of_top_decile_breakouts
scan_count_with_zero_persisted

# Redundancy (existing)
cross_keyword_duplicate_count, duplicate_rate, exclusive_discovery_count

# Delayed (fill placeholders with real defs)
observed_72h_video_count
median_absolute_view_growth_72h
top_decile_72h_growth_count
top_decile_72h_growth_rate

# Meta
evidence_status: "insufficient" | "early" | "established"
evidence_detail: { scan_count, unique_video_count, … }  # counts only
```

**Lifecycle decoupling:** Same row may show `lifecycle_status=probation` and `evidence_status=early` with high `p90_vph_at_discovery` — no auto transition.

---

## H. Storage strategy

| Option | When |
|--------|------|
| **Compute / read model** | **1.18B** — batch service + API; one breakout pass per request/batch. |
| **Deterministic analysis artifact** | **1.18B allowed** — e.g. `artifacts/keyword_performance_evaluation_*.json` for tests and 1.18C. |
| **DB evaluation snapshot table** | **Not 1.18B.** Revisit after **1.18C** if metrics prove useful. |
| **Materialized aggregate table** | Post-validation only if read cost requires it. |

Avoid recomputing breakout order per keyword; avoid N+1 list reads (fix in 1.18B).

---

## I. Query / performance plan

**Per evaluation batch (worker or API list):**

1. One query: hits (+ scan runs) grouped by `keyword_id` in window → sets of `video_id`, dup stats, discovery VPH aggregates.
2. One query: distinct `video_id` universe across keywords (or per request cap).
3. **One** `load_monitored_video_states(session)` (+ batched latest snapshots if needed for views tie-break) → **one** `rank_breakout_v1` → map `video_id → {rank, eligible, vph}`.
4. One batched query: load snapshots for attributed `video_id` set; in memory, match **horizon snapshot** per keyword×video (§3, tolerance 12h).
5. Join in application memory: keyword → video set → online breakout map + delayed outcomes.

**Forbidden patterns:**

- Per-keyword full monitoring enrich.
- Per-video detail API from keyword job.
- Per-keyword breakout re-rank.

**Note:** `include_current_tiers=true` remains opt-in and **not** part of breakout feedback.

---

## J. API / UI implications (design only)

**API:** Extend existing:

- `GET /api/keywords/performance` — list with `window`, `attribution_mode`, `include_breakout`, `include_delayed`.
- `GET /api/keywords/{id}/performance` — detail + optional run breakdown (`KeywordScanRun` series).

Query params (conceptual): `from_timestamp`, `to_timestamp`, `attribution_mode`, `evidence_min` (filter insufficient — optional).

**UI (1.18D):** Table columns — Keyword, Lifecycle (context), Scans, Unique videos, Breakout eligible, Top-decile rate (with evidence badge), Dup rate, 72h coverage, Last evaluated. No score dial. Link to videos via existing monitoring/breakout views.

---

## K. Historical validation plan (1.18C)

**Frozen cohorts:** Join rows carry `t0_keywords[]` — useful for **methodology rehearsal**, not direct `TargetKeyword.id` mapping. Use for metric definitions (Spearman, top-decile capture) on keyword **labels** as pseudo-keywords.

**Production DB (post 1.18B):**

1. **Predictive:** For keywords with `observed_72h_video_count ≥ k`, correlate keyword `top_decile_breakout_rate` with median / p90 `absolute_view_growth_72h` on attributed videos.
2. **Stability:** Split scans chronologically; compare online metrics scan1–half vs half–end.
3. **Outlier dominance:** Distribution of `top_video_share`; flag keywords where one video = 100% of top-decile count.
4. **Redundancy:** High `duplicate_rate` vs incremental `new_to_corpus_video_count` and delayed outcomes.

**Success criteria (qualitative for 1.18C):** Online breakout yield associated with delayed growth **at least as well as** raw discovery VPH; metrics stable enough to inform lifecycle design — **not** fixed ρ thresholds in 1.18A.

---

## L. Stage decomposition

| Stage | Scope |
|-------|--------|
| **1.18A** | This design + final contracts (above) |
| **1.18B** | See **1.18B implementation plan** below |
| **1.18C** | Historical + production validation; **then** decide on persistent evaluation snapshots |
| **1.18D** | Keyword performance UI |
| **1.18E** | Lifecycle automation **design** only (no auto in B/C/D) |

### 1.18B implementation plan (scoped)

1. **Batched keyword / hit aggregates** in window (`all_hits` default; optional `first_discovery`).
2. **One breakout ranking pass** per evaluation — populate `evaluated_at`, `global_eligible_video_count`, `ranking_version`; join to keyword video sets.
3. **Delayed outcome batch matching** — discovery-anchored 72h growth (§3); first hit per keyword×video in window.
4. **API / schema** — extend existing keyword performance endpoints; required global context fields on breakout/delayed rates.
5. **Tests** — horizon matching, dedupe, global top-decile semantics, attribution modes; optional golden artifact.
6. **No lifecycle writes**, **no keyword score**, **no DB evaluation snapshot table**.
7. Optional **deterministic JSON artifact** for regression (not required for production read path).

---

## M. Risks / open questions

1. **Global breakout pool shifts** — mitigated by required `evaluated_at` + `global_eligible_video_count` + `ranking_version` on every rate.
2. **Staleness** — keywords surfacing cap-excluded videos may look weak online but reflect snapshot gap (same as breakout UI).
3. **Qualification vs monitoring** — rejected hits still valuable for “surfaced velocity”; separate metrics for `qualification_passed` vs `persisted_for_monitoring`.
4. **First-discovery ties** — deterministic tie-break needed.
5. **Window defaults** — product choice (30d vs last 10 scans) affects probation keywords; expose in API.
6. **Placeholder field debt** — `confirmed_breakout_count` needs definition or removal.
7. **Expansion keywords** — `parent_keyword_id` genealogy metrics deferred or minimal in v1.

---

## Constraints honored

No keyword score, no lifecycle auto-change, no discovery/monitoring worker changes, no tier/breakout coupling, no frozen artifact edits.
