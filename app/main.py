"""
FastAPI application entry point.

Запуск сервера (из корня проекта):

    pip install -r requirements.txt
    python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

После запуска:
    - API:          http://127.0.0.1:8000
    - Swagger UI:   http://127.0.0.1:8000/docs
    - InnerTube:    POST http://127.0.0.1:8000/api/search  body: {"query": "...", "filters": {...}}
    - Suggestions:  GET http://127.0.0.1:8000/api/suggestions?query=python
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.routes import analytics, explosive_channels, keywords, radar, radar_stats, saved_keywords, search, target_keywords, videos
from app.core.config import settings
from app.integrations.youtube.client import (
    EnrichedVideoModel,
    YouTubeApiError,
    analyze_channel_from_url,
    get_enriched_search_results,
    get_search_suggestions,
)
from app.models.db import Base, SessionLocal, engine
from app.db.migrations import run_startup_migrations
import app.models.orm  # noqa: F401 — register ORM models with Base.metadata
import app.models.radar_v01  # noqa: F401 — register Radar v0.1 models with Base.metadata
from app.models.schemas import (
    AnalyzeChannelRequest,
    AnalyzeChannelResponse,
    ChannelAnalysisVideoItem,
    KeywordResearchResponse,
    ForceRadarScanResponse,
    SearchFiltersModel,
    SearchRequest,
)
from app.services.explosive_channels_radar_worker import get_shared_worker, stop_radar
from app.services.explosive_channels_service import ExplosiveChannelsService
from app.services.keyword_research_service import KeywordResearchService
from app.services.video_filter_service import VideoFilterService


logger = logging.getLogger(__name__)

# Number of videos requested from InnerTube for a user-facing search.
# The client caps a single search at 50 results across continuations.
SEARCH_MAX_RESULTS = 50


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Application startup and shutdown hooks."""
    # TODO: replace with Alembic migrations in production
    Base.metadata.create_all(bind=engine)
    run_startup_migrations(engine)

    db = SessionLocal()
    try:
        removed = ExplosiveChannelsService().purge_placeholder_channels(db)
        if removed:
            logger.info("Removed %s placeholder explosive channel record(s)", removed)
    finally:
        db.close()

    yield

    await stop_radar()
    # TODO: graceful shutdown (close connections, flush queues)


# 1. Сначала создаём приложение
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    debug=settings.debug,
    lifespan=lifespan,
)

# 2. Сразу после app — CORS middleware (до всех роутов и include_router).
#    Используем штатный CORSMiddleware FastAPI: он сам корректно отвечает на
#    preflight (OPTIONS) и проставляет заголовки на ВСЕ ответы.
#
#    allow_credentials=False, поэтому "*" в allow_origins разрешён. Если в
#    будущем понадобятся cookie/credentials — заменить "*" на конкретный
#    список доменов (например, "https://<your-app>.vercel.app").
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=86400,
)


# Гарантируем CORS-заголовки даже на ответах с ошибкой (500 и т.п.),
# которые иначе формирует внешний обработчик ошибок Starlette уже ПОСЛЕ
# CORSMiddleware — без этого браузер показывает "CORS error" вместо 500.
class _EnsureCorsOnErrorsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
        except Exception:
            response = Response("Internal Server Error", status_code=500)
        response.headers.setdefault("Access-Control-Allow-Origin", "*")
        return response


app.add_middleware(_EnsureCorsOnErrorsMiddleware)

