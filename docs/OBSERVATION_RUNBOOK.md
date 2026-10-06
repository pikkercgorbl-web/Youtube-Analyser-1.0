# Runbook: локальное наблюдение Radar (Attention + Saved Topics)

Стадии **1.22A / 1.22B / 1.22B.1 / 1.22C / 1.22D** — завершены.  
**Следующие этапы:** период наблюдения (read-only контроль), **LLM keyword expansion** (без автозапуска workers в этом runbook).

Workers и YouTube Data API в режиме наблюдения **не обязательны**; Attention refresh — отдельный Python-скрипт.

---

## 1. Запуск и остановка

### PostgreSQL (Docker)

```powershell
Set-Location "C:\Projects\Сайт анализ ниш1"
docker compose --env-file .env.docker up -d db
docker compose --env-file .env.docker exec db pg_isready -U radar -d youtube_radar_restore_check
```

Остановка без удаления данных: `docker compose --env-file .env.docker stop db`  
**Не использовать** `docker compose down -v`.

### Backend (порт 8000)

```powershell
Set-Location "C:\Projects\Сайт анализ ниш1"
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Frontend (порт 3000)

```powershell
Set-Location "C:\Projects\Сайт анализ ниш1\frontend"
npm install
npm run dev
```

`frontend/.env.local`: `NEXT_PUBLIC_API_URL=http://localhost:8000`

### Workers (только когда нужен live discovery/monitoring)

Не запускать для read-only наблюдения. Команды — в [LOCAL_RADAR_LAPTOP.md](./LOCAL_RADAR_LAPTOP.md).

---

## 2. Attention refresh (полный путь)

Рабочий каталог — **корень репозитория** (где `app/`, `scripts/`, `.env`).

```powershell
Set-Location "C:\Projects\Сайт анализ ниш1"
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
python scripts/refresh_attention_engine.py
```

JSON: `python scripts/refresh_attention_engine.py --json`  
Dry-run: `python scripts/refresh_attention_engine.py --dry-run`

После refresh для неархивных Saved Topics автоматически append observations (1.22C).

---

## 3. Measurement start (один раз)

```powershell
Set-Location "C:\Projects\Сайт анализ ниш1"
python scripts/stamp_momentum_measurement_start.py
```

Артефакт: `artifacts/momentum_measurement_start.json`. Повторно не перезаписывать без причины.

---

## 4. Read-only контроль через 24 часа

Без workers:

1. http://localhost:3000/opportunities — snapshot families/winners  
2. http://localhost:3000/saved-topics — watchlist, последнее observation  
3. http://localhost:3000/validation — сводка feedback и presence  
4. API: `GET /api/attention/summary`, `GET /api/validation/report`

Momentum audit (read-only SQL):

```powershell
python scripts/audit_momentum_baseline_measurement.py
```

---

## 5. Backup

```powershell
Set-Location "C:\Projects\Сайт анализ ниш1"
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
docker compose --env-file .env.docker exec -T db pg_dump -U radar -d youtube_radar_restore_check -Fc -f "/tmp/backup_$ts.dump"
docker compose --env-file .env.docker cp "db:/tmp/backup_$ts.dump" "backups/youtube_radar_restore_check_$ts.dump"
$env:SNAPSHOT_OUT = "backups/youtube_radar_restore_check_$ts.counts.snapshot.json"
python scripts/write_db_count_snapshot.py
```

Не перенаправлять `pg_dump` через PowerShell `>` в файл — получится UTF-16 и `pg_restore` не примет архив.

Проверка restore в **отдельную** БД (не трогать рабочую):

```powershell
$env:BACKUP_VERIFY_DUMP = "backups/youtube_radar_restore_check_$ts.dump"
python scripts/verify_backup_restore_counts.py
```

---

## 6. Тестовая БД (API/E2E, не браузер на prod)

```powershell
$env:SAVED_TOPICS_POSTGRES_TEST_URL = "postgresql://USER:PASS@127.0.0.1:5433/youtube_radar_saved_topics_test"
python scripts/test_observation_readiness_e2e.py
python scripts/test_saved_topics_1_22c_postgres_regression.py
```

Пароль подставить из `.env.docker` (не коммитить). После проверки **не менять** рабочий `.env`.

---

## 7. Entrypoints smoke

```powershell
python scripts/verify_local_radar_entrypoints.py
```

---

## 8. Roadmap

| Stage | Status |
|-------|--------|
| 1.22A Attention Engine | done |
| 1.22B Analyst feed UI | done |
| 1.22B.1 Pattern Families | done |
| 1.22C Saved Topics | done |
| 1.22D Feedback + Validation | done |
| Observation window | **next** |
| LLM keyword expansion | **next** (planned) |
