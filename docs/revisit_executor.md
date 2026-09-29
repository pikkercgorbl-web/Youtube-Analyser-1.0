# Revisit executor (Stage 1.13B)

## What does the executor do?

Turns **approved** `SnapshotCaptureRequest` objects into real **`VideoSnapshot`** rows: batch `videos.list` fetch, normalize observations, derive age/VPH, persist append-only.

## What does it NOT do?

- Does not choose videos or tiers (Stage 1.13A / 1.12B upstream)
- Does not schedule itself (Stage 1.13C later)
- Does not rank breakouts or change qualification
- Does not mark checkpoints “completed” in a schedule table — the planner derives that from snapshots

## Why batch requests?

`YouTubeApiClient.get_videos()` already chunks at **50** IDs per call. The executor reuses that path for quota efficiency.

## Why missing video is not fatal?

Returned IDs may omit deleted/private/unavailable videos. Those requests get `status=missing`; other videos in the batch continue.

## Why captured_at must be real?

Metrics and checkpoint matching use **true observation time**, not the checkpoint target age. Overdue captures record the actual age at fetch.

## Subscribers

`get_videos()` does not include subscriber counts. The executor accepts an optional **preloaded** `subscribers_by_channel_id` map only — **no** per-video channel API calls. Snapshots persist successfully with `subscribers=NULL`.

## Idempotency

Before fetch/persist, the executor checks for an existing snapshot with the same `(video_id, source, run_id)`. Stable `run_id` from the planner (checkpoint identity) prevents duplicate work on rerun. DB unique constraint also guards exact `(video_id, captured_at, source, run_id)` collisions.

## Manual execution

Pipeline: Discovery → Tier → Planner → Budget allocator → **Executor** → VideoSnapshot. Trigger the executor explicitly; no background loop in this stage.
