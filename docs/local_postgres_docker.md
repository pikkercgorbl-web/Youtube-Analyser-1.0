# Локальный PostgreSQL в Docker

Compose-проект: **youtube-radar-local** (явное имя из‑за пробелов/кириллицы в пути).

## Первый запуск

1. Скопируйте `.env.docker.example` → `.env.docker`.
2. Задайте `RADAR_LOCAL_DB_PASSWORD` (или сгенерируйте случайный пароль в `.env.docker`).
3. Из корня репозитория:

```powershell
docker compose --env-file .env.docker config --quiet
docker compose --env-file .env.docker up -d db
docker compose --env-file .env.docker ps
```

Проверка SQL:

```powershell
docker compose --env-file .env.docker exec -T db psql -U radar -d youtube_radar -c "SELECT version(), current_database();"
```

(Подставьте `RADAR_LOCAL_DB_USER` / `RADAR_LOCAL_DB_NAME`, если меняли их в `.env.docker`.)

## Порт

По умолчанию: **127.0.0.1:5433** → контейнер `5432`. Если `5433` занят, измените левую часть в `compose.yaml` (например `5434:5432`) и обновите будущий `DATABASE_URL`.

## Ежедневные команды

| Действие | Команда |
|----------|---------|
| Статус | `docker compose --env-file .env.docker ps` |
| Логи | `docker compose --env-file .env.docker logs -f db` |
| Остановка | `docker compose --env-file .env.docker stop db` |
| Снова поднять | `docker compose --env-file .env.docker up -d db` |

## Где лежат данные

Named volume **`youtube-radar-local_postgres_data`** (префикс = имя Compose-проекта). Данные переживают `docker compose --env-file .env.docker down`.

**Не выполняйте** `docker compose --env-file .env.docker down -v` — флаг `-v` удалит volume и все данные БД.

## Смена пароля в `.env.docker`

После первой инициализации Postgres **не** подхватывает новый `POSTGRES_PASSWORD` из env при простом `up`. Нужно сменить пароль внутри БД (`ALTER USER ...`) или пересоздать volume (потеря данных).

## Связь с приложением (позже)

Backend читает **`DATABASE_URL`** из `.env` (`app/core/config.py`, `app/models/db.py`). На этом этапе `.env` не меняем. Когда будете переключаться:

`postgresql://<RADAR_LOCAL_DB_USER>:<password>@127.0.0.1:5433/<RADAR_LOCAL_DB_NAME>`

Фронтенд к Postgres не подключается (`NEXT_PUBLIC_API_URL` → API).
