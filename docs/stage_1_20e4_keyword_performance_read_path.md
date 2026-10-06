# Stage 1.20E.4 — Keyword Performance Read-Path Performance

## A. Frontend / API call path

**Page:** `/keyword-performance` (`KeywordPerformanceDashboard`)

Per tab (Discovery / Breakout / 72h outcomes), the UI calls:

`GET /api/keywords/performance?limit=&attribution_mode=&include_breakout=&include_delayed=`

via `fetchKeywordPerformanceList()` in `frontend/src/lib/api.ts`.

**Detail:** `/keyword-performance/[keywordId]` → `GET /api/keywords/{id}/performance`.

## B. Root cause (500 / slow loads)

Default list path previously:

1. Loaded up to `limit` keywords (100–500).
2. **`build_global_breakout_bundle`** — all regular/long videos + latest snapshots (full monitorable universe).
3. **`evaluate_keywords_batch`** loaded **all** `keyword_discovery_hits` in the time window (entire table when no window), then filtered in Python.
4. Delayed 72h path loaded horizon snapshots for all attributed videos on the page.
5. No SQL pagination; work scaled with global history.

Under remote PostgreSQL this produced tens of seconds of latency, proxy/worker timeouts, and intermittent **HTTP 500** (not fixed by increasing frontend timeout).

## C. Architecture change

**Workers / batch jobs compute; UI reads snapshots.**

1. Tables `keyword_performance_global_snapshots` + `keyword_performance_keyword_snapshots` (per keyword × attribution mode).
2. **`refresh_keyword_performance_read_model()`** — full evaluation off the UI path (both `all_hits` and `first_discovery`).
3. Default **`GET /performance`** reads snapshots with SQL `JOIN` + `COUNT` + `LIMIT/OFFSET` (~few queries, bounded rows).
4. **`?live_evaluation=true`** — diagnostic live recompute for one page only.
5. **`evaluate_keywords_batch`** fixed to load hits only for requested keyword IDs; shared-video and first-owner via aggregated SQL (no full-table ORM load).

**Materialize after deploy:**

```powershell
python scripts/backfill_keyword_performance_read_model.py
```

Until backfill runs, list returns `data_source=unavailable` and empty items (no silent full-universe fallback).

## D. Query / latency targets

Measure:

```powershell
python scripts/profile_keyword_performance_api.py
```

Set `KEYWORD_PERFORMANCE_PROFILE_LIVE=1` to compare legacy live page path.

Target default snapshot list: **&lt;3s**, **&lt;10 SQL** statements, independent of total discovery hit count.

## E. Tests

`scripts/test_keyword_performance_read_1_20e4.py` — snapshot path, unavailable state, live page bounds, no full-table hit load.

Existing 1.18D1 tests use `live_evaluation=true` where full eval is intentional.

## F. Remaining limitations

- **Breakout tab** still needs global denominator in snapshot refresh (not on each UI read).
- **Detail** without snapshot falls back to single-keyword live eval (may still build global breakout if flags default true).
- **Time-window filters** force live evaluation path.
- Re-run backfill periodically (or hook discovery/monitoring cycle later) for freshness.
