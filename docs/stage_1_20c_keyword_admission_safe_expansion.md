# Stage 1.20C — Keyword Admission Policy + Safe Expansion Orchestration

**Status:** implemented (orchestrator + admission layer). Discovery worker is **not** wired to orchestration. No automatic lifecycle promotion/demotion/archive.

---

## A. Current flow before

```
run_keyword_expansion / batch
  → is_seed_eligible (archived/weak only)
  → source.expand()
  → filter_candidates()
  → persist_expansion_candidate()
       → find_keyword_by_normalized → existing event OR create_keyword(probation)
  → run caps break loop (no deferred audit)
```

| Topic | Previous behavior |
|--------|-------------------|
| Candidate filtering | `keyword_expansion_filter.py`: empty/length/parent dup/URL/numeric/batch dup |
| Duplicate handling | Normalized match → `existing`; archived row unchanged |
| TargetKeyword create | Expansion → `probation`, provenance `source_type` + `parent_keyword_id` |
| Archived | Seed blocked; collision → `existing` without reactivation |
| Provenance | `KeywordExpansionEvent` + `create_keyword` reason string |
| Caps | 20/source, 10/parent/run, 50/run, 10 seeds, 7d cooldown/source |
| Transaction | API/CLI commits; service helpers flush only |

---

## B. New flow

```
run_keyword_expansion* → run_keyword_expansion_orchestrated*
  → seed_expansion_block_reason (lifecycle, depth, PROBATION_READY scans)
  → source.expand()
  → filter_candidates() → rejected events
  → evaluate_keyword_admission() → accept | reject | defer | existing
  → persist_admission_decision() → created | existing | deferred | rejected events
```

Entry points:

- `app/services/keyword_expansion_orchestrator.py`
- `scripts/run_keyword_expansion_orchestrator.py --dry-run`
- Existing `run_keyword_expansion` / API expand delegate to orchestrator

---

## C. Admission decisions

DTO: `KeywordAdmissionDecision` (`app/services/keyword_admission_types.py`)

| Decision | Meaning |
|----------|---------|
| **accept** | May create new `TargetKeyword(probation)` |
| **reject** | Invalid/noisy/redundant (filters, same-as-parent) |
| **defer** | Valid but blocked by **budget** caps |
| **existing** | Normalized match to pool row (including archived) |

No numeric score. `reason_code` is machine-readable; `human_reason` for operators.

Policy: `app/services/keyword_admission_policy.py`

---

## D. Seed eligibility

Function: `seed_expansion_block_reason` / `is_seed_eligible_for_expansion`

| Lifecycle | Expand (default) |
|-----------|------------------|
| archived | No (`seed_archived`) |
| weak | No unless `expand_weak=True` (`seed_weak_excluded`) |
| probation | Only if `successful_scan_count >= PROBATION_READY_SCAN_COUNT` (3) (`seed_not_ready`) |
| active | Yes (subject to depth/cooldown/budgets) |

Evidence: `count_successful_scans_batch` (same semantics as lifecycle: `KeywordScanRun.status == ok`).

Keywords created in the same orchestration run cannot be used as seeds (`seed_created_same_run`). Batch seed IDs are frozen at run start.

---

## E. Depth policy

- Derived from `parent_keyword_id` chain (`keyword_expansion_depth.py`), no DB column.
- `DEFAULT_MAX_EXPANSION_DEPTH = 2` → depths **0** and **1** may expand; depth **≥ 2** blocked (`depth_limit`).
- Parent cycles → depth `None` → seed blocked.

---

## F. Budget policy

| Budget | Type | On exhaustion |
|--------|------|----------------|
| `max_new_keywords_per_seed_per_run` | Admission (run) | **defer** `parent_budget_exhausted` |
| `max_new_keywords_per_expansion_run` | Admission (run) | **defer** `global_budget_exhausted` |
| `max_non_archived_pool_size` | Pool (optional config) | **defer** `pool_budget_exhausted` |
| `max_probation_pool_size` | Pool (optional config) | **defer** `probation_budget_exhausted` |
| `max_candidates_per_source_per_seed` | Source cap | Truncates source output (unchanged) |
| `max_seeds_per_batch` | Orchestration | Frozen seed list (unchanged) |
| Cooldown 7d / source | Expansion | Skip source (unchanged) |

Optional pool caps default to **unset** (no limit) for backward compatibility; set on `KeywordExpansionOrchestratorConfig` in CLI/tests.

---

## G. Event / audit semantics

`KeywordExpansionEvent.outcome`:

- `created` — accepted + new row
- `existing` — pool match (`existing_keyword` / `existing_archived` in `rejection_reason`)
- `rejected` — filter/admission reject (`rejection_reason` = reason code)
- `deferred` — budget defer (`rejection_reason` = reason code)

Historical rows unchanged; new outcome value is additive.

---

## H. Dry-run behavior

`dry_run=True`: admission + source logic run; **no** commits; **no** events or keyword inserts; summary counts reflect simulated accepts.

---

## I. Transaction ownership

Orchestrator/admission/persistence: **flush only**, no commit/rollback. Callers: `SessionLocal` scripts, `POST .../expand` API.

---

## J. Tests

`scripts/test_keyword_admission_orchestration.py` — seed rules, admission, budgets, depth, dry-run, same-run recursion, deferred events, batch query budget.

Regression: `scripts/test_keyword_expansion.py`.

---

## K. Remaining limitations

- Discovery worker still does not call orchestrator.
- Pool/probation caps off by default until configured.
- Noise blocklist beyond structural filters not added (1.20A calibration).
- No expansion from evidence scores or 72h outcomes.

---

## L. Deliberately NOT automated

- Lifecycle promotion/demotion/archive
- Keyword quality score
- Archived auto-reactivation
- Worker-scheduled expansion

See `docs/stage_1_20a_keyword_pool_governance.md` for Phase 1 vs 2 boundaries.
