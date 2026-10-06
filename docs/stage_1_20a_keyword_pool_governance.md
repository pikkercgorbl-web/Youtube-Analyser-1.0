# Stage 1.20A — Keyword Pool Governance / Lifecycle Policy (design)

**Status:** design only — no automatic lifecycle transitions, no discovery-worker expansion wiring, no scheduling interval changes.

**Product question:** How should the system *eventually* decide which keywords enter the pool, how they are scanned, when they may spawn children, and when lifecycle status changes — without conflating scheduling, quality, and budget?

---

## A. Current behavior in the repository

### A.1 Data model (source: `app/models/orm.py`)

| Entity | Purpose | Key fields / constraints |
|--------|---------|---------------------------|
| **TargetKeyword** | Discovery scan queue row | `keyword` (unique), `lifecycle_status`, `source_type`, `parent_keyword_id` (FK self, `ON DELETE SET NULL`), `last_checked`, `next_scan_at`, `scan_interval_seconds`, `status_changed_at`, `status_reason`. ORM default `lifecycle_status="active"` (legacy rows may differ). |
| **KeywordLifecycleEvent** | Append-only lifecycle audit | `from_status`, `to_status`, `changed_at`, `reason`, `actor_source`. |
| **KeywordExpansionEvent** | Expansion attempt audit | `parent_keyword_id`, `candidate_text`, `normalized_candidate`, `source_type`, `outcome` (`created` / `existing` / `rejected`), `rejection_reason`, `created_keyword_id`, `discovery_run_id`. Index on `(parent_keyword_id, source_type, discovered_at)`. |
| **KeywordScanRun** | One scan per `(keyword_id, discovery_run_id)` | Aggregates: `raw_candidates`, `unique_candidates`, dup counts, `persisted_videos`, `qualification_passed/rejected`, `status` (`ok` / `failed`), `error_summary`, timestamps. |
| **KeywordDiscoveryHit** | Attribution grain `(keyword_id, video_id, discovery_run_id)` | `discovered_at`, dup flags, `video_existed_before_discovery`, `views_at_discovery`, `vph_at_discovery`, `qualification_state`, `persisted_for_monitoring`. |

### A.2 Scheduling policy (verified: `app/services/keyword_scheduling_policy.py`)

| Lifecycle | Scan interval | Notes |
|-----------|---------------|--------|
| **probation** | **6 h** | `probation_interval_hours=6.0` |
| **active** | **24 h** | `active_interval_hours=24.0` |
| **weak** | **72 h** | `weak_interval_hours=72.0` |
| **archived** | **none** | `interval_seconds_for` → `None`; no `next_scan_at` after lifecycle change |
| **Failed scan retry** | **2 h** | `next_scan_at` via `next_scan_after_failure` only; **`last_checked` not updated** |

Additional constants:

- `PROBATION_READY_SCAN_COUNT = 3` — used only for **review hint**, not automation (`probation_ready_for_review` in `keyword_schedule_state.py`).
- `LIFECYCLE_TIEBREAK_ORDER`: probation → active → weak → archived (discovery batch tie-break only).

**Due semantics** (`is_keyword_due`, `keyword_schedule_state.py`): non-archived and (`next_scan_at IS NULL` OR `next_scan_at <= now`). Null `next_scan_at` ⇒ due immediately.

**After lifecycle change:** active/probation ⇒ `next_scan_at = now`; weak ⇒ now + interval; archived ⇒ `next_scan_at = None`.

### A.3 Lifecycle mutations today (`keyword_lifecycle_service.py`)

| Action | Behavior |
|--------|----------|
| **create_keyword** | Normalizes text; returns existing row if normalized duplicate; else insert + `KeywordLifecycleEvent`. Default caller-chosen status (expansion → probation; API seed → active). |
| **set_keyword_lifecycle** | PATCH path; writes event with `actor_source` (API uses `"api"`). Updates interval + `next_scan_at`. |
| **apply_post_scan_schedule** | Success: updates `last_checked`, schedules next success interval. Failure: 2 h retry only. **No lifecycle change.** |
| **count_successful_scans** | `KeywordScanRun.status == "ok"` only. |
| **probation_ready_for_review** | probation + successful scans ≥ 3. |

**No automatic promotion/demotion/archival exists in code.**

### A.4 Discovery worker keyword selection (`discovery_keyword_selection.py`, `discovery_cycle.py`)

- Batch size default **5** (`DEFAULT_KEYWORD_BATCH_SIZE`, worker config mirrors this).
- Selects non-archived keywords with due `next_scan_at` (or null).
- Sort: **overdue seconds ↓**, then lifecycle tie-break, then oldest `last_checked`, then `id`.
- Per keyword: InnerTube scan → hits + scan run → `apply_post_scan_schedule(scan_succeeded=not keyword_failed)`.
- **`keyword_failed`** ⇔ `scan.error is not None` (exception path ⇒ failed run + 2 h retry).
- **Expansion is not invoked** from discovery cycle or worker (confirmed: no expansion imports under discovery services).

### A.5 Expansion (verified: `keyword_expansion_service.py`, `keyword_expansion_filter.py`, `keyword_expansion_persistence.py`)

**Defaults (`KeywordExpansionConfig`):**

| Parameter | Default |
|-----------|---------|
| `max_candidates_per_source_per_seed` | **20** |
| `max_new_keywords_per_seed_per_run` | **10** |
| `max_new_keywords_per_expansion_run` | **50** |
| `cooldown_days` | **7.0** (per parent × source_type, from `KeywordExpansionEvent.discovered_at`) |
| `expand_weak` | **False** |
| `max_seeds_per_batch` | **10** |
| `source_types` | **suggestion, related, channel** (not seed/manual/llm) |

**Seed eligibility (`is_seed_eligible`):** archived ❌; weak ❌ unless `expand_weak=True`; active, probation, weak (if flag) ✅.

**Admission today:** After string filter, `persist_expansion_candidate` calls `create_keyword(..., lifecycle_status=probation)`. Existing normalized keyword ⇒ outcome `existing` (**lifecycle unchanged**, including archived).

**Pre-admission filter (`filter_candidates` / `reject_reason`):** empty, too short (<3), too long (>120), same as parent, URL-like, numeric-only, duplicate in batch. **Does not** check global pool size or archived semantics beyond `create_keyword` dedupe.

**API:** `POST /api/keywords/{id}/expand` — optional override `max_new_keywords_per_seed_per_run` only.

**Manual seeds:** `TargetKeywordsService.create` → `create_keyword(..., source_type=seed, lifecycle_status=active)` (`target_keywords_service.py`).

### A.6 Performance / outcome read path (reference only for future evidence)

- `keyword_performance_evaluation.py`: `HORIZON_HOURS=72`, `HORIZON_SNAPSHOT_TOLERANCE_HOURS=12`; breakout via global pool; attribution `all_hits` / `first_discovery`.
- `operations_overview_service.py` / `operations_maturity_sql.py`: keyword outcome maturity (pending / valid / missing 72h) for operations UI — **not wired to lifecycle**.

### A.7 Source types (verified: `keyword_scheduling_policy.py`)

`seed`, `manual`, `suggestion`, `related`, `channel`, `llm` — expansion persistence uses candidate `source_type`; only suggestion/related/channel are expansion **sources**.

---

## B. Risks in current behavior

1. **Admission asymmetry:** Manual/API **seed → active**; expansion child → **probation** with no unified admission policy object.
2. **Expansion ≈ admission:** Any filtered candidate that is not an existing keyword is admitted to probation without yield evidence.
3. **Archived keywords block expansion as seeds** but **existing archived match** still returns `existing` — no reactivation path in expansion.
4. **No expansion depth gate:** Child can be expanded on the next API call; batch run does not expand newly created IDs in the same run, but **next run** can expand depth-1 immediately (no min successful scans).
5. **Probation review is a hint only** (`probation_ready_for_review`) — easy to misread in UI as “system decided quality.”
6. **Scan failure vs empty SERP:** Failed runs do not increment successful scan count; empty-but-ok runs do — good — but operators may confuse zero yield with infra failure unless `error_summary` is inspected.
7. **Duplicate detection:** `find_keyword_by_normalized` scans all keywords (scalability / race under load).
8. **No pool-wide or probation budgets** beyond expansion numeric caps.
9. **Lifecycle and performance metrics are separate products** (1.21E pool vs performance) — governance must keep that separation when automation arrives.

---

## C. Operational state definitions (not quality scores)

### PROBATION

- **Meaning:** Newly admitted keyword under evaluation scheduling (6 h scans).
- **Operational goal:** Collect repeated discovery observations before committing regular scan budget (24 h) or demotion (72 h).
- **Not:** “Low quality” or “failed.”

### ACTIVE

- **Meaning:** Keyword remains in the regular discovery rotation (24 h).
- **Operational goal:** Continued surveillance for new videos/channels worth monitoring.
- **Not:** “High breakout rate” or “proven niche.” Manual seeds enter here by product choice today.

### WEAK

- **Meaning:** Deprioritized but **retained**; scanned every 72 h.
- **Operational goal:** Cheap residual coverage; reversible without data loss.
- **Not:** “Bad/dead keyword.” UI must avoid shame labeling (see 1.21F pool copy: “Редкий” scheduling mode).

### ARCHIVED

- **Meaning:** Removed from automatic scheduling (`next_scan_at` cleared); history (hits, runs, events) retained.
- **Operational goal:** Human or policy decision to stop spending scan/expansion budget.
- **Not:** Deletion. **Reactivation** via manual lifecycle (or future explicit restore policy) must remain possible.

---

## D. Three separate policies (mandatory separation)

| Policy | Question | Must not use |
|--------|----------|--------------|
| **Admission** | Should this *candidate string* become (or re-enter) a `TargetKeyword` row? | Performance score, single 0–100 metric |
| **Lifecycle** | Given *existing* keyword evidence over time, which scheduling band applies? | Expansion budget exhaustion as “weak” |
| **Expansion** | Should this *existing* keyword invoke child discovery **now**? | Admission by default; 72h outcome alone in Phase 1 |

Implement as separate functions/services with explicit inputs/outputs and audit events (`KeywordLifecycleEvent`, `KeywordExpansionEvent`).

---

## E. Admission policy (design — not implemented)

### E.1 Future pipeline

```
expansion/manual/API candidate
  → normalize + structural filter (today's filter_candidates++)
  → admission decision (NEW)
  → create_keyword(probation) OR link existing OR reject (event only)
```

**Principle:** Expansion candidate discovery **must not** imply admission.

### E.2 Admission checks (proposed layers)

| Check | Action if fail | Notes |
|-------|----------------|-------|
| Normalization empty / length / URL / numeric | Reject | Already in filter |
| Same as parent (normalized) | Reject | Already |
| Duplicate in batch | Reject | Already |
| Exact duplicate of existing TargetKeyword | **No new row**; record expansion `existing` | Today; decide archived reactivation separately (§L) |
| Obvious noise tokens | Reject | **CALIBRATION REQUIRED** — blocklist / entropy rules |
| Global pool size cap | Defer/reject admission | Budget policy (§J), not quality |
| Per-parent child cap (lifetime or window) | Defer/reject | Genealogy (§I) |
| Source-specific rules | e.g. channel topics require min hits | **CALIBRATION REQUIRED** |

### E.3 Source provenance

- Persist `source_type` + `parent_keyword_id` + expansion event (already).
- **Manual/seed:** Product may continue direct **active** admission for operator-intent seeds (explicit bypass of probation) — document as **manual admission class**, not expansion class.

### E.4 Archived keyword collision

- **Default (conservative):** `existing` archived ⇒ **do not auto-reactivate**; record event; optional manual “restore to probation.”
- **Alternative (future flag):** reactivate to probation with reason — only after UX/policy review.

---

## F. Probation evidence (`PROBATION_READY_SCAN_COUNT = 3`)

### F.1 Is 3 successful scans still sensible?

**Yes as a minimum checkpoint**, not as sufficient evidence alone:

- At 6 h interval, three **successful** scans ≈ ≥12 h wall time minimum (plus overdue skew) — enough to see at least diurnal variation in SERP.
- Aligns with existing `count_successful_scans` and API hint `probation_ready_for_review`.
- **Recommendation:** Keep **3** as “minimum scans before automated **recommendation** is allowed”; promotion automation should prefer **CALIBRATION REQUIRED** window (e.g. 3–5 scans **and** aggregated yield rules).

Failed scans (`status != ok`) must **not** count toward review readiness (already the case).

### F.2 Metric classification for lifecycle decisions

| Metric | Class | Lifecycle use |
|--------|-------|----------------|
| Successful scan count (`KeywordScanRun.status=ok`) | **Primary** | Minimum observations gate |
| Distinct videos attributed (hits, deduped) | **Primary** | Yield existence |
| New-to-database videos (`video_existed_before_discovery=false`) | **Primary** | Incremental corpus value |
| Persisted-for-monitoring count | **Supporting** | Downstream pipeline value |
| Scan-level `persisted_videos` / `unique_candidates` | **Supporting** | Run-level yield |
| Cross-keyword duplicate rate (scan or hit flags) | **Supporting** | Redundancy cost signal (§K) |
| Median / distribution VPH at discovery | **Supporting (Phase 1)** | Early signal; volatile |
| Qualification pass rate | **Diagnostic** | Radar filter tuning, not lifecycle |
| Raw candidates count | **Diagnostic** | SERP noise vs filter strictness |
| Top-decile breakout rate (global-relative) | **Phase 2 primary** | Needs mature 72h + global pool |
| Median 72h absolute view growth | **Phase 2 primary** | Needs snapshot coverage |
| Worker/API error fields | **Excluded from quality** | Scheduling retry only |

**Rule:** Missing monitoring snapshots or missing 72h outcome ⇒ **missing data**, not probation failure.

---

## G. Lifecycle transition policy (design — advisory/automation later)

### G.1 General rules

- Prefer **multi-scan aggregates** over single-run reactions.
- **Infrastructure failures** (`scan.status=failed`, exceptions) affect **schedule only** (2 h retry).
- Zero-yield **successful** scans are evidence of low SERP yield, but **single zero** should not archive.
- Every transition: human-readable `status_reason` + `KeywordLifecycleEvent`.
- **Hysteresis:** separate thresholds for promote vs demote (see below).
- **No physical delete** via lifecycle engine.

### G.2 Proposed transitions (thresholds CALIBRATION REQUIRED unless noted)

| From | To | Evidence direction | Automation Phase |
|------|-----|-------------------|------------------|
| probation | active | ≥3 ok scans AND sustained non-zero new-to-DB or monitored yield | Phase 1 advisory; Phase 1F limited auto **CALIBRATION REQUIRED** |
| probation | weak | ≥3 ok scans AND repeatedly zero incremental yield | Phase 1 advisory |
| probation | archived | Operator/policy OR repeated zero yield over **N** scans **CALIBRATION REQUIRED** | Manual / late Phase 1F |
| active | weak | Yield drop over **M** scans vs rolling baseline **CALIBRATION REQUIRED** | Phase 1 advisory only initially |
| weak | active | Yield recovery over **M** scans **CALIBRATION REQUIRED** | Phase 1 advisory |
| weak | archived | Long-run zero yield + redundancy **CALIBRATION REQUIRED** | Manual preferred |
| archived | probation/active | **Manual restore** default; auto-restore **not recommended** | Manual |

### G.3 Anti-flapping (design)

- **Minimum dwell time** in active/weak before automated demotion/promotion: **CALIBRATION REQUIRED** (e.g. 7–14 days wall time or ≥N scans).
- **Cooldown after manual override:** automated engine must not change status for **T_manual** (e.g. 14–30 days) unless operator clears lock — see §L.
- **Asymmetric thresholds:** promote requires stronger evidence than demote (e.g. 2 consecutive “good” windows vs 3 “bad” windows).

---

## H. Expansion eligibility policy (design)

Re-evaluate current: active + probation (+ weak if flag); archived excluded.

### H.1 Proposed rules

| Rule | Recommendation |
|------|----------------|
| Should every probation keyword expand? | **No.** Require **≥1 successful scan** (prefer ≥3 before batch expansion) **CALIBRATION REQUIRED**. |
| Only active expands? | **Too strict** for Phase 1; allow probation **after min scans** with lower caps. |
| New probation child expands same run? | **No** (keep); extend to **no expansion until next cycle after admission**. |
| Weak expands? | **Default off** (matches `expand_weak=False`); optional manual/API flag. |
| Manual/seed special case? | Seeds may expand earlier if **active** and operator-owned — still subject to budgets. |
| Requires useful discovery evidence? | **Yes** — e.g. min distinct hits or new-to-DB count before first expansion **CALIBRATION REQUIRED**. |
| Cooldown | Keep 7 d / source; consider global per-parent cooldown across sources. |

**Strong requirement:** No recursive explosion — see §I.

---

## I. Genealogy / depth

### I.1 Current model

- `parent_keyword_id` only; `ON DELETE SET NULL`.
- Depth derivable by walking parent chain (O(depth) per query).
- Risks: broken chain if parent deleted; expensive for deep trees; ambiguous if cycles ever introduced (must forbid).

### I.2 Depth field tradeoff

| Approach | Pros | Cons |
|----------|------|------|
| **Derived depth** | No migration | Slower; parent null ⇒ unknown generation |
| **Explicit `expansion_depth` on create** | Fast budget enforcement; clear UX | Migration + backfill **CALIBRATION REQUIRED** |

**Recommendation:** Add **`expansion_depth`** (0=seed/manual root, child=parent+1) at admission time in a future stage; until then, compute depth with cap walk (max 10 hops) for policy.

### I.3 Maximum depth

| Max depth | Effect |
|-----------|--------|
| **1** | Seed → children only; safest anti-explosion |
| **2** | Seed → child → grandchild; moderate breadth |
| **Unlimited** | **Reject** — combinatorial risk |

**Recommendation:** **Max depth = 2** for automated expansion; depth 0–1 may expand (with budgets); depth 2 may **not** expand further. **CALIBRATION REQUIRED** after measuring real genealogy distribution in production events.

---

## J. Budget policy (product-level, separate from quality)

Technical caps today (expansion config) are necessary but not sufficient.

| Budget | Purpose | On exhaustion |
|--------|---------|----------------|
| Max new keywords per parent per run | Breadth | Defer remaining candidates; **not** reject as noise |
| Max new keywords global per expansion run | Global breadth | Stop creation; queue for next run |
| Max parents expanded per cycle | Orchestration | Round-robin defer |
| Max non-archived pool size | Cost ceiling | Defer admission; surface ops alert |
| Probation pool cap | Limit 6 h scan load | Defer admission to probation |
| Source quotas (optional) | Balance suggestion vs channel | Defer per source |
| Expansion cooldown (7 d / source) | Already implemented | Skip source until cooldown ends |

**Distinction:** Budget deferral records `KeywordExpansionEvent` outcome `deferred_budget` (future) — **not** lifecycle demotion.

---

## K. Overlap / redundancy policy

When two keywords repeatedly surface the same videos (high cross-keyword duplicate hits):

- **Do not merge or delete** keywords automatically.
- Treat overlap as **cost signal** in lifecycle **advisory** (supporting evidence).
- **first_discovery** attribution is scan-order sensitive — do not use alone for redundancy punishment.
- **all_hits** mode for overlap analysis; compare Jaccard-like overlap on distinct `video_id` sets over rolling window **CALIBRATION REQUIRED**.
- Conservative action: suggest weak **or** reduce expansion eligibility for redundant child, not archival on first overlap.

---

## L. Failure semantics

| Failure | Affects schedule? | Affects lifecycle evidence? | Notes |
|---------|-------------------|------------------------------|-------|
| InnerTube / API exception | 2 h retry | **No** (failed run) | Today |
| Zero raw results, ok run | Normal success interval | Weak yield signal (multi-scan) | Not immediate archive |
| Parse / filter errors in scan | May set `scan.error` | No if failed | |
| Subscriber lookup failure | Partial candidate enrichment | Diagnostic | Qualification may reject |
| Discovery worker stopped | No scans | No new evidence | Stale, not demote |
| Monitoring worker stopped | No new snapshots | 72h outcomes missing | Missing data |
| No snapshot within 72h ± tolerance | — | Outcome **missing** | Excluded from 72h aggregates |
| Empty breakout-eligible pool | — | Breakout rates undefined | Do not lifecycle-change |
| Candidate already exists | — | Expansion `existing` | Admission N/A |
| Candidate matches archived keyword | — | **Policy choice** (§E.4) | Default: no auto-reactivate |
| Parent archived mid-life | — | Child scheduling independent | Expansion from archived seed blocked |
| Expansion source failure | Logged in summary.errors | No lifecycle change | Other sources may continue |
| Pool budget full | — | Defer admission/expansion | Not weak/archived |

---

## M. Manual override policy

Existing: `PATCH /api/keywords/{id}/lifecycle` → `set_keyword_lifecycle(..., actor_source="api")`.

**Design extensions (future):**

1. **Manual change always wins** over automation for cooldown window **T_manual** (recommended 14–30 days, **CALIBRATION REQUIRED**).
2. Store `actor_source` values distinctly: `api`, `manual`, `system_recommendation`, `system_auto` (future).
3. **`status_reason`:** required human-readable string; map known codes in UI only.
4. **No automatic undo** of manual promotion/demotion during lock window.
5. Optional **`manual_lock_until`** column (future) vs inferring lock from latest lifecycle event — **CALIBRATION REQUIRED** schema decision in 1.20B.

---

## M. Phase 1 vs Phase 2 automation boundary

### Phase 1 — safe before strong 72h production evidence

**May automate (late 1.20F, with validation):**

- Admission deferral on budget/duplicate/depth rules.
- Expansion gating (min scans, depth, cooldown orchestration).
- **Advisory** lifecycle recommendations (UI only in 1.20D).

**Evidence allowed:** scan success count, hit/yield aggregates, new-to-DB counts, duplicate rates, early VPH distributions (descriptive).

**Should remain manual:** probation→active, active→weak, archival — until calibration artifacts exist.

### Phase 2 — after sufficient real 72h outcomes

**May add to lifecycle automation (1.20G+):**

- Median 72h growth, delayed breakout rates (global-relative), consistency across outcomes.
- Stronger promotion/demotion with hysteresis tied to outcome maturity coverage metrics (operations maturity block).

**Never:** conflate missing 72h snapshot with keyword failure.

---

## N. Policy decision table (concise)

| State | Scan interval | Can expand (default) | Typical next states | Automation readiness |
|-------|---------------|----------------------|------------------------|----------------------|
| **probation** | 6 h | After min scans + yield gate **CALIBRATION REQUIRED**; not same-run | active, weak, archived (manual) | Hint at 3 ok scans; auto **Phase 1D advisory / 1.20F limited** |
| **active** | 24 h | Yes, subject to cooldown/budget/depth | weak, archived (manual) | Demotion **Phase 2 preferred**; advisory Phase 1 |
| **weak** | 72 h | **No** (`expand_weak=False`) | active (manual/advisory), archived | Promotion advisory Phase 1 |
| **archived** | none | **No** | probation/active via **manual restore** | No auto |

**Expansion admission:** always creates **probation** (unless explicit manual seed class → active).

---

## O. Recommended implementation stages

| Stage | Scope |
|-------|--------|
| **1.20A** | This governance spec (done) |
| **1.20B** | Evidence read-model: per-keyword rolling aggregates from `KeywordScanRun` + hits; optional `expansion_depth`; manual lock fields if needed |
| **1.20C** | Admission service + expansion orchestration hooks (**still not** discovery worker by default); budget deferrals; depth limits |
| **1.20D** | Advisory lifecycle recommendations API/UI (“suggested weak”) — **no writes** |
| **1.20E** | Production validation scripts + calibration artifacts (overlap, yield baselines, false positive rates) |
| **1.20F** | Limited automatic transitions (probation→weak on sustained zero yield only, etc.) with manual lock |
| **1.20G** | Outcome-aware lifecycle using validated 72h metrics + hysteresis |

**Explicit non-goals until 1.20F:** no keyword score; no discovery worker expansion wiring unless a later stage explicitly approves orchestration.

---

## P. Open calibration questions

1. Minimum **new-to-database videos** per probation window to promote to active?
2. **N** consecutive zero-yield ok scans before probation→weak advisory?
3. **Max non-archived pool size** and probation share of batch (5 keywords/cycle today)?
4. **Max expansion depth** — confirm 1 vs 2 from production genealogy?
5. **Archived collision:** reactivate to probation on expansion match — yes/no?
6. **Manual seed → active** — retain forever as operator bypass?
7. **T_manual** lock duration after PATCH lifecycle?
8. Overlap threshold for redundancy advisory (Jaccard on hit sets)?
9. Minimum monitoring coverage before using any VPH/breakout signal in Phase 1 advisories?
10. Production baseline for “typical” active keyword yield (for hysteresis bands)?

---

## Document map (report sections)

This file satisfies Stage 1.20A outputs **A–P** as labeled sections above. No production code changes in 1.20A.
