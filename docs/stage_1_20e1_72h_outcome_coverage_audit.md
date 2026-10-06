# Stage 1.20E.1 — 72h Outcome Coverage Audit

## A. Previous semantics

**Intended (Stage 1.18A):** discovery-anchored delayed outcome.

- Baseline: first `KeywordDiscoveryHit` per `(keyword_id, video_id)` → `discovered_at`, `views_at_discovery`.
- Maturity: `maturity_at = discovered_at + 72h` (UTC).
- Target snapshot time: `target = discovered_at + 72h`.
- Match: nearest `VideoSnapshot` with non-null `views` where `|captured_at - target| ≤ 12h` (`HORIZON_SNAPSHOT_TOLERANCE_HOURS`). No interpolation.

**Attributed:** keyword×video observations in the active attribution mode (`all_hits` unique videos per keyword; baseline still first hit per pair).

**What the calibration report showed before this fix:**

| Field | Value |
|-------|------:|
| attributed | 39,942 |
| matured | ~7,416 |
| valid | 0 |
| missing | 39,942 |

`missing` equaled **all attributed**, including **pending** observations still inside the 72h window.

## B. Actual bug(s)

1. **`missing_72h_outcome_count` in batch evaluation** (`keyword_performance_evaluation.evaluate_keywords_batch`): incremented for every observation without a valid outcome, including **pending** (`now < discovered_at + 72h`), missing baselines, and matured-without-snapshot alike. Summing across keywords reproduced `missing ≈ attributed`.

2. **SQL maturity aggregate** (`operations_maturity_sql.compute_maturity_aggregate_sql`): `missing = eligible_count - valid_count` where `eligible` only included matured rows **with** `views_at_discovery`, while `matured_72h_count` included all time-matured rows → **`matured ≠ valid + missing`**.

3. **Legacy operations maturity** early-returned when no matured rows had views, leaving `missing = 0` despite `matured > 0`.

4. **Case review** listed keywords with `valid_72h_outcome_count = 0` in `valid_72h_outcomes`.

5. **Not a counting bug:** `valid = 0` on production despite thousands matured — snapshot **timing** vs discovery anchor (see E, H).

## C. Corrected semantics

| Term | Definition |
|------|------------|
| **Attributed** | All keyword×video observations in attribution mode |
| **Pending** | `now < discovered_at + 72h` |
| **Matured** | `now ≥ discovered_at + 72h` |
| **Valid** | Matured + `match_horizon_outcome` succeeds (views + snapshot within tolerance of `discovered_at + 72h`) |
| **Missing** | Matured − valid (includes no views at discovery, no snapshot, or only out-of-window snapshots) |

**Invariant:** `matured_72h_count == valid_72h_outcome_count + missing_72h_outcome_count`  
**Invariant:** `attributed == pending + matured` (time partition)

Pending observations are **never** counted as missing.

## D. Monitoring checkpoint vs discovery-delay analysis

Monitoring schedules checkpoints by **video age since `published_at`** (6h / 12h / 24h / 48h / 72h).

Keyword delayed outcome targets **`discovered_at + 72h`**.

These clocks diverge when discovery is late relative to publish:

- Video published 40h ago; keyword discovers it now.
- Monitoring “72h video-age” snapshot ≈ 32h from now.
- Keyword outcome target ≈ 72h from now.

Stage 1.18A explicitly chose **discovery-delay** for outcomes; `videos_with_snapshot_72h_count` (max `age_hours`) is informational only.

**Implication:** Even with healthy monitoring, many matured keyword observations will lack an in-window snapshot unless a capture happens near `discovered_at + 72h` (ad hoc monitoring, later cycles, or future alignment work). This stage does **not** change monitoring policy or tolerance.

## E. Snapshot coverage diagnostics

Read-only helper: `compute_horizon_coverage_diagnostics()` (loads all snapshots for matured videos to classify coverage).

Calibration CLI: `python scripts/analyze_keyword_lifecycle_calibration.py --include-delayed --72h-diagnostics`

### Production findings (pool limit 5000 keywords, 2026-09-30 run)

| Metric | Count |
|--------|------:|
| attributed | 39,942 |
| pending | 31,481 |
| matured | 8,461 |
| valid | 0 |
| missing | 8,461 |
| matured with any snapshot | 491 |
| in-window snapshot | 0 |
| only outside-window snapshot | 491 |
| no snapshot | 7,970 |

**Nearest snapshot delta to `discovered_at + 72h` (491 with any snapshot):**

- p50 ≈ 71.70h  
- p75 ≈ 71.79h  
- p90 ≈ 71.91h  

Interpretation: stored snapshots cluster near **discovery** (≈0.3h after discovery), not near **discovery + 72h**. They are ~72h **early** relative to the outcome target — consistent with early video-age monitoring, not wrong matching code.

## F. Invariants

- `matured = valid + missing` (enforced in evaluation, SQL, legacy maturity, calibration summary flag `matured_equals_valid_plus_missing`).
- Pending excluded from missing.
- Constants unchanged: `HORIZON_HOURS = 72`, `HORIZON_SNAPSHOT_TOLERANCE_HOURS = 12`.
- No lifecycle writes in this stage.

## G. Tests

`scripts/test_72h_outcome_coverage.py` (12 scenarios): pending vs missing, valid/missing paths, tolerance, nearest snap, SQL invariant, attribution timestamps, timezone, case review filter, diagnostics partition, tally helper.

Included in `scripts/run_fast_regressions.py`.

## H. Remaining architectural issue

**Zero valid outcomes** on production is expected under current monitoring design + discovery-delay semantics until either:

- monitoring adds discovery-relative checkpoints, or  
- product adopts video-age-72h outcomes (would contradict Stage 1.18A without explicit re-spec).

Do **not** widen tolerance or interpolate snapshots to mask this.

## I. Lifecycle calibration proceed?

**Yes for report integrity** — counts and diagnostics are now trustworthy.

**No for rule calibration depending on 72h growth** — `valid_72h_outcome_count = 0`; status remains `CALIBRATION_NOT_READY` for 72h-linked rules. Continue yield/redundancy/VPH observation; treat 72h associations as blocked until coverage improves or semantics are revised at product level.
