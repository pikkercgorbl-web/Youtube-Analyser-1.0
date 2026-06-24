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

# 2. Сразу после app — CORS middleware (до всех роутов и include_router)
@app.middleware("http")
async def add_cors_and_skip_warning(request: Request, call_next):
    if request.method == "OPTIONS":
        response = Response(status_code=200)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"
        return response

    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


# 3. Роуты и подключение router-ов
@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


app.include_router(videos.router, prefix="/api/v1/videos", tags=["videos"])
app.include_router(analytics.router, prefix="/api/analysis", tags=["analysis"])
app.include_router(search.router, prefix="/api/youtube-search", tags=["search"])
app.include_router(keywords.router, prefix="/api/keywords", tags=["keywords"])
app.include_router(saved_keywords.router, prefix="/api/saved-keywords", tags=["keywords"])
app.include_router(explosive_channels.router, prefix="/api/explosive-channels", tags=["analysis"])
app.include_router(radar.router, prefix="/api/radar", tags=["analysis"])
app.include_router(target_keywords.router, prefix="/api/target-keywords", tags=["analysis"])
app.include_router(radar_stats.router, prefix="/api/radar-stats", tags=["analysis"])


@app.post("/api/force-radar-scan", response_model=ForceRadarScanResponse, tags=["analysis"])
async def force_radar_scan() -> ForceRadarScanResponse:
    """Run one immediate radar scan using the next due keywords from the queue."""
    worker = get_shared_worker()

    try:
        await worker.run_force_scan()
    except YouTubeApiError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return ForceRadarScanResponse(
        status="ok",
        message="Радар выполнил принудительный поиск",
    )


@app.post("/api/search", response_model=list[EnrichedVideoModel], tags=["search"])
async def search_videos(request: SearchRequest) -> list[EnrichedVideoModel]:
    """InnerTube search enriched with channel metadata, optional local filtering."""
    sort_by_upload_date = request.sort_by.strip().lower() == "date"
    try:
        enriched = await get_enriched_search_results(
            request.query,
            max_results=SEARCH_MAX_RESULTS,
            sort_by_upload_date=sort_by_upload_date,
            save_to_db=False,
        )
    except YouTubeApiError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    filters_config = (request.filters or SearchFiltersModel()).model_dump()
    filter_service = VideoFilterService()
    filtered = filter_service.apply_filters(enriched, filters_config)
    try:
        return filter_service.sort_results(filtered, request.sort_by)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@app.post("/api/analyze-channel", response_model=AnalyzeChannelResponse, tags=["analysis"])
async def analyze_channel(body: AnalyzeChannelRequest) -> AnalyzeChannelResponse:
    """Analyze a channel or resolve channel from a video URL via InnerTube browse."""
    try:
        result = await analyze_channel_from_url(body.url)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except YouTubeApiError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    if not result.channel_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found for the provided URL",
        )

    return AnalyzeChannelResponse(
        channel_id=result.channel_id,
        channel_title=result.channel_title,
        subscribers_count=result.subscribers_count,
        channel_avatar_url=result.channel_avatar_url,
        videos=[
            ChannelAnalysisVideoItem(**video.model_dump())
            for video in result.videos
        ],
        total_videos=len(result.videos),
    )


@app.get("/api/keyword-research", response_model=KeywordResearchResponse, tags=["keywords"])
async def keyword_research(
    query: str = Query(..., min_length=1, max_length=256, description="Keyword or search query"),
) -> KeywordResearchResponse:
    """SEO keyword research: main query and related suggestions with volume and competition scores."""
    service = KeywordResearchService()
    try:
        return await service.research(query)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except YouTubeApiError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@app.get("/api/suggestions", response_model=list[str], tags=["search"])
async def search_suggestions(
    query: str = Query(..., min_length=2, max_length=256, description="Partial search query"),
) -> list[str]:
    """YouTube autocomplete suggestions (FR-1)."""
    try:
        return await get_search_suggestions(query)
    except YouTubeApiError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

# TODO: include routers
# from app.api.routes import channels
# app.include_router(channels.router, prefix="/api/v1/channels", tags=["channels"])
