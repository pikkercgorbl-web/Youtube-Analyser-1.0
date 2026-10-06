"""Keyword expansion API (Stage 1.16C)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models.db import get_db
from app.models.schemas import KeywordExpansionSummaryResponse
from app.services.keyword_expansion_service import (
    KeywordExpansionConfig,
    run_keyword_expansion_sync,
)

router = APIRouter()


class KeywordExpansionRequest(BaseModel):
    dry_run: bool = False
    max_new_keywords_per_seed_per_run: int = Field(default=10, ge=1, le=50)


@router.post("/{keyword_id}/expand", response_model=KeywordExpansionSummaryResponse)
def expand_keyword(
    keyword_id: int,
    payload: KeywordExpansionRequest,
    db: Session = Depends(get_db),
) -> KeywordExpansionSummaryResponse:
    config = KeywordExpansionConfig(
        max_new_keywords_per_seed_per_run=payload.max_new_keywords_per_seed_per_run,
    )
    summary = run_keyword_expansion_sync(
        db,
        keyword_id,
        config=config,
        dry_run=payload.dry_run,
    )
    if summary.errors == ("seed_not_found",):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Keyword not found")
    if summary.errors and summary.errors[0].startswith("seed_"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=summary.errors[0])
    if not payload.dry_run:
        db.commit()
    else:
        db.rollback()
    return KeywordExpansionSummaryResponse(
        discovery_run_id=summary.discovery_run_id,
        cycle_status=summary.cycle_status,
        seed_keyword_count=summary.seed_keyword_count,
        source_count=summary.source_count,
        raw_candidate_count=summary.raw_candidate_count,
        normalized_unique_count=summary.normalized_unique_count,
        existing_keyword_count=summary.existing_keyword_count,
        rejected_count=summary.rejected_count,
        deferred_count=summary.deferred_count,
        created_keyword_count=summary.created_keyword_count,
        per_source_counts=summary.per_source_counts,
        per_seed_counts={str(k): v for k, v in summary.per_seed_counts.items()},
        errors=list(summary.errors),
        runtime_seconds=summary.runtime_seconds,
    )
