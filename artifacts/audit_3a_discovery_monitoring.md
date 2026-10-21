# Fix 3A — аудит Discovery due + Monitoring «Частично»

**Снимок:** `2026-10-13T10:23:45Z` (UTC)  
**БД:** PostgreSQL `127.0.0.1:5433/youtube_radar_restore_check` (read-only)  
**Машиночитаемые числа:** `artifacts/audit_3a_discovery_monitoring_report.json`  
**Скрипт:** `artifacts/audit_3a_discovery_monitoring_readonly.py`

---

## 1. Откуда «N уже пора просканировать»

### Код и единица счёта

| Слой | Файл | Правило |
|------|------|---------|
| UI (страница **Поисковые запросы** `/keywords`) | `frontend/src/lib/keyword-pool-summaries.ts` → `computePoolMetrics` | `dueNow` = число строк в **загруженном списке** `TargetKeyword`, для которых `isKeywordDue(row, now)` |
| UI due | `frontend/src/lib/keyword-pool-format.ts` | `archived` → не due; `next_scan_at == null` → **due**; иначе due если `next_scan_at <= now` |
| Backend (Operations, тот же смысл) | `app/services/keyword_schedule_state.py` `is_keyword_due` | Идентичная логика |
| Backend aggregate | `app/services/operations_overview_queries.py` `count_keywords_due_batch` | SQL `SUM` по **уникальным** `target_keywords.id`, не archived |

**Единица:** одна строка **`target_keywords`** (уникальный TargetKeyword), **не** scan task и **не** discovery_run.

**Момент времени:** `Date.now()` на клиенте в момент последней загрузки `/api/keywords` (poll 60 с). Число на полоске summary **не** берётся из Operations API.

**Загрузка данных:** `fetchTargetKeywords()` → `GET /api/keywords` без пагинации — **весь пул** в память, затем клиентский подсчёт (`keyword-pool-dashboard.tsx`).

### Текущие числа (снимок)

| Метрика | Значение |
|---------|----------|
| Не archived | **1866** |
| Due now (backend batch) | **1659** |
| Due now (UI would match, same rules) | **1659** |
| `next_scan_at IS NULL` among due | **0** |
| Due next 24h (ещё не due) | **207** |

**Про «1849» из аудита пользователя:** на этом снимке **1659** due (~89% рабочего пула). **1849** могло быть на другой минуте/до серии сканов или при другом понимании строки (близко к **1866** «в рабочем пуле»). **Факт:** почти весь пул одновременно в состоянии due — это не баг счётчика, а накопившаяся очередь по расписанию.

### Разбивка due

**Lifecycle (due):** probation **1606**, active **53**  
**Lifecycle (все не archived):** probation **1786**, active **80**

**source_type (due):** suggestion **1592**, seed **53**, related **10**, channel **4**  
**source_type (все):** suggestion **1772**, seed **80**, related **10**, channel **4**

**Просрочка `next_scan_at` (среди не archived, bucket ≠ not_due):**

| Bucket | Count |
|--------|------:|
| overdue 0–1 h | 31 |
| overdue 1–24 h | 738 |
| overdue 1–7 d | 890 |
| null_next_scan_at | 0 |

*(Сумма bucket’ов > due_now, т.к. в bucket попадают и ключи с `next_scan_at` в будущем только для `null`/`not_due`; due-only overdue mass — доминирует 1–7 d.)*

---

## 2. Discovery: история 24–72 ч (факты, не «стало due»)

**Ограничение:** журнала событий «ключ стал due» **нет**. Ниже только **`keyword_scan_runs`**.

| Окно | Scan rows | Distinct keyword_id | Distinct discovery_run_id | status |
|------|----------:|--------------------:|----------------------------:|--------|
| 24 h | 728 | 728 | 182 | `ok`: 728 |
| 72 h | 2232 | 1861 | 558 | `ok`: 2232 |

**Факт:** за 24 ч просканировано **728** уникальных ключей; за 72 ч — **1861** (≈ весь пул). **Failed scan runs за 72 h:** **0** (`discovery_repeat_failed_keywords_72h`: []).

**Пропускная способность (факт):** последние циклы — **4** keyword_scan на `discovery_run_id` (~1 слот exploration из batch 5). Интервал worker по умолчанию **300 с** (`discovery_worker_runtime.py`). ≈ **4 ключей / ~5–10 мин** → порядка **24–48 ключей/ч** при непрерывной работе.

**Гипотеза (не измерялась напрямую):** due ~1659 при ~30 ключей/ч даёт **десятки часов** полного опустошения без притока новых due — согласуется с bucket **890** просрочка 1–7 d.

**Worker (факт):** `discovery_worker_state`: `running`, last cycle finished `2026-10-13T10:19:12Z`, `last_cycle_status`: **ok**, `last_error`: null. **Не** зависший worker.

**Отбор в цикл:** `select_discovery_keywords` — до **batch_size** (default 5, фактически 4 seed) из **всех due**, сортировка по overdue ↓ (`discovery_keyword_selection.py`).

---

## 3. «Поисковые запросы» vs «Отдача запросов»

| | **Поисковые запросы** `/keywords` | **Отдача запросов** `/keyword-performance` |
|--|-----------------------------------|---------------------------------------------|
| **Данные** | Живые строки `TargetKeyword` (расписание, lifecycle, source) | Предагрегированные метрики performance (discovery / breakout / 72h) |
| **Действия** | Фильтры, сортировка, просмотр **next_scan_at**, lifecycle labels; **нет** запуска scan из UI | Выбор семейства метрик, attribution, лимит, поиск; drill-down на keyword |
| **Решения** | Какие запросы в пуле, насколько они «просрочены» для **планового** Discovery | Какие запросы **исторически** давали видео / breakout / исходы 72h |
| **Due** | Явно: «N уже пора просканировать» | Не очередь; «отдача» ≠ «пора сканировать» |

---

## 4. Monitoring — правило «Частично»

### Код

```187:202:app/services/monitoring_cycle.py
def _resolve_cycle_status(...):
    ...
    if summary.total_failed_count > 0 or summary.failed_batch_count > 0:
        return "partial"
    return "ok"
```

`total_failed_count` = `fetch_failed + missing + validation_failed + persistence_failed` (`revisit_executor.py`).

**Deferred** в partial **не входит** — только ошибки исполнения выбранных capture requests.

**UI:** `cycleStatusLabel("partial")` → **«Частично»** (`frontend/src/lib/design-system/labels.ts`). Таблица циклов: колонка «Сбоев» = `fetch_failed + validation_failed + persistence_failed` **без `missing_count`** (`monitoring-dashboard.tsx`).

### Worker vs partial cycle

**Факт:** `monitoring_worker_state`: `running`, `updated_at` совпадает с последним циклом. Циклы **завершаются** за ~5–8 с. **Partial — итог успешно завершённого цикла**, не зависший процесс.

### Последние 10 циклов (все partial, один паттерн)

| run_id (short) | finished (UTC) | loaded | eligible | due | overdue | selected | inserted | missing | fetch/val/persist |
|----------------|----------------|-------:|---------:|----:|--------:|---------:|-----------:|--------:|-------------------|
| …100950Z | 10:09:56 | 6570 | 1631 | 11 | 1 | 12 | 11 | **1** | 0 |
| …095438Z | 09:54:44 | 6570 | 1669 | 5 | 1 | 6 | 5 | **1** | 0 |
| …093924Z | 09:39:32 | 6570 | 1678 | 9 | 1 | 10 | 9 | **1** | 0 |
| …092413Z | 09:24:20 | 6570 | 1688 | 13 | 1 | 14 | 13 | **1** | 0 |
| …090903Z | 09:09:09 | 6570 | 1697 | 12 | 1 | 12 | 12 | **1** | 0 |
| …085351Z | 08:53:58 | 6570 | 1720 | 5 | 1 | 6 | 5 | **1** | 0 |
| …083842Z | 08:38:48 | 6570 | 1724 | 5 | 1 | 6 | 5 | **1** | 0 |
| …082330Z | 08:23:36 | 6570 | 1730 | 9 | 1 | 10 | 9 | **1** | 0 |
| …080819Z | 08:08:25 | 6570 | 1735 | 8 | 1 | 9 | 8 | **1** | 0 |
| …075309Z | 07:53:15 | 6570 | 1742 | 2 | 1 | 3 | 2 | **1** | 0 |

**72 h:** ok **91**, partial **181**. Декомпозиция partial: **181/181** с `missing_count > 0`; fetch/validation/persist **0**.

**Факт:** доминирующая причина «Частично» локально — **ровно 1 missing video** на цикл (видео не вернулось в batch API), часто при **overdue_count = 1**.

**Гипотеза:** один и тот же «битый»/удалённый `video_id` в overdue checkpoint → каждый цикл partial при успешных остальных снимках.

---

## 5. Выводы

### Штатно

- Определение due (null или `next_scan_at <= now`, не archived).
- Discovery worker крутится, scan runs **ok**, без failed keywords.
- Monitoring worker завершает циклы; partial при частичных сбоях capture — **задуманное** правило.

### Подтверждённый дефект / UX-разрыв (код)

- **Monitoring UI:** «Частично» выглядит как сбой воркера, а фактически часто **11/12 снимков OK**; колонка «Сбоев» **скрывает missing**, хотя missing **двигает** `cycle_status` в partial.

### Ограничение пропускной способности (не баг)

- **~4 keywords/cycle × ~12 cycles/h ≈ 48/h max** vs **~1659 due** → большая цифра на `/keywords` **ожидаема** при массовом suggestion/probation пуле и просрочке 1–7 d.
- Приток suggestion (**1772** из **1866**) увеличивает пул быстрее, чем empty queue.

### Что править в коде vs объяснить в UI

| | Код | UI |
|--|-----|-----|
| Due 1659+ | Не обязательно (batch/interval — продуктовые) | Показать **throughput** (ключей/ч из last 24h), **не «всё сломано»** |
| Partial | Опционально: gradation ok-with-missing vs failed batch | Расшифровка: «N из M снимков; missing = нет в ответе API»; включить missing в «сбои» или отдельная колонка |
| Overdue video | Диагностика: какой video_id missing (из `monitoring_capture_outcomes`) | Link/stop для deleted videos |

---

## 6. Минимальный Fix 3B (предложение, без реализации)

1. **Keywords summary:** под «N пора просканировать» — «за 24 ч просканировано K уникальных ключей; worker ~4 за цикл / ~300 с» (K из API или operations).
2. **Monitoring cycle badge:** при `partial` и `missing_only` — label уровня «Неполный снимок (1 missing)», не «Частично» как сбой; tooltip с breakdown.
3. **Таблица циклов:** колонка **missing** или «missing в partial».
4. **Read API (additive):** last-N cycles с `partial_reason` enum (`missing_only` | `fetch_failed` | …) из уже сохранённых полей — без смены worker logic.

**Приёмка 3B:**  
- При last cycle partial + missing=1, UI не показывает «0 сбоев» при статусе partial.  
- Keywords page показывает due + scanned_24h + одну строку «очередь vs пропускная способность».  
- Документ: partial ≠ worker stuck (есть `finished_at`).  
- Без изменения batch_size/interval без отдельного capacity review.

---

## Факты vs гипотезы

| Утверждение | Тип |
|-------------|-----|
| due = count TargetKeyword по next_scan_at | **Факт (код+SQL)** |
| 1659 due на снимке | **Факт** |
| 728 scans / 24 h | **Факт** |
| 0 failed keyword scans / 72 h | **Факт** |
| partial из-за missing_count | **Факт (181/181 за 72 h)** |
| 1849 было due в момент пользовательского аудита | **Гипотеза** (близко к full pool) |
| один video_id → recurring missing=1 | **Гипотеза** (нужен query к `monitoring_capture_outcomes`) |
| probation interval → 7d overdue mass | **Гипотеза** (нужен join scan_interval policy) |

*Реализация Fix 3B не начата.*
