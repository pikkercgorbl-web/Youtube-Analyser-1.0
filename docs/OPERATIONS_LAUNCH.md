# Операционный запуск NicheScope / Radar

Дополняет `READ.ME` (UI) и `docs/LOCAL_RADAR_LAPTOP.md` (локальный PostgreSQL).  
**Один способ конфигурации:** файл `.env` в корне проекта + опционально `.env.docker` для Docker Postgres.

## Приоритет переменных окружения

1. Уже заданные в **текущей сессии** PowerShell (`$env:DATABASE_URL`, …) — **перекрывают** `.env`.
2. Пары из `.env` (скрипты `migrate.load_dotenv` **не перезаписывают** уже установленные ключи).
3. Значения по умолчанию в коде (Pydantic settings).

Перед workers и read-model refresh в **новом** терминале:

```powershell
Set-Location "C:\Projects\Сайт анализ ниш1"
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
```

---

## Три режима работы

### A) Просмотр уже сохранённых данных

Нужны **Backend + Frontend**. Workers **не** обязательны.

| Компонент | Команда (открыть **отдельный** терминал PowerShell) |
|-----------|-----------------------------------------------------|
| PostgreSQL (Docker) | `.\scripts\start-local-db.ps1` |
| Backend | `.\scripts\start-backend.ps1` |
| Frontend | `.\scripts\start-frontend.ps1` |

UI читает Attention / Keyword Performance / Monitoring из **snapshot-таблиц** в БД. Если snapshot устарел, данные на экране старые — это нормально без refresh (режим A).

Остановка UI: `Ctrl+C` в терминалах backend и frontend.

### B) Непрерывный сбор данных

**Workers обязательны.** Backend/frontend для сбора **не** нужны (только для просмотра).

Скрипты `scripts/start-*.ps1` используют `$PSScriptRoot` (путь с пробелами/кириллицей поддерживается через `Set-Location -LiteralPath`), снимают **только** `Env:DATABASE_URL` текущего процесса, выставляют UTF-8 для Python и проверяют локальную БД через `stage3_operations_preflight.py` (без секретов). Второй экземпляр того же worker **не** стартует, если процесс уже есть.

| Pipeline | Терминал | Назначение |
|----------|----------|------------|
| Discovery (+ enrichment после цикла при `RADAR_ENRICHMENT_AFTER_DISCOVERY=1`; post-pass **keyword expansion** при `KEYWORD_EXPANSION_AFTER_DISCOVERY=1`; **topic exploration** при `TOPIC_EXPLORATION_IN_DISCOVERY=1`, см. `artifacts/stage6_local_radar_enable.json`) | `.\scripts\start-discovery.ps1` | seeds, hits, enrichment, expansion, exploration evidence |
| Monitoring | `.\scripts\start-monitoring.ps1` | snapshots по tier/checkpoint |
| Outcome | `.\scripts\start-outcome.ps1` | отложенные outcomes |

План без запуска: `.\scripts\start-discovery.ps1 -DryRun` (и аналоги для остальных).

Остановка: **`Ctrl+C`** в том же терминале (lock снимается в `finally`).

**После сна / hibernation / перезагрузки ноутбука:**

1. **Docker Postgres должен быть запущен** — `.\scripts\start-local-db.ps1` (данные в volume сохраняются, но контейнер после сна часто остановлен).
2. Убедиться, что ПК **не ушёл в сон** во время наблюдения, или после пробуждения выполнить шаги 1 и 3.
3. В **новых** терминалах снова запустить нужные `start-*.ps1` (workers не переживают перезагрузку ОС).
4. **Не** запускать `stamp_momentum_measurement_start.py` повторно, если не начинаете **новый** эксперимент измерения momentum.

**Measurement start (один раз на период наблюдения):**

```powershell
python scripts/stamp_momentum_measurement_start.py
```

Записывает `artifacts/momentum_measurement_start.json` и предлагает `MOMENTUM_MEASUREMENT_START_UTC` для `.env`. Повторный запуск **перезаписывает** маркер — делайте только осознанно.

### C) Обновление read models

Отдельно от workers. Читают БД, пишут snapshot-таблицы (штатные CLI с publish lock).

| Read model | Терминал | Интервал по умолчанию |
|------------|----------|------------------------|
| Attention | `.\scripts\start-attention-loop.ps1` | 3600 с (1 ч); параметр `-IntervalSeconds` |
| Keyword Performance | `.\scripts\start-keyword-performance-loop.ps1` | 86400 с (24 ч); параметр `-IntervalSeconds` |

Первый проход — **сразу** после старта, затем пауза до следующего интервала; при ошибке **нет** быстрого повтора (полный интервал). В логе терминала: время запуска и `exit_code=`. Остановка: **`Ctrl+C`**.

**Не включайте одновременно** терминальные loops (`start-attention-loop.ps1` / `start-keyword-performance-loop.ps1`) **и** Task Scheduler (`NicheScope-Radar-*`) — один механизм refresh на read model.

Dry-run Attention (без записи, разово): `python scripts/refresh_attention_engine.py --dry-run`

Параллельный publish защищён lock (`read_model_publish_locks`); второй CLI/задача завершится с кодом **2**.

---

## Планировщик Windows (подготовка, по умолчанию **не** активирует)

Идемпотентная установка **отключённых** задач:

```powershell
.\scripts\setup_read_model_scheduled_tasks.ps1 -Action DryRun
.\scripts\setup_read_model_scheduled_tasks.ps1 -Action Install   # задачи DISABLED
.\scripts\setup_read_model_scheduled_tasks.ps1 -Action Remove
```

Параметры: `-AttentionIntervalHours`, `-KeywordPerformanceLocalTime`, `-PythonExe`, `-ProjectRoot`.

Активация вручную после проверки: Task Scheduler → задача → Enable.

Обёртки с логами: `scripts/scheduled/run_attention_refresh.ps1`, `scripts/scheduled/run_keyword_performance_refresh.ps1` → каталог `logs/scheduled/`.

---

## Проверки

| Назначение | Команда |
|------------|---------|
| Offline regression (SQLite / in-memory) | `python scripts/run_fast_regressions.py` |
| PostgreSQL integration / concurrency / E2E | `python scripts/run_postgres_integration_tests.py` (нужен test URL) |
| Read-only preflight (локальная БД) | `python scripts/stage3_operations_preflight.py` |
| Entrypoints smoke | `python scripts/verify_local_radar_entrypoints.py` |
| Recovery / locks (offline suite) | `python scripts/run_stage3_recovery_suite.py` |

---

## Логи

- Workers: stdout терминала
- Scheduled read models: `logs/scheduled/*.log` (после установки задач)
