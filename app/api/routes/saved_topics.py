"""Saved Topics / Watchlist API (Stage 1.22C)."""

from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.models.db import get_db
from app.models.orm import SavedTopic, SavedTopicObservation
from app.models.schemas import (
    SavedTopicCreateRequest,
    SavedTopicDetailResponse,
    SavedTopicFeedbackCreateRequest,
    SavedTopicFeedbackResponse,
    SavedTopicHistoryResponse,
    SavedTopicListItemResponse,
    SavedTopicListResponse,
    SavedTopicObservationResponse,
    SavedTopicPatchRequest,
    SavedTopicSaveResponse,
    SavedTopicTimelineItemResponse,
    SavedTopicTimelineResponse,
)
from app.services.saved_topic_decisions import append_feedback, feedback_to_dict, latest_feedback_by_topic_ids
from app.services.saved_topics import (
    SavedTopicArchivedError,
    SavedTopicFamilyNotInSnapshotError,
    _parse_tags,
    archive_topic,
    count_deltas,
    frozen_label,
    get_topic,
    get_topic_by_family_key,
    latest_observations_by_topic_ids,
    list_observation_history,
    list_topic_timeline,
    list_topics,
    patch_topic,
    restore_topic,
    save_topic,
    validate_tags,
)

router = APIRouter()


def _observation_response(row: SavedTopicObservation) -> SavedTopicObservationResponse:
    return SavedTopicObservationResponse(
        id=row.id,
        attention_run_id=row.attention_run_id,
        captured_at=row.captured_at,
        payload=json.loads(row.payload_json or "{}"),
    )


def _feedback_response(row) -> SavedTopicFeedbackResponse:
    data = feedback_to_dict(row)
    return SavedTopicFeedbackResponse(
        id=data["id"],
        recorded_at=row.recorded_at,
        finding_rating=data["finding_rating"],  # type: ignore[arg-type]
        reason_comment=data["reason_comment"],
        own_test_video_url=data["own_test_video_url"],
        own_test_video_published_at=row.own_test_video_published_at,
        own_test_outcome=data["own_test_outcome"],  # type: ignore[arg-type]
        manual_metrics=data["manual_metrics"],
    )


def _detail_response(
    topic: SavedTopic,
    *,
    live: SavedTopicObservation | None,
    latest_feedback_row=None,
) -> SavedTopicDetailResponse:
    frozen = json.loads(topic.frozen_snapshot_json or "{}")
    live_payload = json.loads(live.payload_json) if live is not None else None
    deltas = count_deltas(frozen, live_payload) if live_payload is not None else None
    return SavedTopicDetailResponse(
        id=topic.id,
        family_key=topic.family_key,
        status=topic.status,  # type: ignore[arg-type]
        notes=topic.notes,
        tags=_parse_tags(topic.tags_json),
        created_at=topic.created_at,
        updated_at=topic.updated_at,
        archived_at=topic.archived_at,
        frozen_snapshot=frozen,
        live_observation=_observation_response(live) if live is not None else None,
        count_deltas=deltas,
        latest_feedback=_feedback_response(latest_feedback_row) if latest_feedback_row is not None else None,
    )


def _topic_detail(db: Session, topic: SavedTopic) -> SavedTopicDetailResponse:
    live_map = latest_observations_by_topic_ids(db, [topic.id])
    feedback_map = latest_feedback_by_topic_ids(db, [topic.id])
    return _detail_response(
        topic,
        live=live_map.get(topic.id),
        latest_feedback_row=feedback_map.get(topic.id),
    )


def _list_item(
    topic: SavedTopic,
    *,
    live: SavedTopicObservation | None,
) -> SavedTopicListItemResponse:
    present: bool | None = None
    if live is not None:
        payload = json.loads(live.payload_json or "{}")
        present = bool(payload.get("present_in_snapshot"))
    return SavedTopicListItemResponse(
        id=topic.id,
        family_key=topic.family_key,
        label=frozen_label(topic),
        status=topic.status,  # type: ignore[arg-type]
        notes=topic.notes,
        tags=_parse_tags(topic.tags_json),
        created_at=topic.created_at,
        updated_at=topic.updated_at,
        archived_at=topic.archived_at,
        latest_observation_at=live.captured_at if live is not None else None,
        present_in_latest_snapshot=present,
    )


@router.post("", response_model=SavedTopicSaveResponse, status_code=status.HTTP_200_OK)
def create_saved_topic(
    payload: SavedTopicCreateRequest,
    db: Session = Depends(get_db),
) -> SavedTopicSaveResponse:
    try:
        outcome = save_topic(db, family_key=payload.family_key.strip())
        db.commit()
    except SavedTopicFamilyNotInSnapshotError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except SavedTopicArchivedError as exc:
        db.rollback()
        topic = get_topic_by_family_key(db, payload.family_key.strip())
        if topic is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        detail = _topic_detail(db, topic)
        return SavedTopicSaveResponse(
            item=detail,
            created=False,
            idempotent=False,
            archived_requires_restore=True,
            message=str(exc),
        )

    detail = _topic_detail(db, outcome.topic)
    return SavedTopicSaveResponse(
        item=detail,
        created=outcome.created,
        idempotent=outcome.idempotent,
    )


@router.get("", response_model=SavedTopicListResponse)
def list_saved_topics(
    db: Session = Depends(get_db),
    archived: Literal["active", "archived", "all"] = Query("active"),
    q: str | None = Query(None, max_length=200),
    family_key: str | None = Query(None, max_length=160),
) -> SavedTopicListResponse:
    if family_key:
        topic = get_topic_by_family_key(db, family_key.strip())
        topics = [topic] if topic is not None else []
    else:
        topics = list_topics(db, archived=archived, query=q)
    topic_ids = [row.id for row in topics]
    live_map = latest_observations_by_topic_ids(db, topic_ids)
    items = [_list_item(row, live=live_map.get(row.id)) for row in topics]
    return SavedTopicListResponse(items=items, total=len(items))


@router.get("/{topic_id}", response_model=SavedTopicDetailResponse)
def get_saved_topic(topic_id: int, db: Session = Depends(get_db)) -> SavedTopicDetailResponse:
    topic = get_topic(db, topic_id)
    if topic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="saved topic not found")
    return _topic_detail(db, topic)


@router.patch("/{topic_id}", response_model=SavedTopicDetailResponse)
def update_saved_topic(
    topic_id: int,
    payload: SavedTopicPatchRequest,
    db: Session = Depends(get_db),
) -> SavedTopicDetailResponse:
    if payload.tags is not None:
        try:
            validate_tags(payload.tags)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    topic = patch_topic(
        db,
        topic_id,
        status=payload.status,
        notes=payload.notes,
        tags=payload.tags,
    )
    if topic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="saved topic not found")
    db.commit()
    return _topic_detail(db, topic)


@router.post("/{topic_id}/archive", response_model=SavedTopicDetailResponse)
def archive_saved_topic(topic_id: int, db: Session = Depends(get_db)) -> SavedTopicDetailResponse:
    topic = archive_topic(db, topic_id)
    if topic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="saved topic not found")
    db.commit()
    return _topic_detail(db, topic)


@router.post("/{topic_id}/restore", response_model=SavedTopicDetailResponse)
def restore_saved_topic(topic_id: int, db: Session = Depends(get_db)) -> SavedTopicDetailResponse:
    topic = restore_topic(db, topic_id)
    if topic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="saved topic not found")
    db.commit()
    return _topic_detail(db, topic)


@router.post("/{topic_id}/feedback", response_model=SavedTopicFeedbackResponse)
def add_saved_topic_feedback(
    topic_id: int,
    payload: SavedTopicFeedbackCreateRequest,
    db: Session = Depends(get_db),
) -> SavedTopicFeedbackResponse:
    topic = get_topic(db, topic_id)
    if topic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="saved topic not found")
    metrics = payload.manual_metrics.model_dump(exclude_none=True) if payload.manual_metrics else None
    try:
        row = append_feedback(
            db,
            topic_id,
            finding_rating=payload.finding_rating,
            reason_comment=payload.reason_comment,
            own_test_video_url=payload.own_test_video_url,
            own_test_video_published_at=payload.own_test_video_published_at,
            own_test_outcome=payload.own_test_outcome,
            manual_metrics=metrics,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="saved topic not found")
    db.commit()
    return _feedback_response(row)


@router.get("/{topic_id}/timeline", response_model=SavedTopicTimelineResponse)
def saved_topic_timeline(
    topic_id: int,
    db: Session = Depends(get_db),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> SavedTopicTimelineResponse:
    topic = get_topic(db, topic_id)
    if topic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="saved topic not found")
    rows, total = list_topic_timeline(db, topic_id, limit=limit, offset=offset)
    return SavedTopicTimelineResponse(
        items=[SavedTopicTimelineItemResponse.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{topic_id}/history", response_model=SavedTopicHistoryResponse)
def saved_topic_history(
    topic_id: int,
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> SavedTopicHistoryResponse:
    topic = get_topic(db, topic_id)
    if topic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="saved topic not found")
    rows, total = list_observation_history(db, topic_id, limit=limit, offset=offset)
    return SavedTopicHistoryResponse(
        items=[_observation_response(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
