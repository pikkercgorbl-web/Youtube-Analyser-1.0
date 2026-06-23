from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.models.db import get_db
from app.models.schemas import SavedKeywordCreate, SavedKeywordItem
from app.services.saved_keywords_service import SavedKeywordsService

router = APIRouter()


def get_saved_keywords_service() -> SavedKeywordsService:
    return SavedKeywordsService()


@router.post("", response_model=SavedKeywordItem, status_code=status.HTTP_200_OK)
def save_keyword(
    payload: SavedKeywordCreate,
    db: Session = Depends(get_db),
    service: SavedKeywordsService = Depends(get_saved_keywords_service),
) -> SavedKeywordItem:
    """Save a keyword or update metrics if it already exists."""
    record = service.upsert(db, payload)
    return SavedKeywordItem.model_validate(record)


@router.get("", response_model=list[SavedKeywordItem])
def list_saved_keywords(
    db: Session = Depends(get_db),
    service: SavedKeywordsService = Depends(get_saved_keywords_service),
) -> list[SavedKeywordItem]:
    """Return all saved keywords sorted by score descending."""
    records = service.list_all(db)
    return [SavedKeywordItem.model_validate(record) for record in records]


@router.delete("/{keyword_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_saved_keyword(
    keyword_id: int,
    db: Session = Depends(get_db),
    service: SavedKeywordsService = Depends(get_saved_keywords_service),
) -> None:
    """Remove a saved keyword by id."""
    deleted = service.delete(db, keyword_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Saved keyword with id {keyword_id} not found",
        )
