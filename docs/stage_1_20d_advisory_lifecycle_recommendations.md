# Stage 1.20D — Advisory lifecycle recommendations

**Status:** mechanism only — **no lifecycle writes**, no scores, no auto-promote/demote/archive.

Production pool lacks mature 72h outcome calibration; recommendations are intentionally conservative.

## API

| Method | Path |
|--------|------|
| GET | `/api/keywords/recommendations` |
| GET | `/api/keywords/{keyword_id}/recommendation` |

Query: `attribution_mode=all_hits|first_discovery`, optional `lifecycle_status`, `limit` (list).

## Recommendation kinds

| Kind | Meaning |
|------|---------|
| `insufficient_evidence` | Below minimum Phase-1 observations (e.g. &lt;3 successful scans on probation) |
| `keep` | No transition suggested; may include `calibration_required=true` |
| `preliminary_review` | Operator may review; **not** an auto action; often `calibration_required=true` |
| `promote_active` / `move_weak` / `archive_candidate` / `restore_active` | Emitted **only** when calibrated rules are enabled and evidence matches (disabled in 1.20D) |

## Policy (Stage 1.20A aligned)

- Uses **Stage 1.20B** evidence only (scan + discovery yield; not 72h outcomes for strong actions).
- **`PROBATION_READY_SCAN_COUNT` (3)** — minimum successful scans before any non-`insufficient` probation advice.
- Thresholds marked **CALIBRATION_REQUIRED** in 1.20A are **not** invented → `keep` or `preliminary_review` + `calibration_required`.
- **Archived:** `keep`; restore is manual-only (no `restore_active` in 1.20D).
- **Active / weak:** `keep` + calibration pending for demotion/promotion.
- **Probation:** after min scans → `preliminary_review` (yield vs zero-yield paths); never auto `promote_active` / `move_weak` until `_CALIBRATED_*` flags enabled in a later stage.

## Enabling strong recommendations later

Toggle constants in `keyword_lifecycle_recommendation_service.py` after **1.20E** calibration artifacts exist.

## Non-goals

- No PATCH lifecycle from this API
- No keyword quality score
- No use of missing 72h data as failure signal
