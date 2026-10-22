# Fix 3B.1 — UI acceptance + missing retry cooldown

## 1. Browser acceptance (Fix 3B UI)

- Остановлен только процесс **:3100** (acceptance); **:3000**, backend, workers не трогались.
- Перезапуск: `NEXT_DIST_DIR=.next-acceptance`, `PORT=3100`, `npm run start`.
- Smoke: `node frontend/scripts/fix-3b-keywords-monitoring-smoke.cjs` → **ok**
- Артефакты:
  - `artifacts/fix_3b_acceptance_screenshots/01-keywords-queue-context.png`
  - `artifacts/fix_3b_acceptance_screenshots/02-monitoring-cycles-partial-columns.png`
  - `artifacts/fix_3b_acceptance_screenshots/acceptance-report.json` (HTTP samples + console)

**Проверено в UI/API:** `/keywords` — due + **720** unique scans / 24h + пояснение про «Пора просканировать»; `/monitoring` — колонки **«Нет в API»** / **«Ошибки захвата»**, cycles API 200, partial с `missing=1`, `fetch_failed=0`.

## 2. Missing retry cooldown

**Файлы:** `app/services/monitoring_missing_retry.py`, hook в `run_monitoring_cycle` перед `allocate_capture_budget`.

**Источник данных:** последняя строка `monitoring_capture_outcomes` с `outcome='missing'` на пару `(video_id, checkpoint_age_hours)`. `fetch_failed` / validation / persistence **не** подавляют повтор.

**Интервал (не произвольный):**

- База: `max(checkpoint_match_tolerance_hours, 2 × worker_interval)` — для cp **24h** tolerance = **3.6h** (15%×24, min 1h), worker 900s → cooldown **≥ 3.6h**.
- До **expiry** (`checkpoint + recovery`, для 24h → 36h video age): если до expiry осталось меньше базы, cooldown сжимается до **2× worker interval** (~30 min), чтобы успеть последнюю попытку; в последний worker-tick перед expiry — **0** (не блокировать финальную попытку).
- Checkpoint **не** помечается completed/terminal; только отложен выбор в budget.

**Лог:** `missing_retry_suppressed=N` в `[MONITORING_CYCLE]`.

## 3. Tests

| Script | What |
|--------|------|
| `scripts/test_monitoring_missing_retry_cooldown_3b1.py` | suppress / after cooldown / other video & cp / fetch_failed |
| `scripts/test_monitoring_dry_run_no_outcomes_3b1.py` | dry-run, no YouTube call |
| `scripts/test_monitoring_missing_retry_3b.py` | checkpoint stays due without snapshot |

## 4. Residual risk

- Cooldown вступает в силу после **перезагрузки Python-процесса**, который выполняет `run_monitoring_cycle` (monitoring worker / backend). Workers намеренно не перезапускались в этой задаче — до деплоя кода `YXodhWM0RiI` может ещё 1–2 цикла идти по старому поведению.
- Пока checkpoint **due** и cooldown активен, цикл может быть **ok** (0 selected), а в UI очередь видео всё ещё «due» — это ожидаемо; partial/missing считаются только по **фактически отправленным** запросам.
- Очень старые missing без успешного snapshot до expiry: checkpoint уйдёт в **expired** по существующей policy, без нового terminal-state.

## Diff (summary)

- **+** `monitoring_missing_retry.py`
- **~** `monitoring_cycle.py` — filter + `missing_retry_suppressed_count`
- **~** `fix-3b-keywords-monitoring-smoke.cjs` — HTTP/console, screenshot timeout
- **+** tests `*_3b1.py`
