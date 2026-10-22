# Fix 2C — browser acceptance (port 3100)

- Build: `NEXT_DIST_DIR=.next-acceptance` + `npm run build`
- Server: `PORT=3100 npm run start` (isolated dist)
- Smoke: `node frontend/scripts/fix-2c-detail-smoke.cjs`
- Screenshots: `artifacts/fix_2c_screenshots/` (`01`–`04`, desktop + 390px)
- Terminology: `artifacts/fix_2c_terminology_map.md`

Latest smoke (`acceptance-report.json`):

- Winner: `JF2A0GZzezQ` — baseline panel present (available or unavailable) on expanded cards
- Keyword family: `family:kw:1497`
- Topic family: `family:topic:86b8434548938bdc`

Backend tests: `python scripts/test_attention_views_measurement_2c.py`, `python scripts/test_opportunity_family_presentation_2b.py`

Frontend tests: vitest `channel-baseline-copy`, `views-measurement-status`, `pattern-family-detail`, `saved-research-format`
