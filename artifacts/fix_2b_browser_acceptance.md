# Fix 2B / Fix 1A — browser acceptance (local)

Backend: `.\scripts\start-backend.ps1` (repo root, port 8000).

## Isolated production UI (recommended for smoke)

Does not share `.next` with `next dev` on port 3000.

```powershell
# From repo root
Set-Location "c:\Projects\Сайт анализ ниш1\frontend"
$env:NEXT_DIST_DIR = ".next-acceptance"
npm run build
$env:PORT = "3100"
npm run start
```

In another terminal:

```powershell
Set-Location "c:\Projects\Сайт анализ ниш1\frontend"
$env:RADAR_ACCEPTANCE_URL = "http://127.0.0.1:3100"
node scripts/fix-2b-winner-link-smoke.cjs
```

Screenshots: `artifacts/fix_2b_acceptance_screenshots/`  
Report: `artifacts/fix_2b_acceptance_screenshots/acceptance-report.json`

## Daily dev frontend

From **repo root** (not `cd frontend && ...`):

```powershell
Set-Location "c:\Projects\Сайт анализ ниш1"
.\scripts\start-frontend.ps1
```

Equivalent from `frontend/`: `.\scripts\start-frontend.ps1` (delegates to repo root).

Do not run `npm run build` while `next dev` is using the same `NEXT_DIST_DIR` (default `.next`).

## pattern_candidate_build

Appears in `attention_runs.notes_json` after the next scheduled Attention refresh only.  
Read-only check: `python artifacts/read_pattern_candidate_build_notes.py`
