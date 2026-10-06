# Stage 1.20E — Keyword lifecycle calibration dataset + observation

## A. Goal

Reproducible **read-only** calibration layer: describe production keyword behavior, zero-yield, yield, VPH, breakout, 72h coverage, and 1.20D recommendation mix — **without** changing lifecycle or enabling calibrated automation.

## B. Dataset schema

### Keyword-level (`KeywordCalibrationRow`)

Identity, scan history aggregates, discovery yield, zero-yield streak metrics, redundancy, discovery VPH, breakout, 72h outcomes, Stage 1.20D recommendation fields, descriptive `maturity_group`.

### Scan-level (`ScanCalibrationRow`)

One row per `KeywordScanRun` with per-scan `new_to_database_video_count` from hits.

## C. Zero-yield definition

**Zero-yield scan (primary):** `KeywordScanRun.status == "ok"` **and** count of hits with `video_existed_before_discovery=false` for `(keyword_id, discovery_run_id)` **== 0**.

**Not zero-yield:** failed scans; ok scans with any new-to-database video.

**Also tracked separately:**

- `zero_raw_result` — ok scan, `raw_candidates == 0`
- `zero_persisted_result` — ok scan, `persisted_videos == 0`

Keyword rates use **successful scans only** as denominator.

## D. Scan-level semantics

`scan_failed` ⇔ status ≠ `ok`. Failed scans never increment zero-yield counts.

## E. Keyword-level semantics

Aggregates from 1.20B evidence + scan-level zero-yield math. Missing VPH/72h remain **null**, not zero.

## F. Breakout semantics

Uses existing global-relative breakout bundle when `include_breakout=true`. Reports eligible counts and rates with sample-size context.

## G. 72h coverage

Existing delayed-outcome methodology unchanged. Report includes `CALIBRATION_NOT_READY` when valid outcome count &lt; 30.

## H. Association methodology

Spearman ρ via `spearman_correlation()`; computed only when **n ≥ 10** valid pairs; otherwise `rho=null`.

## I. Calibration readiness

Per-rule `READY` / `PARTIALLY_READY` / `NOT_READY` for promotion, demotion, archive, 72h — **calibration data readiness**, not keyword quality.

## J. CLI usage

```powershell
python scripts/analyze_keyword_lifecycle_calibration.py --json
python scripts/analyze_keyword_lifecycle_calibration.py --status probation --export-csv ./calibration_out
python scripts/analyze_keyword_lifecycle_calibration.py --no-breakout --no-delayed
```

## K. API

- `GET /api/keywords/calibration/summary`
- `GET /api/keywords/calibration/dataset`

## L. Tests

`scripts/test_keyword_lifecycle_calibration.py`

## M. Explicit non-goals

No lifecycle writes, no `_CALIBRATED_*` enablement, no scores, no invented thresholds, no worker wiring.
