from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.models.db import get_db
from app.models.schemas import TargetKeywordCreate, TargetKeywordItem
from app.services.target_keywords_service import TargetKeywordsService

router = APIRouter()


def get_target_keywords_service() -> TargetKeywordsService:
    return TargetKeywordsService()


@router.post("", response_model=TargetKeywordItem, status_code=status.HTTP_201_CREATED)
def add_target_keyword(
    payload: TargetKeywordCreate,
    db: Session = Depends(get_db),
    service: TargetKeywordsService = Depends(get_target_keywords_service),
) -> TargetKeywordItem:
    """Add a keyword to the explosive-channels radar queue."""
    try:
        record = service.create(db, payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return TargetKeywordItem.model_validate(record)


@router.get("", response_model=list[TargetKeywordItem])
def list_target_keywords(
    db: Session = Depends(get_db),
    service: TargetKeywordsService = Depends(get_target_keywords_service),
) -> list[TargetKeywordItem]:
    """Return all keywords queued for background radar scanning."""
    records = service.list_all(db)
    return [TargetKeywordItem.model_validate(record) for record in records]
