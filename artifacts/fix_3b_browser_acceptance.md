# Fix 3B — browser smoke

Backend pool-summary (no UI): `GET http://127.0.0.1:8000/api/keywords/pool-summary`

## Acceptance UI (port 3100)

After pulling Fix 3B, rebuild and restart the isolated server (does not touch discovery/monitoring workers):

```powershell
Set-Location "c:\Projects\Сайт анализ ниш1\frontend"
$env:NEXT_DIST_DIR = ".next-acceptance"
npm run build
# stop existing process on 3100, then:
$env:PORT = "3100"
npm run start
```

Smoke:

```powershell
Set-Location "c:\Projects\Сайт анализ ниш1\frontend"
$env:RADAR_ACCEPTANCE_URL = "http://127.0.0.1:3100"
node scripts/fix-3b-keywords-monitoring-smoke.cjs
```

Screenshots: `artifacts/fix_3b_acceptance_screenshots/`  
Report: `artifacts/fix_3b_acceptance_screenshots/acceptance-report.json`

**Note:** A build with `.next-acceptance` was produced during Fix 3B; until the process on **3100** is restarted, the running server may still serve the pre-3B bundle (smoke will miss `keyword-pool-queue-context`).
