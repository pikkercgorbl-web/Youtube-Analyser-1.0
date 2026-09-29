# Breakout ranking v1 (Stage 1.17B)

## Purpose

Order **breakout-eligible** monitored videos for analyst attention by last-known early velocity (VPH).

This is **not** monitoring tier A/B/C and **not** capture-budget priority (`sort=priority`).

## Population

Included when all hold:

- Regular monitorable video (not SHORT / LIVE)
- `published_at` available (via monitoring state)
- `age_hours <= max_age_monitoring_hours` (default 72h)
- VPH computable (`raw_vph` non-null)

**Not** gated by channel cap, global cap, tier, due/overdue, or discovery qualification.

## Algorithm (`breakout_v1`)

1. VPH descending  
2. Views descending (tie-break)  
3. `video_id` ascending  

No weighted score.

## Staleness limitation

Breakout v1 ranks by **last-known** VPH from the batched monitoring state (latest snapshot when present, else views ÷ age).

Videos **excluded from the active capture pool** may receive fewer or no new snapshots; their views may age without refresh. Rank can drift down over time even if the video was hot at discovery.

**Do not** fix this by requiring tier A/B or active-pool membership for breakout eligibility.

## API

`GET /api/monitoring/videos?sort=breakout_v1` — cap-independent population with rank metadata.

`GET /api/monitoring/videos?sort=priority` — unchanged operational active-after-caps list.

## Historical validation (Stage 1.17C)

Offline evaluation against frozen cohort artifacts (production `breakout_ranking_service` imported as-is):

| Artifact | SHA256 |
|----------|--------|
| [breakout_rank_v1_evaluation.json](../artifacts/breakout_rank_v1_evaluation.json) | `5f3b046fe3145718fed1ae542c6b3d7c67d4f0d23c7c53bba3ad7928cb93967f` |
| [breakout_rank_v1_evaluation.md](../artifacts/breakout_rank_v1_evaluation.md) | `0f8e7973ba4923ffae7c7eeb945e7c962db4a02c6aa75663ecabc44d8a98c40b` |

Frozen joined inputs (unchanged):

- `radar_outcome_joined_T0_T67_20260914_124311.jsonl` — `4ad54a3725a8a777e63436bba26308fbcccb8e17227355f9c8d3380c8412dc11`
- `radar_outcome_joined_stage110_T0_to_T72_stage110_20260914_141029.jsonl` — `69613d88581a8f2c45bee441ddd5e40cec64c1ca06a79022d9412dc30e26e504`

Regenerate: `python scripts/run_breakout_rank_v1_evaluation.py`

## Frontend (Stage 1.17D)

Monitoring dashboard sort **Breakout (VPH)** → `sort=breakout_v1`. Operational sort **Приоритет** remains default (`sort=priority`).
