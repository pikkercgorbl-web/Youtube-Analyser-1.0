from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.models.db import get_db
from app.models.schemas import RadarSettingsUpdate, RadarStatusResponse, RadarToggleRequest
from app.services.explosive_channels_radar_worker import (
    apply_radar_toggle,
    get_radar_status,
    start_radar_loop_background,
)
from app.services.explosive_channels_service import ExplosiveChannelsService

router = APIRouter()


def get_explosive_channels_service() -> ExplosiveChannelsService:
    return ExplosiveChannelsService()


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
    state = apply_radar_toggle(upload_period=upload_period)

    if state["is_running"]:
        background_tasks.add_task(start_radar_loop_background)

    return RadarStatusResponse(**state)
