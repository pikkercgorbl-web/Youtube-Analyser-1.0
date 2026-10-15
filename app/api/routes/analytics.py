from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_youtube_client
from app.integrations.youtube.client import YouTubeApiClient, YouTubeApiError
from app.integrations.youtube.key_manager import YouTubeApiKeyError
from app.models.db import get_db
from app.models.schemas import (
    ChannelSingleAnalysisEnrichRequest,
    ChannelSingleAnalysisEnrichResponse,
    ChannelSingleAnalysisShelfMoreRequest,
    ChannelSingleAnalysisShelfMoreResponse,
    ChannelSingleAnalysisShelfRequest,
    ChannelSingleAnalysisShelfResponse,
    ChannelSingleCompareRequest,
    ChannelSingleCompareResponse,
    MassAnalysisRequest,
    MassAnalysisResponse,
    YouTubeLeadersResponse,
)
from app.services.channel_single_analysis_http import (
    run_channel_single_compare,
    run_channel_single_enrich,
    run_channel_single_shelf,
    run_channel_single_shelf_more,
)
from app.services.competitor_analysis_service import CompetitorAnalysisService

router = APIRouter()


def get_competitor_service(
    db: Session = Depends(get_db),
    youtube_client: YouTubeApiClient = Depends(get_youtube_client),
) -> CompetitorAnalysisService:
    return CompetitorAnalysisService(db, youtube_client)


@router.post("/channel/shelf", response_model=ChannelSingleAnalysisShelfResponse)
async def channel_single_shelf(
    payload: ChannelSingleAnalysisShelfRequest,
    youtube_client: YouTubeApiClient = Depends(get_youtube_client),
) -> ChannelSingleAnalysisShelfResponse:
    """InnerTube shelf for one channel (read-only, no DB writes)."""
    return await run_channel_single_shelf(youtube_client, payload)


@router.post("/channel/shelf/more", response_model=ChannelSingleAnalysisShelfMoreResponse)
async def channel_single_shelf_more(
    payload: ChannelSingleAnalysisShelfMoreRequest,
    youtube_client: YouTubeApiClient = Depends(get_youtube_client),
) -> ChannelSingleAnalysisShelfMoreResponse:
    """Append next InnerTube shelf slice (read-only, max 100 unique ids)."""
    return await run_channel_single_shelf_more(youtube_client, payload)


@router.post("/channel/enrich", response_model=ChannelSingleAnalysisEnrichResponse)
async def channel_single_enrich(
    payload: ChannelSingleAnalysisEnrichRequest,
    youtube_client: YouTubeApiClient = Depends(get_youtube_client),
) -> ChannelSingleAnalysisEnrichResponse:
    """Batch videos.list enrichment + v1 peer comparison (read-only)."""
    return await run_channel_single_enrich(youtube_client, payload)


@router.post("/channel/compare", response_model=ChannelSingleCompareResponse)
async def channel_single_compare(
    payload: ChannelSingleCompareRequest,
    youtube_client: YouTubeApiClient = Depends(get_youtube_client),
) -> ChannelSingleCompareResponse:
    """Recompute comparison from enriched feed; optional single-video API fetch for focus."""
    return await run_channel_single_compare(youtube_client, payload)


@router.post("/mass", response_model=MassAnalysisResponse)
async def mass_analysis(
    payload: MassAnalysisRequest,
    service: CompetitorAnalysisService = Depends(get_competitor_service),
) -> MassAnalysisResponse:
    """
    Mass Analysis: fetch the last 30 videos from 3–20 competitor channels via InnerTube.

    Returns a single outlier feed sorted by video_views / channel_average_views.
    """
    try:
        return await service.mass_analyze_async(
            payload.channel_refs,
            videos_per_channel=payload.videos_per_channel,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except YouTubeApiKeyError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except YouTubeApiError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/leaders", response_model=YouTubeLeadersResponse)
def youtube_leaders(
    window_days: int = Query(
        default=7,
        ge=3,
        le=7,
        description="Growth observation window (3–7 days)",
    ),
    limit: int = Query(default=10, ge=1, le=10, description="Top-N fastest-growing channels"),
    service: CompetitorAnalysisService = Depends(get_competitor_service),
) -> YouTubeLeadersResponse:
    """
    YouTube Leaders: top fastest-growing channels already stored in the database.

    Compares current subscribers/views against the closest snapshot at or before
    (now - window_days) to surface emerging micro-trends.
    """
    try:
        return service.get_youtube_leaders(window_days=window_days, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
