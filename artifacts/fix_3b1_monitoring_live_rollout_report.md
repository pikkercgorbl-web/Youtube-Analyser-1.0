# Fix 3B.1 — live monitoring rollout (one cycle)

## Before

| Item | Value |
|------|--------|
| DB | `127.0.0.1:5433/youtube_radar_restore_check` (preflight OK) |
| Monitoring worker PID | **6604** — `run_monitoring_worker.py --interval-seconds 900` |
| Lock | `LAPTOP-K7VTSODB:1`, status running |
| Last finished cycle | `monitoring_20261013T105529Z_6463a1f1` — **partial**, selected **12**, inserted **11**, **missing 1** |
| Unfinished cycle | none |

**YXodhWM0RiI / cp24:** last missing `2026-10-13T10:55:29Z`; cooldown **active**; **retry_at** `2026-10-13T14:31:29Z` (~3.6h = match tolerance for 24h checkpoint).

## Action

1. Stopped **only** PID **6604** (monitoring worker).
2. Started **one** instance via `scripts/start-monitoring.ps1` → new PID **31588** (DB check repeated).
3. Lock **not** cleared manually; new worker re-acquired lock at `2026-10-13T11:03:06Z`.

Discovery, outcome, backend, frontend, schedules — **unchanged**.

## First cycle after restart

| Field | Value |
|-------|--------|
| run_id | `monitoring_20261013T110306Z_6c86b566` |
| finished | `2026-10-13T11:03:10Z` |
| status | **ok** |
| selected / inserted / missing | **14 / 14 / 0** |
| fetch_failed | 0 |

**YXodhWM0RiI:** **no** row in `monitoring_capture_outcomes` for this run → **not sent** to YouTube batch while cooldown active. Last missing unchanged (history not reset).

**Other due videos:** cycle selected **14** captures (vs 12 before), all inserted — no sign of global blockage.

**Processes:** single `run_monitoring_worker` PID **31588** after restart.

## Evidence vs cooldown

- Prior partial cycle: `missing=1` with repeated YXodh missing history.
- Post-restart cycle: `missing=0`, status **ok**, YXodh absent from outcomes, **retry_at** still in the future → consistent with **missing retry filter**, not with “video disappeared from queue” alone.

**Live-run limit:** direct proof is absence of API attempt (no outcome row) + active cooldown window; forced-time planner proof remains in `scripts/test_monitoring_missing_retry_cooldown_3b1.py`.

## Residual risk

- Worker now sleeps **900s** until next cycle; YXodh remains due at cp24 until capture succeeds or checkpoint **expires** (~36h age per existing policy).
- Next YXodh API attempt expected after **retry_at** (~14:31 UTC) if still due and not expired.

Machine-readable: `artifacts/fix_3b1_monitoring_live_rollout_report.json`
