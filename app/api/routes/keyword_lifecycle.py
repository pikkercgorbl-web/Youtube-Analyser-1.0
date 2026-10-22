"""Keyword lifecycle API (Stage 1.16B)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db import get_db
from app.models.orm import TargetKeyword
from app.models.schemas import (
    KeywordLifecyclePatch,
    KeywordLifecycleResponse,
    KeywordPoolSummaryResponse,
    TargetKeywordItem,
)
from app.services.keyword_pool_read_model import build_keyword_pool_summary
from app.services.keyword_lifecycle_service import set_keyword_lifecycle
from app.services.keyword_schedule_state import get_keyword_schedule_state, is_keyword_due
from app.services.metrics import utc_now

router = APIRouter()


@router.get("/pool-summary", response_model=KeywordPoolSummaryResponse)
def keyword_pool_summary(db: Session = Depends(get_db)) -> KeywordPoolSummaryResponse:
    summary = build_keyword_pool_summary(db)
    return KeywordPoolSummaryResponse(
        snapshot_at=summary.snapshot_at,
        due_now=summary.due_now,
        due_next_1h=summary.due_next_1h,
        due_next_24h=summary.due_next_24h,
        not_archived_count=summary.not_archived_count,
        unique_keywords_scanned_last_24h=summary.unique_keywords_scanned_last_24h,
        keyword_scan_runs_last_24h=summary.keyword_scan_runs_last_24h,
        probation_interval_hours=summary.probation_interval_hours,
        active_interval_hours=summary.active_interval_hours,
        weak_interval_hours=summary.weak_interval_hours,
        failed_scan_retry_hours=summary.failed_scan_retry_hours,
    )


def _lifecycle_response(session: Session, record: TargetKeyword) -> KeywordLifecycleResponse:
    state = get_keyword_schedule_state(session, record.id)
    if state is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Keyword not found")
    return KeywordLifecycleResponse(
        keyword_id=state.keyword_id,
        keyword=state.keyword,
        lifecycle_status=state.lifecycle_status,
        source_type=state.source_type,
        last_checked=state.last_checked,
        next_scan_at=state.next_scan_at,
        scan_interval_seconds=state.scan_interval_seconds,
        status_changed_at=record.status_changed_at,
        status_reason=record.status_reason,
        is_due=state.is_due,
        overdue_seconds=state.overdue_seconds,
        probation_ready_for_review=state.probation_ready_for_review,
        scheduling_hint=state.scheduling_hint,
    )


@router.get("", response_model=list[TargetKeywordItem])
def list_keywords(
    db: Session = Depends(get_db),
    lifecycle_status: str | None = Query(None),
    source_type: str | None = Query(None),
    due_only: bool = Query(False),
) -> list[TargetKeywordItem]:
    stmt = select(TargetKeyword).order_by(TargetKeyword.id.asc())
    if lifecycle_status:
        stmt = stmt.where(TargetKeyword.lifecycle_status == lifecycle_status)
    if source_type:
        stmt = stmt.where(TargetKeyword.source_type == source_type)
    records = list(db.scalars(stmt).all())
    if due_only:
        now = utc_now()
        records = [row for row in records if is_keyword_due(row, now=now)]
    return [TargetKeywordItem.model_validate(row) for row in records]


@router.get("/{keyword_id}/lifecycle", response_model=KeywordLifecycleResponse)
def get_keyword_lifecycle(keyword_id: int, db: Session = Depends(get_db)) -> KeywordLifecycleResponse:
    record = db.get(TargetKeyword, keyword_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Keyword not found")
    return _lifecycle_response(db, record)


@router.patch("/{keyword_id}/lifecycle", response_model=KeywordLifecycleResponse)
def patch_keyword_lifecycle(
    keyword_id: int,
    payload: KeywordLifecyclePatch,
    db: Session = Depends(get_db),
) -> KeywordLifecycleResponse:
    try:
        record = set_keyword_lifecycle(
            db,
            keyword_id,
            payload.status,
            payload.reason,
            actor_source="api",
        )
        db.commit()
        db.refresh(record)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _lifecycle_response(db, record)
