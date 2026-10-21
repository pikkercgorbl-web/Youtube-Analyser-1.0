# Family detail — browser acceptance (port 3100)

## Build

```powershell
Set-Location frontend
$env:NEXT_DIST_DIR = ".next-acceptance"
npm run build
$env:PORT = "3100"
npm run start
```

Dev on `:3000` is not used for acceptance.

## Smoke

```powershell
node frontend/scripts/fix-family-detail-smoke.cjs before   # optional baseline
node frontend/scripts/fix-family-detail-smoke.cjs after
```

Families:

- Wide search collection: `family:kw:1497` (`minecraft challenge videos`)
- Large member list: `family:kw:181`

## Screenshots

- Before (legacy UI, first smoke in session): `artifacts/fix_family_detail_screenshots_before/`
- After: `artifacts/fix_family_detail_screenshots_after/`

Latest after smoke (`acceptance-report.json`):

- `family:kw:1497` — 25 cards, 4× «Детали видео», 4 Winners in feed
- `family:kw:181` — 29 cards, 0 Winners (участники запроса only)

## Unit tests

```powershell
cd frontend
npm run test -- --run src/components/opportunities/pattern-family-detail.test.tsx src/lib/family-member-metrics.test.ts
```
