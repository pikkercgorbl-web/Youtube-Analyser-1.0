# Monitoring frontend (Stage 1.14B)

## Route

- Dashboard: `/monitoring`
- Video detail: `/monitoring/videos/[videoId]`

Navigation: sidebar item **«Мониторинг»**.

## API dependencies

All data comes from `/api/monitoring/*` via `frontend/src/lib/api.ts`:

- `getMonitoringStatus`
- `getMonitoringOverview`
- `getMonitoringVideos`
- `getMonitoringVideo`
- `getMonitoringSnapshots`
- `getMonitoringCycles`

No mocks in production components.

## Filters (videos table)

| Control | Query param |
|---------|-------------|
| Tier | `tier=A|B|C` |
| Status | `status=due|overdue|pending|active|stopped` |
| Sort | `sort=priority|vph_desc|views_desc|age_asc|latest_snapshot_desc` |
| Title search | `keyword` (substring on title) |

Pagination: `limit=50`, `offset`.

## Polling

- Default interval: **60 seconds**
- Paused when `document.visibilityState !== "visible"`
- Manual **Обновить** triggers full reload
- Background refresh keeps previous table data visible (`isBackground` skips full-page skeleton)

## Empty states

- No monitored videos: explains eligibility via `videos` table
- No latest cycle: no fake zeros
- No cycle history / no snapshots on detail

## Worker UI

Read-only. Labels reflect DB lock state (`running` / `stale` / `stopped` / `unknown`), not a guaranteed live process heartbeat.

**No** Start/Stop worker buttons (backend has no safe control endpoints).

## Detail page

Implemented in this stage:

- Summary metrics
- Checkpoint table
- Channel baseline block (when API returns it)
- Snapshot history table (no charts yet)

## Known limitations

- Overview + list recompute on backend each request (can be slow on large DB)
- List baseline columns usually empty (by design)
- Discovery radar UI remains separate (`/explosive-channels`)
- No WebSocket/SSE/alerts

## Tests

```bash
cd frontend
npm test
```

Vitest + Testing Library cover rendering, filters, worker labels, and error isolation patterns.
