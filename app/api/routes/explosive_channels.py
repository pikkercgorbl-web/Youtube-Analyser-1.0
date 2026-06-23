from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.models.db import get_db
from app.models.schemas import ClearExplosiveChannelsResponse, ExplosiveChannelItem
from app.services.explosive_channels_service import (
    DEFAULT_MIN_VIEWS,
    DEFAULT_MIN_VIRAL_COEFF,
    ExplosiveChannelsService,
)

router = APIRouter()


def get_explosive_channels_service() -> ExplosiveChannelsService:
    return ExplosiveChannelsService()


@router.delete("", response_model=ClearExplosiveChannelsResponse)
def clear_explosive_channels(
    db: Session = Depends(get_db),
    service: ExplosiveChannelsService = Depends(get_explosive_channels_service),
) -> ClearExplosiveChannelsResponse:
    """Remove all explosive channel records from the database."""
    service.clear_all_channels(db)
    return ClearExplosiveChannelsResponse()


@router.get("", response_model=list[ExplosiveChannelItem])
def list_explosive_channels(
    min_views: int = Query(
        DEFAULT_MIN_VIEWS,
        ge=0,
        description="Minimum representative video views",
    ),
    min_viral_coeff: float = Query(
        DEFAULT_MIN_VIRAL_COEFF,
        ge=0,
        description="Minimum virality coefficient (views / subscribers)",
    ),
    db: Session = Depends(get_db),
    service: ExplosiveChannelsService = Depends(get_explosive_channels_service),
) -> list[ExplosiveChannelItem]:
    """Return explosive channels filtered by dynamic FR-5 thresholds."""
    records = service.list_filtered(
        db,
        min_views=min_views,
        min_viral_coeff=min_viral_coeff,
    )
    return [ExplosiveChannelItem.model_validate(record) for record in records]
