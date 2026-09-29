# Video snapshot storage (Stage 1.11)

## What is a snapshot?

A **snapshot** is one historical observation of a single YouTube video at one capture moment: views, subscribers, format flags, and derived metrics (VPH, age in hours) computed from what was known **at that time**.

The same `video_id` can have many snapshot rows over days or weeks. Older rows are never updated when newer data arrives.

## Why do we need it?

Breakout and revisit logic depend on **trajectory**, not only the latest view count. File-based validation cohorts are useful for experiments, but automatic Radar needs durable, queryable time series in the database.

## What it enables later?

- T0 → T24 → T48 → T72 growth curves  
- Velocity persistence and age-aligned comparisons  
- Channel-relative early performance  
- Historical channel velocity baselines  
- Automatic revisit scheduling  

## What it does NOT do yet?

- Prediction or scoring  
- Ranking or alerts  
- Production qualification changes  
- Automatic writes from live Radar (storage is opt-in via explicit service calls)  

## Semantics

- **Append-only:** inserts only; no in-place overwrites.  
- **Idempotency:** unique key `(video_id, captured_at, source, run_id)` prevents duplicate writes from the same refresh job.  
- **NULL, not zero:** missing metrics stay `NULL`; derived fields are not fabricated.  
- **Discovery vs snapshot:** `RadarCandidate.discovery_*` fields are separate; snapshots do not mutate discovery state.  

## Future flow (not implemented here)

Discovery → Candidate → Snapshot T0 → revisit later → Snapshot T+N → historical trajectory analysis.
