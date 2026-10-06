"""Read-only keyword lifecycle calibration API (Stage 1.20E)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.models.db import get_db
from app.models.schemas import KeywordCalibrationDatasetResponse, KeywordCalibrationSummaryResponse
from app.services.keyword_lifecycle_calibration_service import (
    build_calibration_report,
    report_to_summary_dict,
)

router = APIRouter()


@router.get("/calibration/summary", response_model=KeywordCalibrationSummaryResponse)
def get_calibration_summary(
    lifecycle_status: str | None = Query(default=None),
    attribution_mode: str = Query(default="all_hits"),
    include_breakout: bool = Query(default=True),
    include_delayed: bool = Query(default=True),
    limit: int = Query(default=5000, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> KeywordCalibrationSummaryResponse:
    report = build_calibration_report(
        db,
        lifecycle_status=lifecycle_status,
        attribution_mode=attribution_mode,  # type: ignore[arg-type]
        include_breakout=include_breakout,
        include_delayed=include_delayed,
        limit=limit,
    )
    return KeywordCalibrationSummaryResponse(**report_to_summary_dict(report))


@router.get("/calibration/dataset", response_model=KeywordCalibrationDatasetResponse)
def get_calibration_dataset(
    lifecycle_status: str | None = Query(default=None),
    attribution_mode: str = Query(default="all_hits"),
    include_breakout: bool = Query(default=True),
    include_delayed: bool = Query(default=True),
    limit: int = Query(default=5000, ge=1, le=5000),
    include_scans: bool = Query(default=True),
    db: Session = Depends(get_db),
) -> KeywordCalibrationDatasetResponse:
    report = build_calibration_report(
        db,
        lifecycle_status=lifecycle_status,
        attribution_mode=attribution_mode,  # type: ignore[arg-type]
        include_breakout=include_breakout,
        include_delayed=include_delayed,
        limit=limit,
    )
    from dataclasses import asdict

    return KeywordCalibrationDatasetResponse(
        summary=report_to_summary_dict(report),
        keyword_rows=[asdict(r) for r in report.keyword_rows],
        scan_rows=[asdict(r) for r in report.scan_rows] if include_scans else [],
    )
