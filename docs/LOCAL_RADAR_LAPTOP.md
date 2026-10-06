# Локальный Radar на ноутбуке (PostgreSQL)

Рабочая база: **`youtube_radar_restore_check`** на `127.0.0.1:5433` (Docker volume `postgres_data`).  
Supabase не трогаем; прежний `DATABASE_URL` сохранён в **`.env.supabase.remote`** (gitignored).

## Однократная настройка `.env`

```powershell
Set-Location "C:\Projects\Сайт анализ ниш1"
python scripts/configure_local_database_env.py
```

Скрипт:

- копирует удалённый `DATABASE_URL` в `.env.supabase.remote` (если ещё нет бэкапа);
- ставит локальный `DATABASE_URL` (пароль из `.env.docker`, URL-encoding);
- включает `RADAR_ENRICHMENT_AFTER_DISCOVERY=1`.

### Важно: переменные в уже открытых терминалах

PowerShell **кэширует** `$env:DATABASE_URL` из сессии. Если вы раньше экспортировали Supabase URL, он **перекроет** `.env` для дочерних процессов.

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

### 4) Workers (запускать отдельно, когда нужны)

Убедитесь, что `.env` указывает на локальную БД и **нет** `$env:DATABASE_URL` из Supabase.

**Discovery**

```powershell
python scripts/run_discovery_worker.py --interval-seconds 300 --error-backoff-seconds 300 --batch-size 5
```

**Monitoring**

```powershell
python scripts/run_monitoring_worker.py --interval-seconds 900 --error-backoff-seconds 300
```

**Outcome capture**

```powershell
python scripts/run_outcome_capture_worker.py --interval-seconds 3600
```

Остановка каждого: `Ctrl+C`.

---

## Attention refresh (без UI compute)

Разовый пересчёт и запись snapshot:

```powershell
Set-Location "C:\Projects\Сайт анализ ниш1"
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
python scripts/refresh_attention_engine.py
```

JSON-вывод:

```powershell
python scripts/refresh_attention_engine.py --json
```

Dry-run (не пишет в БД):

```powershell
python scripts/refresh_attention_engine.py --dry-run
```

### Расписание на Windows (Task Scheduler)

1. **Task Scheduler** → Create Task.
2. Trigger: Daily (или каждые N часов).
3. Action: Start a program  
   - Program: `python` (или полный путь к `python.exe`)  
   - Arguments: `scripts/refresh_attention_engine.py`  
   - Start in: `C:\Projects\Сайт анализ ниш1`
4. В «Start in» проект должен видеть `.env`; не задавайте в задаче старый `DATABASE_URL`.

Пример PowerShell one-liner для теста задачи:

```powershell
powershell -NoProfile -Command "Set-Location 'C:\Projects\Сайт анализ ниш1'; Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue; python scripts/refresh_attention_engine.py"
```

---

## Backup локальной БД (`pg_dump`)

```powershell
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
New-Item -ItemType Directory -Force -Path ".\backups" | Out-Null
docker compose --env-file .env.docker exec -T db pg_dump -U radar -d youtube_radar_restore_check -Fc -f - > ".\backups\youtube_radar_restore_check_$ts.dump"
```

Пользователя `-U` замените на `RADAR_LOCAL_DB_USER` из `.env.docker`.  
Формат `-Fc` — custom, удобен для `pg_restore`.

---

## Проверка entrypoints (без workers)

```powershell
python scripts/verify_local_radar_entrypoints.py
```

---

## Вернуть Supabase (вручную)

Скопируйте `DATABASE_URL` из `.env.supabase.remote` обратно в `.env`. Supabase в облаке не изменяется.
