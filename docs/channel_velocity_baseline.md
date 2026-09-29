# Channel velocity baseline (Stage 1.12A)

## What is this?

A **channel-relative early velocity** comparison: the candidate’s VPH at its current age versus VPH observed on **other videos from the same channel** at **similar ages**, using only persisted `VideoSnapshot` rows.

It answers: *“Is this upload moving unusually fast for this channel at this stage of life?”*

## Why age alignment matters

20,000 views at 3 hours and 20,000 views at 3 days are not the same signal. Comparisons must align on **age since publish** (hours), not lifetime totals alone.

## Age window rule

For candidate age `A` (hours):

```text
tolerance = max(3 hours, 0.20 × A)
acceptable age_hours ∈ [max(0, A − tolerance), A + tolerance]   (inclusive)
```

Examples:

| Candidate age | Tolerance | Window |
|---------------|-----------|--------|
| 6h | 3h | 3–9h |
| 12h | 3h | 9–15h |
| 48h | 9.6h | 38.4–57.6h |

## One snapshot per historical video

A channel may have many snapshots per video inside the window. Each **historical `video_id` contributes exactly one VPH**: the snapshot whose `age_hours` is closest to the candidate’s age (tie-break: earlier `captured_at`).

This prevents dense revisit schedules from overweighting one viral upload.

## Leakage prevention

Historical uploads must be strictly **before** the candidate’s observation cutoff:

1. Prefer `candidate_published_at` if present.
2. Otherwise `candidate_captured_at` (same idea as T0 baseline cutoff).

Require historical `published_at < cutoff`. Snapshots without `published_at` are excluded when a cutoff applies.

## Quality tiers

| Comparable videos | Status | Relative ratios (vs median/p75) |
|-------------------|--------|----------------------------------|
| ≥ 10 | `ok` | computed |
| 5–9 | `partial` | computed |
| 1–4 | `insufficient_history` | stats for diagnostics only |
| 0 | `unavailable` | all baseline stats null |

## Why median?

Robust to a few historical outliers; mean is secondary/diagnostic only.

## Why this is not production-ready yet

Useful coverage depends on **enough age-aligned snapshots per channel** in the database. Without revisit collection, most channels will have `unavailable` or `insufficient_history`. This module does not fetch YouTube data or fabricate early-life VPH from lifetime metrics.

## Complementary signals

- **Raw VPH** — how big/fast the video is in absolute terms.  
- **Channel-relative VPH** — how unusual it is *for this channel* at this age.  

Do not replace raw VPH with the baseline alone.
