"""Read-only Daily Intelligence API (Stage 1.23A)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.models.db import get_db
from app.models.schemas import (
    DailyIntelligenceDateListResponse,
    DailyIntelligenceFamilyDetailResponse,
    DailyIntelligenceFamilyListResponse,
    DailyIntelligenceReportSummaryResponse,
    DailyIntelligenceRunListResponse,
    DailyIntelligenceVideoAppearanceListResponse,
    DailyIntelligenceOutcomeCoverageResponse,
    DailyIntelligenceWinnerDetailResponse,
    DailyIntelligenceWinnerListResponse,
    DailyIntelligenceWinnerOutcomeFollowUpResponse,
    SavedFamilySaveResponse,
    SavedVideoSaveResponse,
)
from app.services.saved_research import (
    SavedResearchArchivedError,
    SavedVideoNotFoundError,
)
from app.services.saved_research_daily_intelligence import (
    DailyIntelligenceFindingNotFoundError,
    DailyIntelligenceReportNotFoundError,
    save_family_from_daily_intelligence,
    save_video_from_daily_intelligence,
)
from app.services.daily_intelligence_outcome_followup import (
    get_report_outcome_coverage,
    get_winner_outcome_followup,
)
from app.services.daily_intelligence_read import (
    get_report_family,
    get_report_summary,
    get_report_winner,
    list_report_dates,
    list_report_families,
    list_report_winners,
    list_run_snapshots,
    list_video_appearances,
)

router = APIRouter()


def _parse_report_date(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid report_date") from exc


@router.get("/dates", response_model=DailyIntelligenceDateListResponse)
def daily_intelligence_dates(
    limit: int = Query(default=30, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> DailyIntelligenceDateListResponse:
    items, total = list_report_dates(db, limit=limit, offset=offset)
    return DailyIntelligenceDateListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/reports/{report_date}", response_model=DailyIntelligenceReportSummaryResponse)
def daily_intelligence_report(
    report_date: str,
    db: Session = Depends(get_db),
) -> DailyIntelligenceReportSummaryResponse:
    d = _parse_report_date(report_date)
    payload = get_report_summary(db, d)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return DailyIntelligenceReportSummaryResponse.model_validate(payload)


@router.get("/reports/{report_date}/winners", response_model=DailyIntelligenceWinnerListResponse)
def daily_intelligence_report_winners(
    report_date: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> DailyIntelligenceWinnerListResponse:
    d = _parse_report_date(report_date)
    if get_report_summary(db, d) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    items, total = list_report_winners(db, d, limit=limit, offset=offset)
    return DailyIntelligenceWinnerListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/reports/{report_date}/outcome-coverage",
    response_model=DailyIntelligenceOutcomeCoverageResponse,
)
def daily_intelligence_report_outcome_coverage(
    report_date: str,
    db: Session = Depends(get_db),
) -> DailyIntelligenceOutcomeCoverageResponse:
    d = _parse_report_date(report_date)
    payload = get_report_outcome_coverage(db, d)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return DailyIntelligenceOutcomeCoverageResponse.model_validate(payload)


@router.get(
    "/reports/{report_date}/winners/{video_id}/outcome-follow-up",
    response_model=DailyIntelligenceWinnerOutcomeFollowUpResponse,
)
def daily_intelligence_report_winner_outcome_followup(
    report_date: str,
    video_id: str,
    db: Session = Depends(get_db),
) -> DailyIntelligenceWinnerOutcomeFollowUpResponse:
    d = _parse_report_date(report_date)
    payload = get_winner_outcome_followup(db, d, video_id.strip())
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Winner not found")
    return DailyIntelligenceWinnerOutcomeFollowUpResponse.model_validate(payload)


@router.get(
    "/reports/{report_date}/winners/{video_id}",
    response_model=DailyIntelligenceWinnerDetailResponse,
)
def daily_intelligence_report_winner_detail(
    report_date: str,
    video_id: str,
    db: Session = Depends(get_db),
) -> DailyIntelligenceWinnerDetailResponse:
    d = _parse_report_date(report_date)
    payload = get_report_winner(db, d, video_id)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Winner not found")
    return DailyIntelligenceWinnerDetailResponse.model_validate(payload)


@router.post(
    "/reports/{report_date}/winners/{video_id}/save-to-research",
    response_model=SavedVideoSaveResponse,
)
def daily_intelligence_save_winner_to_research(
    report_date: str,
    video_id: str,
    db: Session = Depends(get_db),
) -> SavedVideoSaveResponse:
    from app.api.routes import saved_research as saved_research_routes

    d = _parse_report_date(report_date)
    try:
        result = save_video_from_daily_intelligence(db, report_date=d, video_id=video_id.strip())
        db.commit()
    except DailyIntelligenceReportNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DailyIntelligenceFindingNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SavedVideoNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SavedResearchArchivedError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    return SavedVideoSaveResponse(
        item=saved_research_routes._video_detail(db, result.item),
        created=result.created,
        idempotent=result.idempotent,
    )


@router.get("/reports/{report_date}/families", response_model=DailyIntelligenceFamilyListResponse)
def daily_intelligence_report_families(
    report_date: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> DailyIntelligenceFamilyListResponse:
    d = _parse_report_date(report_date)
    if get_report_summary(db, d) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    items, total = list_report_families(db, d, limit=limit, offset=offset)
    return DailyIntelligenceFamilyListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/reports/{report_date}/families/{family_key}",
    response_model=DailyIntelligenceFamilyDetailResponse,
)
def daily_intelligence_report_family_detail(
    report_date: str,
    family_key: str,
    db: Session = Depends(get_db),
) -> DailyIntelligenceFamilyDetailResponse:
    d = _parse_report_date(report_date)
    payload = get_report_family(db, d, family_key)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Family not found")
    return DailyIntelligenceFamilyDetailResponse.model_validate(payload)


@router.post(
    "/reports/{report_date}/families/{family_key}/save-to-research",
    response_model=SavedFamilySaveResponse,
)
def daily_intelligence_save_family_to_research(
    report_date: str,
    family_key: str,
    db: Session = Depends(get_db),
) -> SavedFamilySaveResponse:
    from app.api.routes import saved_research as saved_research_routes

    d = _parse_report_date(report_date)
    try:
        result = save_family_from_daily_intelligence(
            db,
            report_date=d,
            family_key=family_key,
        )
        db.commit()
    except DailyIntelligenceReportNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DailyIntelligenceFindingNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SavedResearchArchivedError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    return SavedFamilySaveResponse(
        item=saved_research_routes._family_detail(db, result.item),
        created=result.created,
        idempotent=result.idempotent,
    )


@router.get("/reports/{report_date}/runs", response_model=DailyIntelligenceRunListResponse)
def daily_intelligence_report_runs(
    report_date: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> DailyIntelligenceRunListResponse:
    d = _parse_report_date(report_date)
    items, total = list_run_snapshots(db, d, limit=limit, offset=offset)
    return DailyIntelligenceRunListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/videos/{video_id}/appearances", response_model=DailyIntelligenceVideoAppearanceListResponse)
def daily_intelligence_video_appearances(
    video_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> DailyIntelligenceVideoAppearanceListResponse:
    items, total = list_video_appearances(db, video_id, limit=limit, offset=offset)
    return DailyIntelligenceVideoAppearanceListResponse(items=items, total=total, limit=limit, offset=offset)
