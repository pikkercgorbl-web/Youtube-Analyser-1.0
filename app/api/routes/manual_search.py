"""Manual YouTube search helpers — save + local corpus context (Stage 1.22C)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_youtube_client
from app.api.routes import saved_research as saved_research_routes
from app.integrations.youtube.client import YouTubeApiClient, YouTubeApiError
from app.models.db import get_db
from app.models.schemas import (
    ManualSearchSaveVideoRequest,
    ManualSearchVideoContextBatchRequest,
    ManualSearchVideoContextBatchResponse,
    ManualSearchVideoContextItem,
    SavedVideoSaveResponse,
)
from app.services.manual_search_save import (
    batch_manual_search_video_context,
    fetch_video_details_for_manual_save,
    save_video_from_manual_search,
)
from app.services.saved_research import SavedResearchArchivedError, SavedVideoNotFoundError

router = APIRouter()


@router.post("/video-context", response_model=ManualSearchVideoContextBatchResponse)
def manual_search_video_context(
    body: ManualSearchVideoContextBatchRequest,
    db: Session = Depends(get_db),
) -> ManualSearchVideoContextBatchResponse:
    items = batch_manual_search_video_context(db, body.video_ids)
    return ManualSearchVideoContextBatchResponse(
        items=[ManualSearchVideoContextItem.model_validate(row) for row in items],
    )


@router.post("/save-video", response_model=SavedVideoSaveResponse)
def manual_search_save_video(
    body: ManualSearchSaveVideoRequest,
    db: Session = Depends(get_db),
    youtube_client: YouTubeApiClient = Depends(get_youtube_client),
) -> SavedVideoSaveResponse:
    video_id = body.video_id.strip()
    try:
        details = fetch_video_details_for_manual_save(youtube_client, video_id)
    except SavedVideoNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except YouTubeApiError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    try:
        result = save_video_from_manual_search(db, details)
        db.commit()
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
