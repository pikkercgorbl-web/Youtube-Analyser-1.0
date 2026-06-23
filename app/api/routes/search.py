from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_youtube_client
from app.integrations.youtube.client import YouTubeApiClient, YouTubeApiError
from app.integrations.youtube.key_manager import YouTubeApiKeyError
from app.models.db import get_db
from app.models.schemas import ExtendedSearchParams, ExtendedSearchResponse, UploadPeriod
from app.services.extended_search_service import ExtendedSearchService

router = APIRouter()


def get_extended_search_service(
    db: Session = Depends(get_db),
    youtube_client: YouTubeApiClient = Depends(get_youtube_client),
) -> ExtendedSearchService:
    return ExtendedSearchService(db, youtube_client)


@router.get("/extended", response_model=ExtendedSearchResponse)
def extended_anomaly_search(
    q: str = Query(..., min_length=1, max_length=256, description="Keyword or niche"),
    period: UploadPeriod = Query(default=UploadPeriod.WEEK, description="Upload window: 24h, week, month"),
    duration_min: int | None = Query(default=None, ge=0),
    duration_max: int | None = Query(default=None, ge=0),
    min_views: int | None = Query(default=None, ge=0),
    max_views: int | None = Query(default=None, ge=0),
    min_virality_percent: float | None = Query(
        default=None,
        ge=0,
        description="Minimum anomaly score: (views / subscribers) × 100",
    ),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: ExtendedSearchService = Depends(get_extended_search_service),
) -> ExtendedSearchResponse:
    """
    Extended anomaly search: query YouTube, enrich with channel subscribers,
    rank by virality, cache results for 1 hour.
    """
    try:
        params = ExtendedSearchParams(
            q=q,
            period=period,
            duration_min=duration_min,
            duration_max=duration_max,
            min_views=min_views,
            max_views=max_views,
            min_virality_percent=min_virality_percent,
            limit=limit,
            offset=offset,
        )
        return service.search(params)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except YouTubeApiKeyError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except YouTubeApiError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
