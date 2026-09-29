# Stage 1.21A — Product UX Audit + Information Architecture

**Status:** audit / IA only (no frontend implementation).

**Scope:** `frontend/src` — monitoring, operations, keyword-performance, keyword-related pages, sidebar, home search.

**Principle:** Each primary route answers **one** operator/analyst question. Progressive disclosure: **что происходит → почему → технические детали**.

---

## A. Executive UX diagnosis

The product backend is mature (discovery, monitoring, breakout, keyword performance, operations, 72h outcomes), but the UI **mirrors pipeline vocabulary** instead of **operator mental models**.

**Core symptoms:**

1. **English pipeline terms at equal visual weight as Russian labels** — Due, Overdue, Loaded, Eligible, Selected, Inserted, Evidence, attr, breakout-elig, Raw, Persisted, Lifecycle (raw enum).
2. **No Level-1 narrative strip** on Operations or Monitoring — users must infer health from numbers (`Due: 89`, `Eligible: 0`).
3. **Page purpose collision** — «Ключевые слова» in sidebar → `/keyword-research` (SEO research), while **target keyword pool / schedule** appears only inside «Perf. ключей» and API; `/keywords` is a separate one-shot analyzer **not in sidebar**.
4. **Tables as default UI** — Keyword Performance shows 10+ columns including internal abbreviations; Operations duplicates metrics across top cards and section grids.
5. **Badge overload with mixed semantics** — `active` (monitoring checkpoint), `probation` (lifecycle), `early` (evidence), `ok` (cycle), `stale_activity` (worker) use similar outline badges.
6. **Partial good patterns already exist** — Operations subtitle clarifies non-quality intent; KP has `GlobalBreakoutNotice` / `OutcomesCoverageNotice`; Monitoring has breakout sort help. These should become the **default pattern**, not exceptions.

**Strategic direction:** Keep all technical data accessible under **«Подробнее» / expandable rows / detail pages**, but lead every screen with **2–5 human sentences** derived from existing metrics (no new scores).

---

## B. Page purpose map

| Route | Sidebar label | Current implied question | Intended question (1.21+) | Keep separate? |
|-------|---------------|--------------------------|---------------------------|----------------|
| `/` | Поиск видео | «Find videos manually» | Same — ad-hoc search / exploration | Yes |
| `/keyword-research` | Ключевые слова | «Research SEO keyword ideas» | Same — **rename in nav** to avoid pool confusion | Yes |
| `/keywords` | *(not linked)* | «Score one keyword for tutorials» | Niche opportunity analysis (legacy/ad-hoc) | Consider merge or rename |
| `/keyword-performance` | Perf. ключей | «Show me every discovery metric column» | **Which keywords produce useful discovery?** | Yes |
| *(missing)* | — | — | **What keyword pool exists and what is scheduled?** | Yes — new IA slot (1.21F+) |
| `/monitoring` | Мониторинг | «Show worker lock + due counts + video table» | **What is watched now and what needs attention?** | Yes |
| `/operations` | Операции | «Dump runtime counters» | **Is the system running and accumulating data?** | Yes |
| `/explosive-channels` | Взрывные каналы | Radar watchlist | Channels matching viral thresholds | Yes |
| `/mass-analysis` | Массовый анализ | Bulk trends | Bulk / cohort analysis | Yes |
| `/saved-keywords` | Сохраненные идеи | Saved research ideas | Saved research ideas | Yes |
| `/monitoring/videos/[id]` | — | Video checkpoint detail | Why this video is in this monitoring state | Yes |

**IA gap (P0):** There is **no dedicated «очередь ключей» UI**; scheduling (`next_scan_at`, lifecycle) is only visible partially via Keyword Performance. Operators conflate **research keywords** with **target keywords**.

---

## C. Three-level information hierarchy (by screen)

Legend: **L1** human summary · **L2** operational/analytical · **L3** technical.

### `/operations`

| Content (current) | Level |
|-------------------|-------|
| Title + «не оценка качества» | L1 (partial) |
| Top 4 cards (Discovery/Monitoring time, Due, snapshots, 72h icons) | L2 (mislabeled L1 — still raw) |
| Discovery/Monitoring cards (Due 1h/24h, Raw, Unique, Persisted, Run ID) | L2–L3 mix |
| Snapshot daily bars | L2 |
| 72h maturity stack + attribution mode | L2 |
| Cycle tables (Raw, Unique, Sel., Ins.) | L3 |
| Live planner toggle, `all_hits` / `first_discovery` | L3 |
| Liveness note (heartbeat not implemented) | L3 |

**Target:** L1 = generated summary strip (5 bullets max). L2 = section cards. L3 = tables + toggles.

### `/monitoring`

| Content | Level |
|---------|-------|
| Worker lock status line | L2 |
| Stat cards: Active, Due, Overdue, Pending, Last cycle | L2 (English labels) |
| Tier A/B/C counts | L2 |
| Latest cycle grid (Loaded/Selected/Inserted/Missing/Fetch…) | L3 |
| Video table + filters | L2 (list) + L3 (columns) |
| Breakout sort help | L2 |

**Target L1:** «Воркер … · N видео на контроле · M просрочено · K ждут снимка» + explain Eligible=0 cases.

### `/keyword-performance`

| Content | Level |
|---------|-------|
| Header description | L1 (partial) |
| Global/outcomes notices | L1 ✅ |
| Metric family tabs (Discovery/Breakout/72h/Full) | L2 |
| Table columns | L2–L3 (too much default) |
| Evidence cell (scans, attr, breakout-elig) | L3 |
| Detail page | L3 dump |

**Target L1:** 1–2 sentences on evaluation window + data readiness. Default table = L2 columns only.

### `/keyword-research` vs target pool

| Content | Level |
|---------|-------|
| Research results, scores | L1–L2 (different product) |
| Target pool / schedule | **Missing** |

### `/` (search home)

Exploration UI — out of 1.21C–E scope except nav grouping.

---

## D. Terminology rewrite table

Product term recommendation: **«всплеск»** as stable Russian product term for breakout ranking context; keep **VPH** with tooltip.

| Internal / API field | User label (RU) | Tooltip / help (short) | Level |
|----------------------|-----------------|-------------------------|-------|
| `keywords_due_now` | Ждут сканирования | Ключи, у которых наступило `next_scan_at` | L1–L2 |
| Due (monitoring) | Пора снять снимок | Checkpoint попал в окно revisits | L2 |
| Overdue | Просрочено | Checkpoint пропустил плановое время | L2 |
| `loaded_video_count` | Проверено видео | Загружено в цикл monitoring (не «в базе») | L3 |
| `eligible_video_count` | Подходит под правила | Regular, в горизонте, проходит planner | L2 |
| `selected_capture_count` | Выбрано для снимка | В бюджет цикла попало N запросов | L3 |
| `inserted_snapshot_count` | Снимков сохранено | Новые строки `VideoSnapshot` | L2 |
| `missing_count` | Без снимка на CP | Checkpoint без успешного capture | L3 |
| Raw candidates | Сырые находки | Все позиции выдачи до дедупа | L3 |
| Unique candidates | Уникальные видео | После дедупа в скане | L2 |
| Persisted videos | Сохранено в базу | Upsert в `videos` для monitoring | L2 |
| `attributed_video_count` | Связано с ключом | Видео, засчитанные ключу (режим атрибуции) | L3 |
| `unique_video_count` (KP) | Найдено уникальных | Уникальные video_id в сканах ключа | L2 |
| `new_to_corpus_video_count` | Новые для базы | Не было в `videos` до discovery | L2 |
| `cross_keyword_duplicate_count` / rate | Уже другими ключами | То же video_id другим ключом в цикле/истории | L2–L3 |
| `median_vph_at_discovery` | VPH при находке | Просмотры/час на момент discovery (медиана) | L2 |
| `breakout_eligible_video_count` | В пуле всплеска | Попадает под правила global breakout pool | L3 |
| `observed_72h_video_count` | Исход 72 ч измерен | Есть валидный снимок около discovery+72ч | L2 |
| `missing_72h_video_count` | Нет снимка на 72 ч | Созрело, но snapshot не найден | L3 |
| `evidence_status` | Надёжность данных | insufficient / early / established | L2 |
| `evidence_detail` | Состав доказательств | scans, attr, breakout-elig, 72h obs | L3 |
| `lifecycle_status` | Статус в очереди | probation / active / weak / archived | L2 |
| `activity_state` | Активность воркера | active_recently / stale / error | L1–L2 |
| `cycle_status` | Итог цикла | ok / partial / failed | L3 |
| `all_hits` / `first_discovery` | Режим атрибуции | Все попадания vs первый ключ | L3 |
| `global_eligible_video_count` | Глобальный пул всплеска | N eligible для сравнения top-decile | L2 |
| `in_active_capture_pool` | В пуле съёма | Попадает в active capture budget | L2 |
| `active_monitored_count` | На мониторинге | Видео с активным monitoring state | L1 |
| Fetch / validation / persistence fail | Ошибки загрузки / проверки / записи | Счётчики последнего цикла | L3 |
| Run ID | ID запуска | `discovery_*` / monitoring run uuid | L3 |

**Lifecycle labels (must translate):**

| Internal | User label |
|----------|------------|
| probation | Пробный |
| active | В работе |
| weak | Слабый сигнал |
| archived | Архив |

---

## E. Operations blueprint (text wireframe)

```
/operations

[Заголовок] Операции
[Подзаголовок] Здоровье discovery, monitoring и накопления данных (не качество ключей).

[L1 — Сводка ситуации]  (auto-generated from API, 3–5 предложений)
  Пример:
  • «Discovery: последний цикл 2 ч назад (ok). 89 ключей ждут сканирования.»
  • «Monitoring: цикл 15 мин назад; сохранено 12 снимков; 340 checkpoint просрочено.»
  • «Снимки: за 24 ч — 12; последний — 15 мин назад.»
  • «72 ч: 1 240 исходов измерено; 7 416 созрели без снимка на горizonte.»
  • «Блокировки: …» (only if error/stale)

[L2 — Пять блоков здоровья]  (collapsible, default expanded first 2)

  [Discovery]
    headline: Работает / Давно не запускался / Ошибка
    explanation: 1 sentence
    key metrics (3): последний цикл · ключей в очереди · сохранено видео (last cycle)
    [Подробнее →] Due 1h/24h, raw/unique/persisted, errors, worker note

  [Monitoring]
    headline + explain Loaded vs Eligible if eligible=0
    key metrics: последний цикл · снимков в цикле · due/overdue (cycle)
    [Подробнее →] loaded/eligible/selected/inserted/fail counters, live planner (off by default)

  [Снимки]
    key metrics: 24h · 7d chart · last snapshot
    [Подробнее →] unique videos 24h

  [72h исходы]
    maturity bar + mode selector (moved here as L3 control)
    key metrics: valid · pending · missing · matures in 24h
    [Подробнее →] attribution help, observation counts

  [Ошибки] (only if any)

[L3 — Журналы циклов]
  Discovery cycles table
  Monitoring cycles table

[Footer] API snapshot time
```

**Summary message rules (descriptive, from real fields):**

- Discovery idle: `last_cycle_finished_at` + `keywords_due_now`
- Monitoring idle snapshots: `inserted_snapshot_count` last cycle + `snapshots_last_24h`
- Outcomes immature: `pending_72h_count` vs `matured_72h_count`
- Blocked: `errors.*` or `activity_state === error`

---

## F. Monitoring blueprint

```
/monitoring

[Заголовок] Мониторинг
[L1 — Сводка]
  • Worker: {running|stale|stopped} + plain Russian
  • «На мониторинге: N видео · P просрочено · Q пора снять снимок · R в ожидании»
  • If eligible=0 in last cycle (from overview/cycle): «В базе есть видео, но по текущим
    правилам нет кандидатов на снимок в этом цикле» (link to Operations Loaded/Eligible)

[L2 — Очередь работ]
  Cards: на мониторинге · пора · просрочено · ожидают (replace Due/Overdue/Pending)
  Tier distribution (secondary row, muted)

[L2 — Последний цикл]
  Human line: «Цикл ok, 12 снимков, 3 ошибки загрузки»
  [Технические детали ▼] run_id, loaded/selected/inserted/...

[L2 — Список видео]
  Default sort: Приоритет
  Columns (default): Видео · Канал · Статус (RU) · Просмотры · VPH · Возраст · След. checkpoint · Снимок
  Expanded / detail: tier, пул съёма, overdue hours list
  Breakout mode: separate column set + keep existing help

[L3 — История циклов]
  Table at bottom (already partially present)
```

**Human-readable monitoring video states:**

| Condition | Copy |
|-----------|------|
| overdue CP | «Просрочен снимок (+N ч)» |
| due CP | «Пора снять снимок» |
| pending | «Ожидает checkpoint» |
| active | «На контроле» |
| stopped | «Снято с мониторинга» |

---

## G. Keyword Performance blueprint

```
/keyword-performance

[L1]
  Evaluation context (already) + readiness notices (already)
  Optional: «Показаны N ключей · M с достаточными данными»

[L2 — Default table]  (single table, not 3 stacked in Full)
  Columns:
    Ключ · Статус в очереди · Найдено · Новые · VPH при находке · Последний скан · Данные (badge)

  Row expand OR link to detail:
    Атриб. · p90 VPH · cross-kw dup · breakout-elig · 72h obs · top-decile rate

[L2 — Tabs as views, not separate dense tables]
  Discovery | Всплеск | 72 ч  → changes expanded columns + detail emphasis, not wholly different tables

[L3 — Detail /keyword-performance/:id]
  Sections: Discovery · Всплеск · 72h · Техническое (attribution, ranking_version, raw counts)
  Scheduling: next_scan_at, scan_interval (when pool page exists, move schedule there)

[Controls]
  Attribution → RU labels, advanced panel
  Metric family → rename «Полный» to «Все метрики (таблицы)»
```

---

## H. Zero / unavailable semantics (UI rules)

| Signal | Meaning | User copy (not “0 = bad”) |
|--------|---------|---------------------------|
| `global_eligible_video_count === 0` | Breakout comparison unavailable | Already ✅ — extend to table cells |
| `observed_72h === 0` | No valid outcomes yet | Already ✅ |
| `eligible === 0`, `loaded > 0` | Rules filter out capture | «Нет подходящих под снимок в этом цикле» |
| `selected === 0`, `eligible > 0` | Budget/deferral | «Есть кандидаты, но цикл ничего не выбрал (бюджет/лимит)» |
| `selected === 0`, `eligible === 0` | Nothing to select | «Нечего выбирать — нет eligible» |
| `snapshots_last_24h === 0` | No new snapshots | «За 24 ч снимков не было» — not necessarily failure |
| `inserted === 0`, cycle ok | Cycle ran, no new snapshots | «Цикл прошёл, новых снимков нет» |
| `keywords_due_now === 0` | Queue caught up | «Нет ключей, которым пора сканироваться прямо сейчас» |
| `active_monitored_count === 0` | Empty pool | «Нет видео на мониторинге — проверьте discovery persistence» |
| `breakout rate —` with N=0 | Unavailable | Already in formatter |
| `median Δ views 72h —` when observed=0 | Unavailable | Already ✅ |
| Empty KP list | No targets | Distinguish API error vs empty queue |

**Rule:** Always pair **0** with **context** (which numerator/denominator, which gate).

---

## I. Status / badge taxonomy

Use **three badge families** (shape/color/icon), never reuse for different concepts:

| Family | Examples | Visual |
|--------|----------|--------|
| **System / worker** | running, stale, stopped, error, active_recently | Dot + neutral/amber/red; **no** lifecycle words |
| **Lifecycle (keyword queue)** | probation, active, weak, archived | Secondary pill + RU label |
| **Evidence / data readiness** | insufficient, early, established | Outline + info icon; muted palette |
| **Checkpoint (video)** | due, overdue, pending, stopped | Amber/rose/slate — **RU only** in UI |
| **Cycle result** | ok, partial, failed | Small monospace tag in logs section only |

**Remove English** from default monitoring status filter options (`overdue` → «Просрочено»).

---

## J. Navigation proposal (labels only; routes unchanged)

**Groups (visual separators in sidebar, not route changes):**

**Поиск и ключи**
- Поиск видео → `/`
- Исследование ниш → `/keyword-research` *(rename from «Ключевые слова»)*
- Очередь discovery → `/keyword-performance` interim + future dedicated pool page
- Производительность ключей → keep or shorten «Результаты ключей»

**Мониторинг системы**
- Мониторинг → `/monitoring`
- Операции → `/operations`

**Анализ**
- Взрывные каналы → `/explosive-channels`
- Массовый анализ → `/mass-analysis`
- Сохранённые идеи → `/saved-keywords`

**Hidden / secondary:** `/keywords` (single analyze) — link from research or deprecate.

Remove «Perf. ключей» abbreviation.

---

## K. Copy / vocabulary guide

1. **UI language:** Russian for labels, sentences, badges, summaries.
2. **English allowed:** run_id, tier A/B/C (with tooltip), VPH (with tooltip), API enum in L3 monospace only.
3. **Product terms (stable):**
   - **Снимок** — VideoSnapshot checkpoint capture
   - **Цикл** — discovery or monitoring worker run
   - **Очередь ключей** — TargetKeyword pool (not SEO research)
   - **Всплеск** — breakout ranking / top-decile context
   - **72 ч исход** — outcome at horizon
4. **Avoid:** attr, elig, ins, sel, corpus (use «база»), hits without translation.
5. **Numbers:** `ru-RU` grouping; «—» for unavailable (not 0).
6. **No quality judgments** in copy («плохой ключ») — already aligned with backend philosophy.

---

## L. Visual hierarchy principles (design rules, no CSS yet)

1. **One hero per page:** L1 summary strip — largest text after title, max 5 lines.
2. **Cards sparingly:** Only for the **five health questions** on Operations and **four queue stats** on Monitoring — not per metric.
3. **Tables for lists** — videos, keywords, cycles; default ≤7 columns.
4. **Muted text** for timestamps, run_id, secondary denominators.
5. **Color:** Amber = attention (due), Rose = overdue/error, Emerald = running/ok **only for system state**, not lifecycle.
6. **Typography:** Title 2xl → L1 lg/regular → section titles sm medium → table xs headers.
7. **Explanations:** Section subtitle (1 sentence) + «?» tooltip; long text in expandable **«Что это значит?»** panel, not inline in every row.
8. **Density:** Desktop-first min table width ~960px; horizontal scroll acceptable with sticky first column.

---

## M. Tooltip / help strategy

| Metric | Tooltip (≤120 chars) | Deeper help |
|--------|----------------------|-------------|
| VPH | Просмотров в час по последнему снимку или discovery | Link to monitoring doc |
| Due / Overdue | См. H. | Section help in Operations |
| Attribution | Кому засчитывается video_id | Expand panel on 72h card |
| First discovery | Первый ключ с earliest `discovered_at` | L3 |
| Breakout / top-decile | Попадание в верхний decile global VPH | Existing banner |
| 72h outcome | Снимок в ±12h от discovery+72h | Operations maturity card |
| Evidence | Объём сканов и исходов для строки | Detail page |
| Tier | Приоритет бюджета снимков A/B/C | Monitoring help |
| Пул съёма | Попадает в бюджет active capture | CapturePoolBadge area |

**Pattern:** `?` icon in header → drawer or popover; table headers → `title` attribute minimum.

---

## N. UX debt priorities

### P0 — confusing / misleading
- English Due/Overdue/Loaded/Eligible/Selected on Operations & Monitoring without L1 explanation
- Sidebar «Ключевые слова» ≠ target keyword pool (wrong mental model)
- Monitoring `Eligible=0` vs large video table — no bridge copy
- Lifecycle enums shown raw (`probation`) in KP
- Attribution select shows `all_hits` / `first_discovery` raw
- Same badge style for worker vs checkpoint vs lifecycle

### P1 — important clarity
- Operations duplicate metrics (top card + section grid)
- KP Full mode = three full tables stacked
- Evidence cell English microcopy (`scans`, `attr`, `breakout-elig`)
- Monitoring filter options in English
- `/keywords` orphan vs sidebar naming
- Operations «Live planner» untranslated

### P2 — polish
- Card aesthetic uniformity
- «Perf. ключей» abbreviation
- Tier row as three equal cards (could be compact bar)
- Mobile nav (secondary for operator desktop)

---

## O. Stage 1.21B–F roadmap

| Stage | Focus | Deliverables |
|-------|--------|--------------|
| **1.21A** | UX audit + IA (this doc) | Terminology map, wireframes, debt list |
| **1.21B** | Design system / visual foundation | Badge taxonomy components, summary strip pattern, tooltip primitive, spacing/type scale |
| **1.21C** | Operations redesign | L1 summary generator (frontend-only string build), section collapse, RU labels |
| **1.21D** | Monitoring redesign | L1 queue summary, RU status filters, cycle detail disclosure |
| **1.21E** | Keyword Performance redesign | Default slim table, row expand, RU attribution, lifecycle labels |
| **1.21F** | Navigation + consistency pass | Sidebar groups/renames, target keyword pool page (schedule + lifecycle actions read-only), cross-link Operations ↔ Monitoring |

---

## Task 1 — Screen audit (per-screen)

### `/operations`

| Item | Finding |
|------|---------|
| **A. Current question** | «What are all runtime counters right now?» |
| **B. Should answer** | Is discovery/monitoring alive; is data accumulating; are 72h outcomes maturing; what is blocked? |
| **C. Cognitive problems** | English metrics at top weight; worker liveness caveat buried; two commit paths mentally merged by user |
| **D. Ambiguous terms** | Due, Live planner, Raw, Unique, Persisted, Loaded, Eligible, Sel./Ins. in tables |
| **E. Excessive weight** | Top Due count; 72h ✓⏳? without narrative |
| **F. Hidden important** | `activity_state`, error summaries, `matures_next_24h`, attribution impact |
| **G. Duplicates** | Discovery due in card + grid; monitoring snapshots in card + section |
| **H. Missing** | Generated L1 summary; eligible=0 explanation |

### `/monitoring`

| Item | Finding |
|------|---------|
| **A** | «List videos + show due/overdue counts» |
| **B** | What is monitored; what needs attention; worker health |
| **C** | Breakout vs priority modes differ but UI looks same; English status filters |
| **D** | Due, Overdue, Pending, Missing, Fetch failed, run_id |
| **E** | Tier A/B/C row equal to queue cards |
| **F** | `in_active_capture_pool`, breakout rank context |
| **G** | Cycle stats in overview + latest cycle section |
| **H** | Eligible vs loaded not on this page (Operations only) — need cross-link |

### `/keyword-performance`

| Item | Finding |
|------|---------|
| **A** | «Show all discovery/breakout/outcome columns» |
| **B** | Which keywords produce useful discovery |
| **C** | Full mode overwhelming; Evidence column is a mini-dashboard |
| **D** | New corpus, Cross-kw dup, VPH @ disc., Breakout-elig, Observed 72h, Lifecycle |
| **E** | Too many numeric columns at once |
| **F** | `next_scan_at`, scheduling (in types but not prominent) |
| **G** | Overlap Discovery + Full tables |
| **H** | When to trust early vs established — badge without row-level sentence |

### Keyword pool / management

| Item | Finding |
|------|---------|
| **A** | *(No dedicated page)* — pool implied in KP list |
| **B** | What keywords exist; schedule; lifecycle state |
| **C** | Users use «Ключевые слова» nav for wrong task |
| **D** | target keyword vs research keyword |
| **E** | — |
| **F** | next_scan_at, source_type, parent_keyword |
| **G** | KP + research both «keywords» |
| **H** | No schedule overview |

### `/keyword-research`

| Item | Finding |
|------|---------|
| **A** | SEO-style keyword ideas for content |
| **B** | Same (correct for research) |
| **C** | Naming collision with discovery queue |
| **D** | score, competition — different domain |
| **E** | — |
| **F** | — |
| **G** | — |
| **H** | Clarify relation to target queue in empty state |

### `/` (home search)

| Item | Finding |
|------|---------|
| **A** | Manual video search |
| **B** | Same |
| **C** | Not conflated with ops pages |
| **D** | Filter jargon (separate module) |
| **E** | — |
| **F** | — |
| **G** | — |
| **H** | — |

### Sidebar / nav

| Item | Finding |
|------|---------|
| **A** | Flat list of features |
| **B** | Grouped workflows (discovery vs ops vs analysis) |
| **C** | No grouping; Perf abbreviation |
| **D** | «Ключевые слова» misroutes intent |
| **E** | All items equal weight |
| **F** | Operations vs Monitoring distinction subtle |
| **G** | — |
| **H** | No «start here» for operators |

---

## Task 13 — Responsive / density

- **Desktop default:** 1280px+; Operations 2-col cards; Monitoring table full width.
- **Collapse:** Operations L3 tables behind tabs; KP expand row for width <1200px hide p90/cross-dup columns.
- **Sticky:** First column (keyword / video title).
- **Mobile:** Sidebar drawer OK; defer table redesign — show «Откройте на широком экране» for KP/Operations tables if `<768px`.

---

*End of Stage 1.21A document.*
