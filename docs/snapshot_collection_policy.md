# Snapshot collection policy (Stage 1.12B)

## Why repeated snapshots matter

The age-aligned channel velocity baseline (Stage 1.12A) needs **real observations at multiple ages**. One T0 row per video is not enough to compare early velocity within a channel over time.

## Target checkpoints

Default ages (hours since publish): **6, 12, 24, 48, 72**.

Each checkpoint is identified by `(video_id, target_age_hours)`.

## Matching a snapshot to a checkpoint

Separate from the 1.12A *baseline comparison* window.

For checkpoint `C`:

```text
match_tolerance = max(1 hour, 0.15 × C)
acceptable age_hours ∈ [C − tolerance, C + tolerance]   (inclusive)
```

Examples:

| Checkpoint | Tolerance | Match window |
|------------|-----------|--------------|
| 6h | 1h | 5–7h |
| 12h | 1.8h | 10.2–13.8h |
| 24h | 3.6h | 20.4–27.6h |
| 48h | 7.2h | 40.8–55.2h |
| 72h | 10.8h | 61.2–82.8h |

## Due vs overdue vs expired

- **Pending** — video age has not reached the checkpoint yet.  
- **Due** — age ≥ checkpoint, no matching snapshot, still inside the recovery window, and age ≤ upper match bound (on-time band).  
- **Overdue** — age ≥ checkpoint, no match, still recoverable, but age **past** the upper match bound (e.g. woke up late; capture now at **real** age).  
- **Completed** — at least one snapshot in the match window.  
- **Expired** — no match and age > `C + max(6h, 0.50 × C)` (not scheduled for capture).

Recovery limits (initial policy):

| Checkpoint | Expires after (approx.) |
|------------|-------------------------|
| 6h | 12h |
| 12h | 18h |
| 24h | 36h |
| 48h | 72h |
| 72h | 108h |

Late captures **record true `age_hours`** (e.g. 31h for a missed 24h checkpoint). We do not pretend the observation happened at 24h.

## Who gets monitored?

Conservative eligibility: regular uploads with valid `video_id` and `published_at`; exclude Shorts, live, and known unavailable/deleted. **No** requirement to pass viral qualification or have subscribers — history should represent typical channel uploads, not only “winners.”

## When monitoring stops

- 72h checkpoint **completed**, or  
- 72h checkpoint **expired**, or  
- Video unavailable / invalid metadata (cannot compute age).

## Priority (operational, not scoring)

1. Overdue checkpoints closest to expiry  
2. Due checkpoints  
3. Lower checkpoint ages before higher  

## Planning only

This module answers **when** a video should be observed again. It does **not** run cron, workers, or YouTube fetches. Execution belongs to a later stage (1.13).
