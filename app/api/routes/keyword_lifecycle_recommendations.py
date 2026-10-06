"""Advisory lifecycle recommendations API (Stage 1.20D). Read-only — no lifecycle writes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.models.db import get_db
from app.models.schemas import (
    KeywordLifecycleRecommendationListResponse,
    KeywordLifecycleRecommendationResponse,
)
from app.services.keyword_lifecycle_recommendation_service import (
    get_lifecycle_recommendation,
    list_lifecycle_recommendations,
)
from app.services.keyword_lifecycle_recommendation_types import KeywordLifecycleRecommendation

router = APIRouter()


def _to_response(item: KeywordLifecycleRecommendation) -> KeywordLifecycleRecommendationResponse:
    return KeywordLifecycleRecommendationResponse(
        keyword_id=item.keyword_id,
        keyword=item.keyword,
        lifecycle_status=item.lifecycle_status,
        recommendation=item.recommendation,
        confidence=item.confidence,
        reason_code=item.reason_code,
        human_reason=item.human_reason,
        calibration_required=item.calibration_required,
        suggested_transition=item.suggested_transition,
        evidence_facts=list(item.evidence_facts),
        evaluated_at=item.evaluated_at,
    )


@router.get("/recommendations", response_model=KeywordLifecycleRecommendationListResponse)
def list_keyword_recommendations(
    lifecycle_status: str | None = Query(default=None),
    attribution_mode: str = Query(default="all_hits"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> KeywordLifecycleRecommendationListResponse:
    if attribution_mode not in ("all_hits", "first_discovery"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid attribution_mode")
    result = list_lifecycle_recommendations(
        db,
        lifecycle_status=lifecycle_status,
        attribution_mode=attribution_mode,  # type: ignore[arg-type]
        limit=limit,
    )
    return KeywordLifecycleRecommendationListResponse(
        evaluated_at=result.evaluated_at,
        attribution_mode=result.attribution_mode,
        items=[_to_response(item) for item in result.items],
    )


@router.get("/{keyword_id}/recommendation", response_model=KeywordLifecycleRecommendationResponse)
def get_keyword_recommendation(
    keyword_id: int,
    attribution_mode: str = Query(default="all_hits"),
    db: Session = Depends(get_db),
) -> KeywordLifecycleRecommendationResponse:
    if attribution_mode not in ("all_hits", "first_discovery"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid attribution_mode")
    item = get_lifecycle_recommendation(
        db,
        keyword_id,
        attribution_mode=attribution_mode,  # type: ignore[arg-type]
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Keyword not found")
    return _to_response(item)
