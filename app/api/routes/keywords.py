from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_youtube_client
from app.integrations.youtube.client import YouTubeApiClient, YouTubeApiError
from app.integrations.youtube.key_manager import YouTubeApiKeyError
from app.models.schemas import KeywordAnalyzeResponse
from app.services.keyword_analysis_service import KeywordAnalysisService

router = APIRouter()


def get_keyword_analysis_service(
    youtube_client: YouTubeApiClient = Depends(get_youtube_client),
) -> KeywordAnalysisService:
    return KeywordAnalysisService(youtube_client)


@router.get("/analyze", response_model=KeywordAnalyzeResponse)
def analyze_keyword(
    keyword: str = Query(..., min_length=1, max_length=256, description="Search query to analyze"),
    service: KeywordAnalysisService = Depends(get_keyword_analysis_service),
) -> KeywordAnalyzeResponse:
    """
    Keyword Analysis: evaluate evergreen traffic potential for a search query.

    Fetches the top-20 YouTube SERP, estimates search volume (views, tag/title
    frequency), measures channel authority competition, and returns an
    opportunity score from 1 to 100 plus related tags.
    """
    try:
        return service.analyze(keyword)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except YouTubeApiKeyError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except YouTubeApiError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
