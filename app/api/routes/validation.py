"""Read-only validation report API (Stage 1.22D)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.models.db import get_db
from app.models.schemas import ValidationReportResponse
from app.services.metrics import ensure_utc
from app.services.saved_topic_validation import build_validation_report

router = APIRouter()


@router.get("/report", response_model=ValidationReportResponse)
def validation_report(
    db: Session = Depends(get_db),
    period_start: datetime | None = Query(None),
    period_end: datetime | None = Query(None),
) -> ValidationReportResponse:
    start = ensure_utc(period_start) if period_start else None
    end = ensure_utc(period_end) if period_end else None
    payload = build_validation_report(db, period_start=start, period_end=end)
    return ValidationReportResponse.model_validate(payload)
