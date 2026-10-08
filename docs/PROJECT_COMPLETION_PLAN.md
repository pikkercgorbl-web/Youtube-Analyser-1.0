# Project completion plan

Дополняет READ.ME / stage-документы; не отменяет завершённые стадии.

## 1) Достоверные даты и метрики

**Цель:** VPH и возраст для monitoring / Attention / baseline считаются от достоверного `published_at` и времени измерения (`captured_at` или `discovered_at`), без слепого доверия к persisted `snapshot.vph` и без подстановки `now` в знаменатель прошлого измерения.

**Сделано (этап 1):**
- `app/services/snapshot_measurement.py` — единый read-path: `derive_snapshot_metrics`, provenance `published_at`, discovery fallback, `vph_series_from_snapshots` для acceleration.
- Потребители: `monitoring_video_source`, `attention_evidence`, `attention_video_winners`, `channel_velocity_baseline` (`snapshot_record_from_orm` + batch Video), `monitoring_api_service`, `snapshot_collection_policy` (rematch tie-break).
- Regression: `scripts/test_snapshot_measurement_regression.py`; обновлены `scripts/test_monitoring_video_source.py`, `scripts/test_breakout_ranking.py` (ожидания VPH согласованы с derived, не со stale `snapshot.vph`).
- Offline compare (read-only): `scripts/compare_snapshot_vph_derived_local.py` → `artifacts/snapshot_vph_derived_compare.json` (БД `127.0.0.1:5433` / `youtube_radar_restore_check`, фиксированный `now`).

**Проверки (команды):**
```text
python scripts/test_snapshot_measurement_regression.py
python scripts/test_monitoring_video_source.py
python scripts/test_snapshot_published_at_rematch.py
python scripts/test_video_snapshot_storage.py
python scripts/test_snapshot_collection_policy.py
python scripts/test_attention_engine_1_22a.py
python scripts/test_breakout_ranking.py
python scripts/test_channel_momentum_age_aligned.py
python scripts/compare_snapshot_vph_derived_local.py
```

**Bootstrap monitoring (discovery + exploration) — приёмка закрыта (2026-10-08):**

| Область | Статус |
|--------|--------|
| Load-path wiring | `monitoring_video_source` batch-load `KeywordDiscoveryHit`, `compute_before=now` на latest snapshots, передача hits в `derive_latest_measurement` |
| Discovery hit selection | `select_discovery_hit_for_measurement`: views + `discovered_at` одной записи; пропуск NULL views и hit не позже API `published_at`; invalid early hit не скрывает поздний |
| Enrichment measurement | `format_enrichment_snapshot.persist_format_enrichment_measurement` — `VideoSnapshot` source `format_enrichment`, `views` + `captured_at` из уже выполняемого `videos.list`; idempotent `(video_id, captured_at, source, run_id)`; без monitoring checkpoint / `fulfilled_late` metadata |
| API parsing | `YouTubeVideoDetails.views_count: int \| None` — missing ≠ 0 |
| Offline regression | `scripts/test_monitoring_bootstrap_complete.py`, `test_monitoring_bootstrap_discovery_to_capture.py`; обновлены `test_snapshot_measurement_regression.py`, `test_monitoring_video_source.py` |
| Read-only compare | `scripts/compare_monitoring_load_paths_readonly.py` → `artifacts/monitoring_load_path_compare.json` (restore-check, один `now`) |
| Live cycle (post-restart) | `monitoring_20261008T105850Z_6a92a6d7`: loaded 2420, active 1497, due 116, overdue 131, selected 247, inserted 247 (до wiring: eligible ~32, selected 0) |
| Отчёт | `artifacts/monitoring_bootstrap_completion_report.json` |

**Проверки bootstrap (дополнительно к списку выше):**
```text
python scripts/test_monitoring_bootstrap_complete.py
python scripts/test_monitoring_bootstrap_discovery_to_capture.py
python scripts/compare_monitoring_load_paths_readonly.py
```

**Ограничения:**
- Persisted `VideoSnapshot.age_hours` / `vph` / `captured_at` / `views` не переписываются; коррекция только при чтении/refresh read models.
- Без snapshot и без **пригодного** discovery-hit (views + `discovered_at` после API `published_at`) — VPH unavailable; exploration-only ждёт `format_enrichment` snapshot после enrichment pass (без доп. API ради bootstrap).
- API viewCount на hit **не** backfill в `views_at_discovery`; исторические snapshots не переписываются.
- InnerTube `published_at` помечается approximate; API snippet — preferred.
- Acceleration: средний VPH от публикации по ряду snapshots (не интервальная скорость между captures); правило 2× без изменений.
- На restore-check сэмпле (5000 latest snapshots) stored `snapshot.vph` совпал с derived — расхождения проявятся после массового уточнения `Video.published_at` при нетронутых snapshots.

## 2) Очереди подписчиков и конкурентный учёт бюджета

**Цель:** корректный отбор кандидатов (eligibility/cooldown до LIMIT, backlog vs recent) и атомарный UTC-day ledger при параллельных worker/CLI.

**Сделано:**
- `app/services/radar_enrichment_selection.py` — subscriber: SQL `fetch_due` + keyset по `channel_id`, orphan channel_id через `Video` + `ChannelSubscriberEnrichmentAttempt`; tie-break `(band, tie, channel_id)`; без `limit×20`.
- `app/services/enrichment_queue_split.py` + `enrichment_backlog_pass_fraction` (`ENRICHMENT_BACKLOG_PASS_FRACTION`, default 0.2) — subscriber и format pass: доля backlog, spill пустой части.
- `app/services/radar_api_budget.py` — read-only `read_budget_day` / `budget_day_status` (нет INSERT); PostgreSQL `INSERT ON CONFLICT` + `FOR UPDATE` + atomic reserve/increment; SQLite — serial fallback для unit-тестов.
- Transaction ownership: `try_reserve_id_units` → `session.commit()` **до** HTTP в `radar_enrichment_orchestrator`; сбой после резерва **не** откатывает ledger (консервативно).
- `http_requests` — счётчик **batch**-вызовов (`get_channels` / `get_videos`), не YouTube quota units; `id_units_reserved` — зарезервированные ID в batch.

**Проверки:**
```text
python scripts/test_subscriber_enrichment_selection_regression.py
python scripts/test_format_enrichment_selection_regression.py
python scripts/test_radar_enrichment_stage25.py
python scripts/test_radar_api_budget_concurrency.py   # RADAR_BUDGET_POSTGRES_TEST_URL
python scripts/stage2_enrichment_dryrun_profile.py  # read-only restore-check
```

**Артефакты (локальный restore-check):** `artifacts/stage2_enrichment_dryrun_profile.json` — subscriber/format selected 50/50, dry-run без новых ledger rows.

**Ограничения:**
- Глобальный HTTP dashboard вне scope.
- Daily/pass limits и quality thresholds не менялись.
- Concurrency гарантирован на PostgreSQL; SQLite in-memory — только последовательные тесты.

## 3) Рабочий запуск и расписания read models

**Цель:** однозначная документация запуска (просмотр vs workers vs read models), подготовка Task Scheduler, publish lock, единые offline/PostgreSQL проверки.

**Сделано:**
- `docs/OPERATIONS_LAUNCH.md` — режимы A/B/C, `.env` vs `$env:`, workers, measurement start один раз, stop/restart.
- `scripts/setup_read_model_scheduled_tasks.ps1` + `scripts/scheduled/run_*_refresh.ps1` — Install = **DISABLED** задачи (Attention hourly, KP daily); Remove/DryRun.
- `app/services/read_model_publish_lock.py` + таблица `read_model_publish_locks`; CLI `refresh_attention_engine.py`, `backfill_keyword_performance_read_model.py` (commit lock → compute → publish → release).
- `scripts/run_fast_regressions.py` — расширен offline suite (measurement, enrichment, momentum, saved topics, publish lock, `test_stage3_recovery_locks` для worker locks).
- `scripts/run_postgres_integration_tests.py`, `scripts/run_stage3_recovery_suite.py`, `scripts/stage3_operations_preflight.py`.

**Проверки:**
```text
python scripts/run_fast_regressions.py
python scripts/run_stage3_recovery_suite.py
python scripts/run_postgres_integration_tests.py   # SAVED_TOPICS_POSTGRES_TEST_URL
python scripts/stage3_operations_preflight.py      # read-only restore-check
.\scripts\setup_read_model_scheduled_tasks.ps1 -Action DryRun
```

**Приёмка этапа 3 (закрыта):**

| Область | Статус |
|--------|--------|
| Publish lock (Attention/KP CLI) | acquire → commit → compute → `assert_publish_lock_token` (FOR UPDATE) → publish → commit → release по **`lock_token`** |
| Владение | UUID **`lock_token`** на каждый acquire; диагностика `hostname:kind:pid` в `lock_holder` |
| Авария после acquire | Lock остаётся в БД до release по token или stale (180 мин); publish откатывается `rollback` |
| Stale takeover | Новый token; старый процесс **не публикует** (`ReadModelPublishNotAuthorizedError`); `release` старого token — no-op |
| Штатные пути публикации | **Только** `scripts/refresh_attention_engine.py` (не `--dry-run`) и `scripts/backfill_keyword_performance_read_model.py`; verify/smoke-скрипты вызывают `refresh_*` без lock — не production path |
| SQLite unit | `scripts/test_read_model_publish_lock.py` — блок второго publisher, stale, snapshot при rollback |
| PostgreSQL | `scripts/test_read_model_publish_lock_postgres.py` — **`test_stale_takeover_same_hostname_old_publish_blocked`** (A/B default identity, publish по stale token запрещён), failed publish + observations |
| Scheduler DryRun | `artifacts/stage3_scheduler_dryrun.json` — python path, cwd, расписание, logs, DISABLED, GUI для IgnoreNew/missed start |
| Wrapper exit code | `run_*_refresh.ps1`: `exit $proc.ExitCode` + строка `exit_code=` в log |

**Уже было корректно:** worker locks (discovery/monitoring), atomic Attention replace в одной транзакции publish, документация OPERATIONS_LAUNCH, offline fast regressions.

**Исправлено при приёмке:** `lock_token` + publish-time `assert_publish_lock_token`; PG-тест stale takeover на одном hostname; DryRun manifest setup-скрипта.

**Точечные проверки:** `run_fast_regressions.py`, `run_postgres_integration_tests.py` (4 скрипта), `setup_read_model_scheduled_tasks.ps1 -Action DryRun`, code review publish paths.

**Блокеры начала наблюдения (операционные, не код):** включить Task Scheduler (DISABLED→Enable + GUI IgnoreNew/missed start); запустить workers; при необходимости обновить KP read model (preflight показывал KP старее Attention); `logs/scheduled` создаётся при первом scheduled run.

**Ограничения:**
- Задачи планировщика **не активированы** в репозитории; IgnoreNew / StartWhenAvailable — финальная настройка в GUI после Install.
- Keyword Performance не имел отдельного фонового worker; только CLI backfill + optional schedule.
- Этапы 4–8 вне scope.

## 4) Наблюдение pipeline

**Статус: наблюдение начато** (2026-10-06). Это **не** «аналитическое качество подтверждено» — нужны сутки+ непрерывных workers и повтор аудитов.

**Цель этапа:** контролируемый локальный Radar на `127.0.0.1:5433` / `youtube_radar_restore_check`, workers + read models + Task Scheduler, исходный замер без изменения алгоритмов/порогов/бюджетов.

**Сделано:**
- Read-only preflight: `python scripts/stage3_operations_preflight.py` (БД и effective settings без секретов).
- Workers (один экземпляр каждого): discovery + monitoring + outcome; логи `logs/workers/*_20261006-213348.log`.
- Разовый refresh: `refresh_attention_engine.py`, `backfill_keyword_performance_read_model.py` (KP run_id `keyword_performance_20261006T154033Z`, 178 rows).
- Task Scheduler: `NicheScope-Radar-AttentionRefresh` (hourly), `NicheScope-Radar-KeywordPerformanceRefresh` (daily 03:15 local); `IgnoreNew` + `StartWhenAvailable` через `setup_read_model_scheduled_tasks.ps1 -Action Enable`. Attention зарегистрирован через `Register-ScheduledTask` (fallback: `schtasks /TR` ломается на пути с кириллицей).
- Метка наблюдения **сохранена**: `artifacts/momentum_measurement_start.json` → `2026-10-06T11:24:58+00:00` (перезапуск workers ~15:33 UTC, перерыв ~4h — **не** re-stamp).
- Первые завершённые циклы зафиксированы; исходный отчёт: `artifacts/stage4_observation_started.json` + audit JSON (ниже).

**Первые циклы (UTC):**

| Worker | run_id | Итог |
|--------|--------|------|
| Discovery | `discovery_20261006T153349Z_d8a3c9ac` | 5 keywords, 1782 hits, 1448 new videos; status ok |
| Enrichment (после цикла) | — | 50 ch / 50 fmt; outcomes 46 regular, 3 short, 1 stream; ledger ch 600 / vid 481 reserved |
| Monitoring | `monitoring_20261006T153349Z_5ea24b57` | eligible 52, due 0, overdue 14 → **14** snapshots, 0 errors |
| Outcome | `outcome_20261006T153350Z_6169e806` | due backlog large; **97** captures inserted, status ok |

**Аудиты (read-only, переиспользованы):**
```text
python scripts/stage4_worker_state_snapshot.py
python scripts/stage25_enrichment_closure_audit.py
python scripts/audit_momentum_data_pipeline.py
python scripts/audit_momentum_baseline_measurement.py
```
Артефакты: `artifacts/stage4_worker_state_snapshot.json`, `stage25_enrichment_closure_audit.json`, `momentum_data_pipeline_audit.json`, `momentum_baseline_measurement.json`.

**Снимок baseline (на старт наблюдения, не финал):**
- Очереди enrichment: ≥10 000 subscriber due (cap), ~2123 format due; возраст oldest due sample — см. stage25 audit.
- Post-restore cohort (since measurement start): 9 confirmed regular с `api_snippet`; snapshots в окне 18–30h для strict/post-restore cohort — **0** (ожидаемо рано).
- Momentum published signals: **0**; top skip: format_not_confirmed, momentum_24h_window_missed; offline rejections — subscriber cap / insufficient recent.
- `http_requests` в enrichment audit = batch API calls, **не** quota units.

**Операции:** запуск/остановка/resume — `docs/OPERATIONS_LAUNCH.md` и `artifacts/stage4_observation_started.json` (`start_commands` / `stop_commands` / scheduled log paths).

**Повтор через ~24h (не ждали внутри этапа):** preflight → `stage4_worker_state_snapshot` → stage25 + momentum audits → проверка логов workers и `logs/scheduled/` → при необходимости `run_channel_momentum_offline.py`.

**Ограничения:** этапы 5–8 не начинались; качество Momentum не подтверждено.

## 5) Существующий keyword expansion

**Цель:** довести текущий orchestrator до контролируемого автоподключения после discovery; на этапе **авто-добавление выключено**, live YouTube в тестах не используется.

**Цепочка (один pipeline):**
- Источники: `SuggestionExpansionSource` / `RelatedQueryExpansionSource` (InnerTube autocomplete), `ChannelTopicExpansionSource` (`Video.topic` через `KeywordDiscoveryHit`). **LLM:** константа `SOURCE_LLM` есть, класса источника и включения в orchestrator **нет** (этап 7).
- Orchestrator: `keyword_expansion_orchestrator.py` → filter → `evaluate_keyword_admission` → `persist_admission_decision`.
- Запуск: `run_keyword_expansion*` / `POST /api/keywords/{id}/expand` / CLI `run_keyword_expansion_orchestrator.py`.
- Provenance: `TargetKeyword.source_type`, `parent_keyword_id`, `KeywordExpansionEvent`; lifecycle events не меняются автоматически.

**Политики (фактические):** dedup normalized + batch; cooldown 7d/источник/родитель (`KeywordExpansionEvent.discovered_at`); depth &lt; 2 по цепочке `parent_keyword_id`; caps 20/источник, 10/seed/run, 50/run, 10 seeds; probation-seed ≥3 ok scans; `created_this_run` блокирует рекурсию в одном проходе; dry-run без insert/events.

**Сделано (этап 5):**
- Read-only аудит restore-check: `scripts/stage5_keyword_provenance_audit.py` → `artifacts/stage5_keyword_provenance_audit.json`.
- Post-discovery pass: `keyword_expansion_discovery_pass.py` + флаг `KEYWORD_EXPANSION_AFTER_DISCOVERY` (default **false**) в `keyword_expansion_runtime_config.py`.
- Точка подключения: `discovery_worker_runtime.py` **после** enrichment pass, **отдельная сессия** (по образцу Stage 2.5) — ошибка expansion не откатывает discovery.
- Тесты: `scripts/test_keyword_expansion_discovery_pass.py` + регрессии `test_keyword_admission_orchestration.py`, `test_keyword_expansion.py` (unit); fake-источники, без сети.

**Проверки (offline, in-memory / subprocess):**
```text
python scripts/test_keyword_expansion_discovery_pass.py
python scripts/test_keyword_admission_orchestration.py
python scripts/test_keyword_expansion.py          # incl. test_discovery_cycle regressions
python scripts/test_discovery_cycle.py
python scripts/test_discovery_worker.py           # expansion runtime (flag on/off, error isolation)
python scripts/test_monitoring_worker.py          # eligibility fixtures (Stage 2.3 contract)
python scripts/stage5_keyword_provenance_audit.py # read-only production DB
```

**Приёмка этапа 5 (2026-10-06):** цепочка `test_keyword_expansion.py` → `test_regressions` → `test_discovery_cycle` зелёная. Падение было из‑за **устаревших monitoring-фикстур** (нет `confirmed_regular`, `subscribers_api_status=known`, seed-snapshot → `raw_vph`), не из‑за expansion. Общий helper: `scripts/monitoring_test_seed_helpers.py`. Production-код monitoring/expansion не менялся для «зелёного» прогона.

**Включение в будущем (не включено сейчас):** в `.env` задать `KEYWORD_EXPANSION_AFTER_DISCOVERY=1`, перезапустить discovery worker (`scripts/start-discovery.ps1`). Ручной dry-run без записи: `python scripts/run_keyword_expansion_orchestrator.py --seed-id ID --dry-run`.

**Отключение:** убрать переменную или `KEYWORD_EXPANSION_AFTER_DISCOVERY=0`; discovery и `RADAR_ENRICHMENT_AFTER_DISCOVERY` не затрагиваются.

**Статус:** подготовлено и проверено, **автоматическое включение выключено**. Рабочие ключи и расписания не менялись.

**Ограничения:** этапы 6–8 не начинались (этап 6 закрыт отдельным разделом ниже).

## 6) Независимая разведка

**Цель:** широкие exploration-запросы вне веток seed keywords; n-gram предложения из заголовков без LLM/embeddings; preview + опциональный admission через существующий pipeline.

**Архитектура (один discovery pipeline):**
- Слоты цикла: `topic_exploration_batch_split.split_discovery_batch_slots` — min 1 seed и min 1 exploration при `batch_size >= 2`; при `batch_size == 1` только seeds.
- Запросы: редактируемый JSON `config/topic_exploration_queries.example.json` (`kind: exploration`); **не импортируется в БД автоматически**.
- Цикл: `discovery_cycle.py` — exploration scan (`keyword_id=None`); `Video`/`Channel` persist в `cycle_persisted_ids` → `cycle_video_ids` / `cycle_channel_ids`; **без** `KeywordScanRun` / `KeywordDiscoveryHit`.
- Persisted evidence (отдельные таблицы): `topic_exploration_passes`, `topic_exploration_video_observations`, `topic_exploration_phrase_pass_stats` — query/run, coverage, status, `settings_version`, dedupe video/pass; phrase stats для novelty/admission audit. Миграция: `ensure_topic_exploration_evidence_tables` (startup); **на рабочей БД в рамках этапа не применялась**.
- Post-pass: preview + novelty из **persisted** phrase stats; admission → `KeywordExpansionEvent` + `admitted_keyword_id` на phrase stat.
- Якорь admission: `TargetKeyword` с `source_type=exploration` и `parent_keyword_id IS NULL` **исключён** из `select_discovery_keywords` (не дублирует широкий exploration scan).

**Downstream handoff (exploration Video без KeywordDiscoveryHit):**

| Этап | Использует hits? | Поведение для exploration-only Video |
|------|------------------|--------------------------------------|
| Enrichment pass | Частично | `cycle_video_ids` → band 0 в `_format_priority`; `views_at_discovery` из hit **может отсутствовать** (fallback `Video.views_count`). Recent pool по hits — exploration video может попасть только через cycle band / backlog. |
| Monitoring eligibility | Нет hits | Как любое persisted regular Video после format confirm + channel caps (`monitoring_video_source`). |
| Attention evidence | Да для окна | `load_candidate_video_ids` объединяет hit window **и** `Video.published_at`; exploration video без hit всё ещё может попасть по publication window; `hits_by_video` для него пуст или без keyword attribution. |
| Keyword Performance 72h outcome | **Только hits** | `load_first_discovery_owner_for_videos` / baselines строятся из `KeywordDiscoveryHit.keyword_id`. Exploration-only Video **не** автоматически становится outcome обычного TargetKeyword; после admission новый probation keyword получает attribution только от **следующих** seed discovery hits. |

**Novelty / first_seen:** сигнал `first_seen_exploration` — первая запись в `topic_exploration_phrase_pass_stats` (scope **exploration**, не весь Radar). Сравнение частоты — только между **ok** проходами с одинаковым `pass_fingerprint` (query id + normalized query text + pages requested/scanned + `settings_version` + status). Failed pass сохраняется, но **не** трактуется как нулевое сопоставимое наблюдение.

**Пороги (гипотезы, env):** `TOPIC_EXPLORATION_MIN_DISTINCT_VIDEOS=2`, `MIN_DISTINCT_CHANNELS=2`, `OBSERVATION_WINDOW_HOURS=168`, `BATCH_FRACTION=0.2`, `MAX_PAGES_PER_QUERY=3`.

**Сделано (этап 6, приёмка):**
- Сервисы `topic_exploration_*`, persisted evidence, anchor exclusion, provenance link на admit.
- Offline: `scripts/test_topic_exploration.py`, `scripts/test_topic_exploration_evidence.py` (runtime discovery cycle + handoff + DB restart novelty).

**Проверки:**
```text
python scripts/test_topic_exploration.py
python scripts/test_topic_exploration_evidence.py
python scripts/test_discovery_cycle.py
```

**Включение (не включено):** `TOPIC_EXPLORATION_IN_DISCOVERY=1`, файл запросов, при необходимости прогнать startup migrations на целевой БД; якорь + `TOPIC_EXPLORATION_AUTO_ADMIT=1` только осознанно.

**Отключение:** `TOPIC_EXPLORATION_IN_DISCOVERY=0`; seed discovery / enrichment / Stage 5 без изменений.

**Статус:** этап 6 реализован и проверен offline; **auto flags off**; рабочая БД не мигрировалась.

**Ограничения:** exploration не пишет в `keyword_discovery_hits`; KP 72h не видит exploration-only video как keyword outcome; phrase history только в exploration tables; этапы 7–8 не начинались.

## 7) Эксперимент с LLM (Groq — offline harness + read-only search)

**Цель:** проверить Groq `openai/gpt-oss-120b` на реальных Radar evidence и **сопоставимо** сравнить сохранённые LLM search queries с **ручными EN baseline** той же темы через InnerTube (без workers, без insert TargetKeyword, без discovery persist).

**Сделано:**
- Smoke: `scripts/test_groq_access.py` → `artifacts/groq_access_smoke.json`
- Evidence + Groq (5 пакетов, discovery hits): `scripts/groq_radar_evidence_experiment.py` → `artifacts/groq_radar_evidence_experiment_20261007T152414Z.json`, снимок `groq_radar_evidence_packets_20261007T152414Z.json` (exploration tables **пусты**)
- Harness fixes: `usage`/`finish_reason` до parse; `finish_reason=length` → incomplete; 429 body + `rate_limit_diagnosis`; 3 suggestions; `SKIP_PACKET_IDS` для повторных прогонов
- Stage 7 compare (**исправленная методика**, 0 LLM, ≤6 InnerTube): `scripts/groq_stage7_search_compare.py` → `artifacts/groq_stage7_thematic_pairs_20261007T153149Z.json`, краткий отчёт `artifacts/groq_stage7_thematic_pairs_report.md`, latest pointer `groq_stage7_search_compare_latest.json`

**Отменено как доказательство «LLM лучше»:** первый прогон 9 поисков (RU seed `реальные истории` / `что если` / `historical mysteries` vs смешанные EN LLM). Разные языки/темы → часто **0 пересечения** и разные пулы заголовков; это **не** сравнение LLM с baseline.

**3 тематически согласованные пары (manual_control_en vs сохранённый LLM, 1 page, sort upload date, hl=en gl=US):**

| Тема | Manual baseline | Saved LLM (Groq artifact) | Пересечение page 1 (20261007) |
|------|-----------------|---------------------------|-------------------------------|
| betrayal | `betrayal stories` | `real life betrayal stories` | 2 |
| abandoned | `abandoned places stories` | `real stories of mysterious abandoned places` | 7 |
| anime what-if | `anime what if` | `what if you have cursed energy` | 0 |

Прогон 20261007: **3 live** InnerTube (baseline) + **3 reuse** из кэша (LLM queries, те же search_settings).

**Выводы (сдержанные):**
- При **EN+EN и одной теме** обе формулировки дают on-theme latin-heavy выдачу; overlap зависит от **специфичности** запроса (abandoned высокий, anime what-if — разные sub-niche, 0 overlap).
- LLM-only video IDs **не** находки; overlap с evidence corpus **0** на всех трёх парах.
- Faceless / канал ≤100k **не** утверждались (только title/format hints; без просмотра и API subs).
- **LLM не интегрирован** в Radar.

**Проверки:**
```text
python scripts/test_groq_access.py
python scripts/groq_radar_evidence_experiment.py   # Groq; новые пакеты (не SKIP set)
python scripts/groq_stage7_search_compare.py       # InnerTube only; thematic pairs
```

**Ограничения:** Groq free tier / лимиты — только Console; 429 на 5-м пакете в первом Groq-прогоне; один truncated JSON (keyword:90); одна страница InnerTube ≠ discovery qualification; этап 8 не начинался.

## 8) Приёмка первой версии

*(не в scope)*
