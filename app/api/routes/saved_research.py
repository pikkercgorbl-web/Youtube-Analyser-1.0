"""Saved Research API — SavedVideo + SavedFamily (Stage 1.22C)."""

from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_youtube_client
from app.integrations.youtube.client import YouTubeApiClient, YouTubeApiError
from app.models.db import get_db
from app.models.orm import SavedFamily, SavedFamilyObservation, SavedVideo, SavedVideoObservation
from app.models.schemas import (
    AttentionRelatedKeywordResponse,
    SavedFamilyCreateRequest,
    SavedFamilyDetailResponse,
    SavedFamilyHistoryResponse,
    SavedFamilyListItemResponse,
    SavedFamilyListResponse,
    SavedFamilyObservationResponse,
    SavedFamilySaveResponse,
    SavedFamilyValidationResponse,
    SavedResearchDecisionHistoryResponse,
    SavedResearchEventResponse,
    SavedResearchFeedbackCreateRequest,
    SavedResearchFeedbackEntryResponse,
    SavedResearchFeedbackHistoryResponse,
    SavedResearchFeedbackOverviewResponse,
    SavedResearchPatchRequest,
    SavedVideoCreateRequest,
    SavedVideoValidationResponse,
    SavedVideoDetailResponse,
    SavedVideoHistoryResponse,
    SavedVideoListItemResponse,
    SavedVideoListResponse,
    SavedVideoManualRefreshRequest,
    SavedVideoManualRefreshResponse,
    SavedVideoObservationResponse,
    SavedVideoSaveResponse,
)
from app.services.attention_pattern_hydrate import hydrate_related_keywords
from app.services.saved_research import (
    VIDEO_ABSENCE_MESSAGE,
    SavedFamilyNotInSnapshotError,
    SavedResearchArchivedError,
    SavedVideoNotFoundError,
    archive_family,
    archive_video,
    export_frozen_family,
    export_frozen_video,
    family_count_deltas,
    latest_family_observations,
    latest_video_observations,
    list_families,
    list_family_history,
    list_video_history,
    list_videos,
    patch_family,
    patch_video,
    restore_family,
    restore_video,
    save_family,
    save_video,
    video_metric_deltas,
)
from app.services.saved_video_manual_refresh import (
    SavedVideoManualRefreshCooldownError,
    SavedVideoManualRefreshInProgressError,
    SavedVideoManualRefreshVideoMissingError,
    SavedVideoManualRefreshYouTubeError,
    refresh_saved_video_metrics,
)
from app.services.saved_research_decisions import event_to_dict, list_decision_events
from app.services.saved_research_feedback import (
    append_analyst_feedback,
    latest_feedback_by_entities,
    list_analyst_feedback,
)
from app.services.saved_research_validation import (
    FeedbackOverviewOptions,
    build_feedback_overview,
    compute_family_validation,
    compute_video_validation,
    family_observation_is_daily_intelligence_anchor,
    measurement_source_for_video,
    observation_is_daily_intelligence_anchor,
)
from app.services.saved_topics import FAMILY_ABSENCE_MESSAGE, _parse_tags

router = APIRouter()


def _video_observation_response(row: SavedVideoObservation) -> SavedVideoObservationResponse:
    payload = json.loads(row.payload_json or "{}")
    memberships = payload.get("family_memberships") or []
    if not memberships and row.family_keys_json:
        try:
            keys = json.loads(row.family_keys_json)
            memberships = [{"family_key": k, "label": k} for k in keys]
        except json.JSONDecodeError:
            memberships = []
    return SavedVideoObservationResponse(
        id=row.id,
        attention_run_id=row.attention_run_id,
        observed_at=row.observed_at,
        video_present_in_attention=row.video_present_in_attention,
        monitoring_snapshot_available=row.monitoring_snapshot_available,
        views=row.views,
        vph=row.vph,
        subscriber_count=row.subscriber_count,
        breakout_rank=row.breakout_rank,
        acceleration_state=row.acceleration_state,
        delayed_outcome_state=row.delayed_outcome_state,
        family_memberships=memberships,
        payload=payload,
    )


def _family_observation_response(row: SavedFamilyObservation) -> SavedFamilyObservationResponse:
    payload = json.loads(row.payload_json or "{}")
    absence = FAMILY_ABSENCE_MESSAGE if not row.family_present else None
    return SavedFamilyObservationResponse(
        id=row.id,
        attention_run_id=row.attention_run_id,
        observed_at=row.observed_at,
        family_present=row.family_present,
        label=row.label,
        video_count=row.video_count,
        channel_count=row.channel_count,
        keyword_count=row.keyword_count,
        payload=payload,
        absence_message=absence,
    )


def _frozen_discovery_keyword_ids(frozen: dict) -> list[int]:
    ids: list[int] = []
    ctx = frozen.get("context") if isinstance(frozen.get("context"), dict) else {}
    evidence = frozen.get("evidence") if isinstance(frozen.get("evidence"), dict) else {}
    for source in (ctx, evidence):
        raw = source.get("keyword_ids")
        if isinstance(raw, list):
            for item in raw:
                try:
                    ids.append(int(item))
                except (TypeError, ValueError):
                    continue
    return list(dict.fromkeys(ids))


def _video_detail(db: Session, row: SavedVideo) -> SavedVideoDetailResponse:
    frozen = export_frozen_video(row)
    live_map = latest_video_observations(db, [row.id])
    live = live_map.get(row.id)
    deltas = video_metric_deltas(frozen, live)
    absence = None
    if live is not None and not live.video_present_in_attention:
        if not observation_is_daily_intelligence_anchor(live):
            absence = VIDEO_ABSENCE_MESSAGE
    return SavedVideoDetailResponse(
        id=row.id,
        video_id=row.video_id,
        status=row.status,  # type: ignore[arg-type]
        notes=row.notes,
        tags=_parse_tags(row.tags_json),
        saved_at=row.saved_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        archived_at=row.archived_at,
        created_from_attention_run_id=row.created_from_attention_run_id,
        frozen_snapshot=frozen,
        live_observation=_video_observation_response(live) if live else None,
        metric_deltas=deltas,
        attention_absence_message=absence,
        discovery_keywords=[
            AttentionRelatedKeywordResponse(**item)
            for item in hydrate_related_keywords(db, _frozen_discovery_keyword_ids(frozen))
        ],
    )


def _family_detail(db: Session, row: SavedFamily) -> SavedFamilyDetailResponse:
    frozen = export_frozen_family(row)
    live_map = latest_family_observations(db, [row.id])
    live = live_map.get(row.id)
    deltas = family_count_deltas(frozen, live)
    absence = None
    if live is not None and not live.family_present:
        if not family_observation_is_daily_intelligence_anchor(live):
            absence = FAMILY_ABSENCE_MESSAGE
    return SavedFamilyDetailResponse(
        id=row.id,
        family_key=row.family_key,
        label=row.frozen_label,
        status=row.status,  # type: ignore[arg-type]
        notes=row.notes,
        tags=_parse_tags(row.tags_json),
        saved_at=row.saved_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        archived_at=row.archived_at,
        created_from_attention_run_id=row.created_from_attention_run_id,
        frozen_snapshot=frozen,
        live_observation=_family_observation_response(live) if live else None,
        count_deltas=deltas,
        absence_message=absence,
    )


@router.post("/saved-videos", response_model=SavedVideoSaveResponse)
def create_saved_video(body: SavedVideoCreateRequest, db: Session = Depends(get_db)) -> SavedVideoSaveResponse:
    try:
        result = save_video(db, video_id=body.video_id.strip())
        db.commit()
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
        item=_video_detail(db, result.item),
        created=result.created,
        idempotent=result.idempotent,
    )


@router.get("/saved-videos", response_model=SavedVideoListResponse)
def list_saved_videos(
    archived: Literal["active", "archived", "all"] = Query(default="active"),
    status_filter: str | None = Query(default=None, alias="status"),
    tag: str | None = None,
    db: Session = Depends(get_db),
) -> SavedVideoListResponse:
    rows = list_videos(db, archived=archived, status=status_filter, tag=tag)
    live_map = latest_video_observations(db, [r.id for r in rows])
    feedback_map = latest_feedback_by_entities(db, entity_kind="video", entity_ids=[r.id for r in rows])
    items: list[SavedVideoListItemResponse] = []
    for row in rows:
        frozen = export_frozen_video(row)
        evidence = frozen.get("evidence") or {}
        context = frozen.get("context") or {}
        memberships = context.get("family_memberships") or []
        live = live_map.get(row.id)
        fb = feedback_map.get(row.id)
        items.append(
            SavedVideoListItemResponse(
                id=row.id,
                video_id=row.video_id,
                title=row.frozen_title,
                channel_title=row.frozen_channel_title,
                status=row.status,  # type: ignore[arg-type]
                notes=row.notes,
                tags=_parse_tags(row.tags_json),
                saved_at=row.saved_at,
                updated_at=row.updated_at,
                archived_at=row.archived_at,
                latest_observed_at=row.latest_observed_at,
                in_current_attention=live.video_present_in_attention if live else None,
                frozen_views=evidence.get("views"),
                frozen_vph=evidence.get("vph"),
                current_views=live.views if live else None,
                current_vph=live.vph if live else None,
                related_family_labels=[m.get("label", "") for m in memberships if m.get("label")],
                latest_analyst_verdict=fb.verdict if fb else None,  # type: ignore[arg-type]
                latest_analyst_verdict_at=fb.created_at if fb else None,
                latest_measurement_source=measurement_source_for_video(live),
            ),
        )
    return SavedVideoListResponse(items=items, total=len(items))


@router.get("/saved-videos/{item_id}", response_model=SavedVideoDetailResponse)
def get_saved_video(item_id: int, db: Session = Depends(get_db)) -> SavedVideoDetailResponse:
    row = db.get(SavedVideo, item_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved video not found")
    return _video_detail(db, row)


@router.patch("/saved-videos/{item_id}", response_model=SavedVideoDetailResponse)
def patch_saved_video(
    item_id: int,
    body: SavedResearchPatchRequest,
    db: Session = Depends(get_db),
) -> SavedVideoDetailResponse:
    try:
        row = patch_video(
            db,
            item_id,
            status=body.status,
            notes=body.notes,
            tags=body.tags,
        )
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved video not found")
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _video_detail(db, row)


@router.post("/saved-videos/{item_id}/archive", response_model=SavedVideoDetailResponse)
def archive_saved_video(item_id: int, db: Session = Depends(get_db)) -> SavedVideoDetailResponse:
    row = archive_video(db, item_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved video not found")
    db.commit()
    return _video_detail(db, row)


@router.post("/saved-videos/{item_id}/restore", response_model=SavedVideoDetailResponse)
def restore_saved_video(item_id: int, db: Session = Depends(get_db)) -> SavedVideoDetailResponse:
    row = restore_video(db, item_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved video not found")
    db.commit()
    return _video_detail(db, row)


@router.post(
    "/saved-videos/{item_id}/refresh-metrics",
    response_model=SavedVideoManualRefreshResponse,
)
def refresh_saved_video_metrics_route(
    item_id: int,
    body: SavedVideoManualRefreshRequest | None = None,
    db: Session = Depends(get_db),
    youtube_client: YouTubeApiClient = Depends(get_youtube_client),
) -> SavedVideoManualRefreshResponse:
    try:
        result = refresh_saved_video_metrics(
            db,
            item_id,
            youtube_client,
            capture_run_id=body.capture_run_id if body else None,
        )
        db.commit()
    except SavedVideoNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SavedResearchArchivedError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except SavedVideoManualRefreshCooldownError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except SavedVideoManualRefreshInProgressError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except SavedVideoManualRefreshVideoMissingError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SavedVideoManualRefreshYouTubeError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except YouTubeApiError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    row = result.item
    return SavedVideoManualRefreshResponse(
        item=_video_detail(db, row),
        capture_run_id=result.capture_run_id,
        measured_at=result.measured_at,
        snapshot_id=result.snapshot_id,
        metrics_source=result.metrics_source,
        idempotent=result.idempotent,
        cooldown_seconds=result.cooldown_seconds,
    )


@router.get("/saved-videos/{item_id}/history", response_model=SavedVideoHistoryResponse)
def saved_video_history(
    item_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> SavedVideoHistoryResponse:
    if db.get(SavedVideo, item_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved video not found")
    rows, total = list_video_history(db, item_id, limit=limit, offset=offset)
    return SavedVideoHistoryResponse(
        items=[_video_observation_response(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/saved-families", response_model=SavedFamilySaveResponse)
def create_saved_family(body: SavedFamilyCreateRequest, db: Session = Depends(get_db)) -> SavedFamilySaveResponse:
    try:
        result = save_family(db, family_key=body.family_key.strip())
        db.commit()
    except SavedFamilyNotInSnapshotError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SavedResearchArchivedError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    return SavedFamilySaveResponse(
        item=_family_detail(db, result.item),
        created=result.created,
        idempotent=result.idempotent,
    )


@router.get("/saved-families", response_model=SavedFamilyListResponse)
def list_saved_families(
    archived: Literal["active", "archived", "all"] = Query(default="active"),
    status_filter: str | None = Query(default=None, alias="status"),
    tag: str | None = None,
    db: Session = Depends(get_db),
) -> SavedFamilyListResponse:
    rows = list_families(db, archived=archived, status=status_filter, tag=tag)
    live_map = latest_family_observations(db, [r.id for r in rows])
    feedback_map = latest_feedback_by_entities(db, entity_kind="family", entity_ids=[r.id for r in rows])
    items: list[SavedFamilyListItemResponse] = []
    for row in rows:
        frozen = export_frozen_family(row)
        family = frozen.get("family") or {}
        live = live_map.get(row.id)
        fb = feedback_map.get(row.id)
        items.append(
            SavedFamilyListItemResponse(
                id=row.id,
                family_key=row.family_key,
                label=row.frozen_label,
                status=row.status,  # type: ignore[arg-type]
                notes=row.notes,
                tags=_parse_tags(row.tags_json),
                saved_at=row.saved_at,
                updated_at=row.updated_at,
                archived_at=row.archived_at,
                latest_observed_at=row.latest_observed_at,
                family_present=live.family_present if live else None,
                frozen_video_count=family.get("video_count"),
                current_video_count=live.video_count if live else None,
                frozen_channel_count=family.get("channel_count"),
                current_channel_count=live.channel_count if live else None,
                latest_analyst_verdict=fb.verdict if fb else None,  # type: ignore[arg-type]
                latest_analyst_verdict_at=fb.created_at if fb else None,
            ),
        )
    return SavedFamilyListResponse(items=items, total=len(items))


@router.get("/saved-families/{item_id}", response_model=SavedFamilyDetailResponse)
def get_saved_family(item_id: int, db: Session = Depends(get_db)) -> SavedFamilyDetailResponse:
    row = db.get(SavedFamily, item_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved family not found")
    return _family_detail(db, row)


@router.patch("/saved-families/{item_id}", response_model=SavedFamilyDetailResponse)
def patch_saved_family(
    item_id: int,
    body: SavedResearchPatchRequest,
    db: Session = Depends(get_db),
) -> SavedFamilyDetailResponse:
    try:
        row = patch_family(
            db,
            item_id,
            status=body.status,
            notes=body.notes,
            tags=body.tags,
        )
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved family not found")
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _family_detail(db, row)


@router.post("/saved-families/{item_id}/archive", response_model=SavedFamilyDetailResponse)
def archive_saved_family(item_id: int, db: Session = Depends(get_db)) -> SavedFamilyDetailResponse:
    row = archive_family(db, item_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved family not found")
    db.commit()
    return _family_detail(db, row)


@router.post("/saved-families/{item_id}/restore", response_model=SavedFamilyDetailResponse)
def restore_saved_family(item_id: int, db: Session = Depends(get_db)) -> SavedFamilyDetailResponse:
    row = restore_family(db, item_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved family not found")
    db.commit()
    return _family_detail(db, row)


@router.get("/saved-families/{item_id}/history", response_model=SavedFamilyHistoryResponse)
def saved_family_history(
    item_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> SavedFamilyHistoryResponse:
    if db.get(SavedFamily, item_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved family not found")
    rows, total = list_family_history(db, item_id, limit=limit, offset=offset)
    return SavedFamilyHistoryResponse(
        items=[_family_observation_response(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def _event_response(row) -> SavedResearchEventResponse:
    data = event_to_dict(row)
    return SavedResearchEventResponse.model_validate(data)


def _feedback_entry_response(row) -> SavedResearchFeedbackEntryResponse:
    return SavedResearchFeedbackEntryResponse(
        id=row.id,
        entity_kind=row.entity_kind,  # type: ignore[arg-type]
        entity_id=row.entity_id,
        verdict=row.verdict,  # type: ignore[arg-type]
        reason=row.reason,
        created_at=row.created_at,
    )


@router.get("/saved-research/feedback-overview", response_model=SavedResearchFeedbackOverviewResponse)
def saved_research_feedback_overview(
    archived: Literal["active", "archived", "all"] = Query(default="active"),
    video_limit: int = Query(default=50, ge=1, le=200),
    video_offset: int = Query(default=0, ge=0),
    family_limit: int = Query(default=50, ge=1, le=200),
    family_offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> SavedResearchFeedbackOverviewResponse:
    payload = build_feedback_overview(
        db,
        FeedbackOverviewOptions(
            archived=archived,
            video_limit=video_limit,
            video_offset=video_offset,
            family_limit=family_limit,
            family_offset=family_offset,
        ),
    )
    return SavedResearchFeedbackOverviewResponse.model_validate(payload)


@router.get("/saved-videos/{item_id}/validation", response_model=SavedVideoValidationResponse)
def saved_video_validation(item_id: int, db: Session = Depends(get_db)) -> SavedVideoValidationResponse:
    row = db.get(SavedVideo, item_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved video not found")
    live_map = latest_video_observations(db, [row.id])
    obs_count = int(
        db.scalar(
            select(func.count())
            .select_from(SavedVideoObservation)
            .where(SavedVideoObservation.saved_video_id == row.id),
        )
        or 0,
    )
    validation = compute_video_validation(
        frozen=export_frozen_video(row),
        live=live_map.get(row.id),
        saved_at=row.saved_at,
        observation_count=obs_count,
    )
    return SavedVideoValidationResponse(
        video_id=row.video_id,
        saved_at=row.saved_at,
        status=row.status,  # type: ignore[arg-type]
        validation=validation,
    )


@router.get("/saved-families/{item_id}/validation", response_model=SavedFamilyValidationResponse)
def saved_family_validation(item_id: int, db: Session = Depends(get_db)) -> SavedFamilyValidationResponse:
    row = db.get(SavedFamily, item_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved family not found")
    live_map = latest_family_observations(db, [row.id])
    obs_count = int(
        db.scalar(
            select(func.count())
            .select_from(SavedFamilyObservation)
            .where(SavedFamilyObservation.saved_family_id == row.id),
        )
        or 0,
    )
    validation = compute_family_validation(
        frozen=export_frozen_family(row),
        live=live_map.get(row.id),
        observation_count=obs_count,
    )
    return SavedFamilyValidationResponse(
        family_key=row.family_key,
        saved_at=row.saved_at,
        status=row.status,  # type: ignore[arg-type]
        validation=validation,
    )


@router.post("/saved-videos/{item_id}/feedback", response_model=SavedResearchFeedbackEntryResponse)
def add_saved_video_feedback(
    item_id: int,
    body: SavedResearchFeedbackCreateRequest,
    db: Session = Depends(get_db),
) -> SavedResearchFeedbackEntryResponse:
    try:
        row = append_analyst_feedback(
            db,
            entity_kind="video",
            entity_id=item_id,
            verdict=body.verdict,
            reason=body.reason,
        )
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved video not found")
        db.commit()
    except SavedResearchArchivedError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _feedback_entry_response(row)


@router.get("/saved-videos/{item_id}/feedback", response_model=SavedResearchFeedbackHistoryResponse)
def saved_video_feedback_history(
    item_id: int,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> SavedResearchFeedbackHistoryResponse:
    if db.get(SavedVideo, item_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved video not found")
    latest, rows, total = list_analyst_feedback(
        db,
        entity_kind="video",
        entity_id=item_id,
        limit=limit,
        offset=offset,
    )
    return SavedResearchFeedbackHistoryResponse(
        latest=_feedback_entry_response(latest) if latest else None,
        items=[_feedback_entry_response(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/saved-families/{item_id}/feedback", response_model=SavedResearchFeedbackEntryResponse)
def add_saved_family_feedback(
    item_id: int,
    body: SavedResearchFeedbackCreateRequest,
    db: Session = Depends(get_db),
) -> SavedResearchFeedbackEntryResponse:
    try:
        row = append_analyst_feedback(
            db,
            entity_kind="family",
            entity_id=item_id,
            verdict=body.verdict,
            reason=body.reason,
        )
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved family not found")
        db.commit()
    except SavedResearchArchivedError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _feedback_entry_response(row)


@router.get("/saved-families/{item_id}/feedback", response_model=SavedResearchFeedbackHistoryResponse)
def saved_family_feedback_history(
    item_id: int,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> SavedResearchFeedbackHistoryResponse:
    if db.get(SavedFamily, item_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved family not found")
    latest, rows, total = list_analyst_feedback(
        db,
        entity_kind="family",
        entity_id=item_id,
        limit=limit,
        offset=offset,
    )
    return SavedResearchFeedbackHistoryResponse(
        latest=_feedback_entry_response(latest) if latest else None,
        items=[_feedback_entry_response(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/saved-videos/{item_id}/decision-events", response_model=SavedResearchDecisionHistoryResponse)
def saved_video_decision_events(
    item_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> SavedResearchDecisionHistoryResponse:
    if db.get(SavedVideo, item_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved video not found")
    rows, total = list_decision_events(
        db,
        entity_kind="video",
        entity_id=item_id,
        limit=limit,
        offset=offset,
    )
    return SavedResearchDecisionHistoryResponse(
        items=[_event_response(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/saved-families/{item_id}/decision-events", response_model=SavedResearchDecisionHistoryResponse)
def saved_family_decision_events(
    item_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> SavedResearchDecisionHistoryResponse:
    if db.get(SavedFamily, item_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved family not found")
    rows, total = list_decision_events(
        db,
        entity_kind="family",
        entity_id=item_id,
        limit=limit,
        offset=offset,
    )
    return SavedResearchDecisionHistoryResponse(
        items=[_event_response(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
