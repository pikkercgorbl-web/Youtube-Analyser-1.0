from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.models.db import get_db
from app.models.schemas import (
    RadarGenerateIdeasRequest,
    RadarGenerateIdeasResponse,
    RadarResetResponse,
    RadarSettingsUpdate,
    RadarStatusResponse,
    RadarToggleRequest,
)
from app.services.explosive_channels_radar_worker import (
    apply_radar_toggle,
    get_radar_status,
    set_radar_blacklist_words,
    start_manual_radar_scan_background,
    start_radar_loop_background,
)
from app.services.explosive_channels_service import ExplosiveChannelsService
from app.services.gemini_ideas_service import GeminiIdeasError, generate_video_title_ideas
from app.services.target_keywords_service import TargetKeywordsService

router = APIRouter()


def get_explosive_channels_service() -> ExplosiveChannelsService:
    return ExplosiveChannelsService()


def get_target_keywords_service() -> TargetKeywordsService:
    return TargetKeywordsService()


@router.get("/status", response_model=RadarStatusResponse)
def radar_status() -> RadarStatusResponse:
    """Return whether the explosive-channels radar loop is running."""
    return RadarStatusResponse(**get_radar_status())


@router.put("/settings", response_model=RadarStatusResponse)
def update_radar_settings(
    payload: RadarSettingsUpdate,
    db: Session = Depends(get_db),
    service: ExplosiveChannelsService = Depends(get_explosive_channels_service),
) -> RadarStatusResponse:
    """Persist radar upload period without toggling power state."""
    try:
        service.update_upload_period(db, payload.upload_period)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return RadarStatusResponse(**get_radar_status())


@router.post("/toggle", response_model=RadarStatusResponse)
async def radar_toggle(
    background_tasks: BackgroundTasks,
    payload: RadarToggleRequest | None = None,
) -> RadarStatusResponse:
    """Toggle the radar loop on or off; heavy scan runs in the background."""
    upload_period = payload.upload_period if payload else None
    search_query = payload.search_query.strip() if payload and payload.search_query else ""

    if payload is not None:
        set_radar_blacklist_words(payload.blacklist_words)

    state = apply_radar_toggle(upload_period=upload_period)

    if state["is_running"]:
        if search_query:
            background_tasks.add_task(start_manual_radar_scan_background, search_query)
        else:
            background_tasks.add_task(start_radar_loop_background)

    return RadarStatusResponse(**state)


@router.post("/reset", response_model=RadarResetResponse)
def reset_radar(
    db: Session = Depends(get_db),
    service: TargetKeywordsService = Depends(get_target_keywords_service),
) -> RadarResetResponse:
    """Reset radar queue cursor so the worker starts from the first target keyword."""
    total_keywords = service.reset_radar_queue(db)
    if total_keywords == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="База ключевых слов пуста — нечего сбрасывать",
        )
    return RadarResetResponse(total_keywords=total_keywords)


@router.post("/generate-ideas", response_model=RadarGenerateIdeasResponse)
def generate_radar_ideas(payload: RadarGenerateIdeasRequest) -> RadarGenerateIdeasResponse:
    """Generate clickable Russian video title ideas from popular titles via Gemini."""
    try:
        ideas = generate_video_title_ideas(payload.video_titles)
    except GeminiIdeasError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    return RadarGenerateIdeasResponse(ideas=ideas)
