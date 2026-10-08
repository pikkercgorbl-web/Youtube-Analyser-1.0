# Radar frontend redesign

Base: `feature/stage-1-22c-saved-topics`, commit `9dae8cc1cdbfc006614eefe34751771b45bdda9b` (GitHub fetched 2026-10-08). Main was older. No AGENTS.md present in checkout.

## Map of responsibilities

| Navigation | Route | Question / data | Actions |
|---|---|---|---|
| Возможности | /opportunities | Which videos, channels and groups deserve investigation? Existing Attention snapshot APIs | Search/sort videos, YouTube, video dynamics, compare group, save topic |
| Сохранённые темы | /saved-topics, /saved-topics/[id] | What did I select and how has it changed? Frozen snapshot, observations, events | Notes/tags/status, feedback, own test, archive/restore |
| Результаты решений | /validation | What have I evaluated/tested? Existing saved-topic cohort report | Period by date of saving, ratings and test results |
| Ручной поиск / Анализ конкурентов | /, /mass-analysis | Explore a query or competitor manually | Existing research actions preserved |
| Поисковые запросы / Отдача запросов | /keywords, /keyword-performance | Where should discovery search, what does it return? | Existing query controls, provenance, performance filters |
| Наблюдение за видео | /monitoring | When are videos measured? | Existing queue, ranking, checkpoints, detail links |
| Состояние системы | /operations | Is collection healthy? | Existing worker/cycle/snapshot diagnostics |

## Existing functionality verified in source

- Saved topics already have real API persistence, feedback, timeline and archive/restore. Kept these actions. Removed invalid nested button/link from saved-topic action.
- No per-video saved-item API found in current routes/client. No fake save-video button added; this requires a separate backend contract.
- Family list supplies participating video IDs but not titles for every member. Cards show up to three example thumbnails linked to YouTube; full existing detail route retains hydrated member video information. These examples are not claimed to be ranked winners.
- Keyword/topic provenance alone is not format evidence. Such families now appear under “Подборки по теме”; phrase-based groups retain cautious language. Counts/ranking/eligibility unchanged.
- Monitoring already has video detail routes. Video cards link to those routes; missing observations remain a valid empty state.

## Implementation

Shared typography, surfaces, contrast, focus and reduced-motion styles; three navigation groups; sticky desktop navigation and mobile menu with Escape; 16:9 video thumbnails; full readable titles; search/sort and progressive 12-item reveal; three opportunity sections; grouping details behind disclosure; saved topic and validation copy/empty states; consistent page names for operational screens. All 50 returned candidates remain reachable.

No API schema, ranking, database, worker, budgets, scheduling or production state changes. No new runtime UI dependency. Historical observations and frozen data are untouched.

## Verification

- `npm run build`: passes.
- `npm test`: 127 tests pass (16 suites); existing tests that expected pre-Saved Topics disabled stubs were updated to the existing persistence contract.
- Browser script: `frontend/scripts/redesign-browser-smoke.cjs`. Install Playwright separately for test tooling, run an isolated production frontend then `node scripts/redesign-browser-smoke.cjs`. Optional `RADAR_PREVIEW_URL`, `CHROMIUM_EXECUTABLE`, `PLAYWRIGHT_MODULE`, `RADAR_SCREENSHOT_DIR`.
- Browser checks: search, sorting, section switch, topic distinction, save/open topic, archive/restore, empty report, 390px viewport overflow, menu Escape, unavailable snapshot and error/retry. Results in `browser-check.json`.
- Screenshots in this directory use clearly isolated browser API fixtures, not the user's current database; fixture interception exists only in the test script, never in application code.
- YouTube images unavailable in this environment: screenshots demonstrate the missing-thumbnail fallback. Actual loaded thumbnails still require visual confirmation on the user's connected machine.
- Working PostgreSQL on the user's laptop was not reachable here. Real-data integration against that database was not executed. Build and browser preview used separate sequential processes, no concurrent dev/build writers.

## Remaining functional gaps

Per-video saving; actively tracking similar videos; production-format / audience / production-cost qualification; LLM integration and daily experiment reports. These are not silently implemented or promised by this visual update. Existing Saved Topics validation counts only saved themes, not individual saved videos.
