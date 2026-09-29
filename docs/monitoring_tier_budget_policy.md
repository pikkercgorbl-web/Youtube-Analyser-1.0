# Monitoring tier and API budget policy (Stage 1.13A)

## Why tiers?

Not every discovered video deserves the same monitoring cost. Tiers control **how often** we revisit (checkpoint schedule), not whether a video is a “winner.”

## Why not only monitor winners?

Winner-only monitoring biases channel history and control groups. **Tier C** keeps representative lower-VPH uploads for trajectory learning and baselines.

## Why channel caps?

A few prolific channels could otherwise dominate snapshot/API budget. Default: **max 3 active monitored videos per channel** (higher tier, younger age, higher VPH kept first).

## Why budget fairness?

Under a hard per-cycle capture cap, Tier A/B would starve Tier C. A configurable **fair share** (default **12%** of the cycle budget) reserves slots for Tier C captures when available.

## Why percentile bands?

Absolute VPH varies by niche and channel size. Initial operational bands are **batch-relative** (defaults: top **15%** → A, next **35%** → B, remainder → C). These are **not** validated production thresholds.

## Age actionability (defaults)

| Discovery age | Effect |
|---------------|--------|
| ≤ 24h | A/B/C from VPH bands (+ optional promotion) |
| 24–48h | Tier A demoted to B unless config allows |
| > 48h | A/B demoted to C |
| > 72h | Unmonitored (stale for active monitoring) |

Videos are not deleted from datasets—only monitoring intensity changes.

## Optional channel-relative promotion

If velocity baseline status is `ok` or `partial` and `vph_vs_channel_median ≥ 3.0` (configurable), promote **at most one tier**: C→B or B→A. Never C→A directly. Missing baseline **does not** downgrade.

## Checkpoint schedules (Stage 1.12B integration)

| Tier | Checkpoints (hours) |
|------|---------------------|
| A | 6, 12, 24, 48, 72 |
| B | 12, 24, 48, 72 |
| C | 24, 72 |
| Unmonitored | none |

Pass `snapshot_collection_policy_for_tier(tier)` into the revisit planner.

## Capture budget priority

1. Overdue (closest to checkpoint expiry first)  
2. Tier A → B → C  
3. Earlier checkpoint age  
4. Higher raw VPH  
5. `video_id` tie-break  

## This is not ranking

Tiers are **operational collection policy**. User-facing breakout scoring comes later and stays separate.
