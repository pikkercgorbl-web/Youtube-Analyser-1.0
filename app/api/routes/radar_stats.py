from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.models.db import get_db
from app.models.schemas import RadarStatsResponse
from app.services.target_keywords_service import TargetKeywordsService

router = APIRouter()


def get_target_keywords_service() -> TargetKeywordsService:
    return TargetKeywordsService()


@router.get("", response_model=RadarStatsResponse)
def get_radar_stats(
    db: Session = Depends(get_db),
    service: TargetKeywordsService = Depends(get_target_keywords_service),
) -> RadarStatsResponse:
    """Return radar queue size and how many keywords were checked in the last 24 hours."""
    return service.get_radar_stats(db)
