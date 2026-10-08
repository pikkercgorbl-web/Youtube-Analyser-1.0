# Локальный Radar на ноутбуке (PostgreSQL)

Полная схема режимов (просмотр / сбор / read models): **`docs/OPERATIONS_LAUNCH.md`**.

Рабочая база: **`youtube_radar_restore_check`** на `127.0.0.1:5433` (Docker volume `postgres_data`).

## Однократная настройка `.env`

```powershell
Set-Location "C:\Projects\Сайт анализ ниш1"
python scripts/configure_local_database_env.py
```

Скрипт:

- при необходимости архивирует **прежний удалённый** `DATABASE_URL` в `backups/migration_archive/database_url_remote.env` (gitignored, **не перезаписывает** существующий архив);
- ставит локальный `DATABASE_URL` (пароль из `.env.docker`, URL-encoding);
- включает `RADAR_ENRICHMENT_AFTER_DISCOVERY=1`.

Архивные инструменты миграции с hosted Postgres: `scripts/archive/migration/` (не для ежедневного запуска).

### Важно: переменные в уже открытых терминалах

PowerShell **кэширует** `$env:DATABASE_URL` из сессии. Значение из User/Machine или старой сессии **перекроет** `.env` для дочерних процессов.

Перед запуском backend/workers:

```powershell
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
# или закройте старые терминалы и откройте новые
```

---

## Запуск и остановка

### 1) PostgreSQL (Docker)

```powershell
Set-Location "C:\Projects\Сайт анализ ниш1"
docker compose --env-file .env.docker up -d db
docker compose --env-file .env.docker ps
```

Остановка (данные в volume **сохраняются**):

```powershell
docker compose --env-file .env.docker stop db
```

Полная остановка compose-проекта:

```powershell
docker compose --env-file .env.docker down
```

Не используйте `down -v` — это удалит volume.

Проверка БД:

```powershell
docker compose --env-file .env.docker exec db pg_isready -U radar -d youtube_radar_restore_check
```

(если `RADAR_LOCAL_DB_USER` другой — подставьте из `.env.docker`)

### 2) Backend (FastAPI)

Порт по умолчанию в скриптах: **8000** (`scripts/start-backend.ps1`).

```powershell
.\scripts\start-backend.ps1
```

Swagger: http://127.0.0.1:8000/docs

Остановка: `Ctrl+C` в том же терминале.

### 3) Frontend (Next.js)

```powershell
.\scripts\start-frontend.ps1
```

Сайт: http://localhost:3000 (`frontend/.env.local` → `NEXT_PUBLIC_API_URL=http://localhost:8000`).

### 4) Workers и read models (отдельный терминал на компонент)

```powershell
.\scripts\start-discovery.ps1
.\scripts\start-monitoring.ps1
.\scripts\start-outcome.ps1
.\scripts\start-attention-loop.ps1
.\scripts\start-keyword-performance-loop.ps1
```

Подробнее: `docs/OPERATIONS_LAUNCH.md` (таблица, `-DryRun`, Ctrl+C, Docker после сна).

---

## Проверка entrypoints (без workers)

```powershell
python scripts/verify_local_radar_entrypoints.py
```

---

## Перенос на другой PostgreSQL-сервер

Задайте `DATABASE_URL` в `.env` (URI сервера). Локальный Docker не обязателен. Архив старого URL: `backups/migration_archive/database_url_remote.env`.
