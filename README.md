# YouTube Analyser

> Local YouTube niche-research tool: video search with channel metrics, keyword research and a background "radar" that finds fast-growing channels. FastAPI + Next.js. Pet project, built with AI-assisted development.

**YouTube Analyser** — локальный сервис для анализа ниш на YouTube. Помогает найти темы и каналы, которые сейчас набирают просмотры, до того как они станут очевидны всем.

## Что умеет

- **Поиск видео** с фильтрами и метриками каналов.
- **Разбор ключевых слов**: анализ запроса и похожих ключей, сохранение идей с заметками.
- **Массовый анализ каналов**: сравнение 3+ каналов по ключевым метрикам.
- **Радар «взрывных» каналов**: фоновый воркер по расписанию сканирует список ключевых слов и находит каналы, у которых видео набирают непропорционально много просмотров относительно подписчиков (коэффициент виральности).
- **Мониторинг**: повторные замеры найденных видео во времени, чтобы отличать устойчивый рост от случайного всплеска.
- **Attention / паттерны**: группировка «выстреливших» видео по похожим темам и форматам, watchlist тем.
- **Operations**: страница со статусом воркеров и состоянием данных.

## Стек

| Часть | Технологии |
|---|---|
| Бэкенд | Python 3.11+, FastAPI, SQLAlchemy 2, Pydantic, Alembic |
| База данных | SQLite (по умолчанию) или PostgreSQL 17 (Docker Compose) |
| Данные YouTube | YouTube InnerTube, YouTube Data API v3 (ротация нескольких ключей) |
| LLM | Google Gemini API (генерация идей) |
| Фронтенд | Next.js 14, React 18, TypeScript, Tailwind CSS, Vitest |
| Деплой (заготовка) | Render Blueprint (`render.yaml`) |

## Архитектура

```
Next.js (порт 3000)
      │  REST /api/...
      ▼
FastAPI (порт 8000) ── services/ ── integrations/youtube (InnerTube, Data API)
      │                              └─ Gemini API
      ▼
SQLite / PostgreSQL  ◄── фоновые воркеры: discovery, monitoring, outcome capture
```

- `app/api/routes/` — REST-эндпоинты (поиск, ключевые слова, радар, мониторинг, attention).
- `app/services/` — бизнес-логика: расчёт метрик, радар, ранжирование, воркеры.
- `app/integrations/youtube/` — клиент YouTube и менеджер API-ключей.
- `scripts/` — запуск воркеров, сиды и аудиты данных.
- `tests/` — автотесты бэкенда (pytest).
- `artifacts/` — замеры и выгрузки экспериментов радара; часть тестов и валидаций читает их, поэтому они хранятся в репозитории.
- `docs/` — ТЗ и дизайн-документы по этапам разработки.

## Как сделан проект

Проект разработан с помощью AI-инструментов (Claude Code, Cursor). Моя роль:

- придумал продукт и написал техническое задание и спецификации по этапам (`docs/`);
- декомпозировал задачи и ставил их AI-ассистенту;
- проверял и отлаживал сгенерированный код, интегрировал части между собой;
- настраивал окружение: `.env`, API-ключи, локальную БД, запуск воркеров.

## Быстрый старт

Нужны **Python 3.11+** и **Node.js LTS**.

### 1. Настройка

```powershell
copy .env.example .env
```

Минимальный `.env` (SQLite, работает сразу):

```env
DATABASE_URL=sqlite:///./database.db
APP_NAME=YouTube Analytics
DEBUG=true
YOUTUBE_API_KEYS=
```

`YOUTUBE_API_KEYS` необязательны: поиск и радар в основном работают через InnerTube. Ключи нужны для отдельных функций YouTube Data API. Ключи и пароли хранятся только в `.env` и не попадают в репозиторий.

Загрузить ключевые слова для радара (иначе он запустится с пустой базой ключей):

```powershell
python -m scripts.seed_target_keywords
```

### 2. Запуск

Терминал 1 — бэкенд:

```powershell
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Терминал 2 — фронтенд:

```powershell
cd frontend
npm install
copy .env.local.example .env.local
npm run dev
```

Открыть: http://localhost:3000. Документация API (Swagger): http://127.0.0.1:8000/docs

Фоновые воркеры (по желанию, каждый в своём терминале):

```powershell
python scripts/run_discovery_worker.py
python scripts/run_monitoring_worker.py
python scripts/run_outcome_capture_worker.py
```

На Windows есть готовые скрипты: `scripts/start-backend.ps1`, `scripts/start-frontend.ps1`. Подробная шпаргалка — в [ЗАПУСК.md](ЗАПУСК.md).

## Тесты

```powershell
pip install pytest
python -m pytest tests/ -q
```

Часть тестов требует локальный PostgreSQL или файлы экспериментов и в чистом окружении пропускается или падает.

## Разделы интерфейса

| Раздел | Адрес |
|---|---|
| Поиск видео | `/` |
| Ключевые слова | `/keyword-research` |
| Взрывные каналы (радар) | `/explosive-channels` |
| Сохранённые идеи | `/saved-keywords` |
| Массовый анализ | `/mass-analysis` |
| Возможности (Attention) | `/opportunities` |
| Сохранённые темы | `/saved-topics` |
| Мониторинг | `/monitoring` |
| Validation | `/validation` |

## Частые проблемы

| Симптом | Решение |
|---|---|
| Сайт не грузит данные | Проверьте, что бэкенд запущен на порту 8000 |
| Ошибки API / `Connection refused` | Проверьте `NEXT_PUBLIC_API_URL` в `frontend/.env.local` |
| Радар: «БАЗА КЛЮЧЕЙ ПУСТА» | `python -m scripts.seed_target_keywords` |
| Старые пороги на странице радара | Очистите localStorage для localhost:3000 |
| `/opportunities` отдаёт 500 в dev | Удалите `frontend/.next`, выполните `npm run build`, перезапустите |

## Статус

Пет-проект в активной разработке. Готово: поиск, ключевые слова, радар, мониторинг, attention engine, сохранённые темы, validation. В планах: разделение на админ-панель и пользовательскую часть, авторизация и несколько профилей, расширение ключевых слов через LLM.
