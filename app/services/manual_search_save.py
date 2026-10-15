"""Save videos chosen from manual YouTube search (Stage 1.22C extension)."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.integrations.youtube.client import YouTubeChannelDetails, YouTubeVideoDetails
from app.models.orm import (
    Channel,
    SavedResearchStatus,
    SavedVideo,
    Video,
    VideoFormat,
    VideoSnapshot,
)
from app.services.discovered_video_persistence import upsert_channel_from_youtube_api
from app.services.format_enrichment_attempts import record_format_enrichment_attempt
from app.services.metrics import ensure_utc, utc_now
from app.services.revisit_executor import VideoBatchFetchClient
from app.services.saved_research import (
    SavedResearchArchivedError,
    SavedResearchError,
    SavedVideoNotFoundError,
    SavedVideoSaveResult,
    _apply_video_observation_row,
    build_video_frozen_payload,
    get_saved_video_by_video_id,
)
from app.services.saved_research_decisions import record_video_saved
from app.services.video_format_from_api import infer_video_format_from_details
from app.services.video_format_outcomes import (
    OUTCOME_LIVE,
    OUTCOME_SHORT,
    OUTCOME_STREAM,
    classify_api_format_outcome,
)
from app.services.video_format_persistence import apply_api_details_to_video_content_format
from app.services.video_published_at import PUBLISHED_AT_SOURCE_API, apply_api_published_at
from app.services.video_snapshot_storage import get_latest_snapshots_for_videos

MANUAL_SEARCH_SAVE_SOURCE = "manual_search"
MANUAL_SEARCH_OBSERVATION_RUN_PREFIX = "manual_search:"


@dataclass(frozen=True, slots=True)
class ManualSearchVideoUpsertResult:
    video: Video
    created: bool


def build_manual_search_observation_payload(
    session: Session,
    *,
    video: Video,
    channel: Channel | None,
) -> dict:
    latest = get_latest_snapshots_for_videos(session, [video.id]).get(video.id)
    payload: dict = {
        "saved_from": MANUAL_SEARCH_SAVE_SOURCE,
        "video_present_in_attention": False,
        "absence_message": None,
        "monitoring_snapshot_available": latest is not None,
        "views": int(video.views_count),
        "family_memberships": [],
    }
    if latest is not None:
        payload["snapshot_captured_at"] = ensure_utc(latest.captured_at).isoformat()
        if latest.views is not None:
            payload["views"] = int(latest.views)
        if latest.vph is not None:
            payload["vph"] = latest.vph
        if latest.subscribers is not None:
            payload["subscriber_count"] = latest.subscribers
    elif channel is not None and channel.subscribers_count:
        payload["subscriber_count"] = int(channel.subscribers_count)
    return payload


def _record_terminal_format_outcome_if_applicable(
    session: Session,
    *,
    video: Video,
    details: YouTubeVideoDetails,
    previous_format: VideoFormat,
) -> None:
    inferred = infer_video_format_from_details(details)
    outcome = classify_api_format_outcome(
        previous=previous_format,
        current=video.content_format,
        inferred=inferred,
        had_details=True,
    )
    if outcome in (OUTCOME_SHORT, OUTCOME_STREAM, OUTCOME_LIVE):
        record_format_enrichment_attempt(session, video_id=video.id, outcome=outcome)


def upsert_corpora_video_from_api_details(
    session: Session,
    details: YouTubeVideoDetails,
) -> ManualSearchVideoUpsertResult:
    """
    Upsert Video/Channel from API details for manual-search save.

    Sets ``automatic_monitoring_withheld`` only when inserting a new Video row.
    """
    video_id = (details.video_id or "").strip()
    channel_id = (details.channel_id or "").strip()
    if not video_id or not channel_id:
        raise SavedResearchError("YouTube video details missing video_id or channel_id")

    now = utc_now()
    upsert_channel_from_youtube_api(
        session,
        details=YouTubeChannelDetails(
            channel_id=channel_id,
            title=channel_id,
            subscribers_count=None,
            subscribers_known=False,
            subscribers_hidden=False,
        ),
        created_at=now,
    )

    published_at = ensure_utc(details.published_at)
    views = max(int(details.views_count or 0), 0)
    title = (details.title or "").strip() or video_id
    duration_seconds = max(int(details.duration_seconds or 0), 0)

    existing = session.get(Video, video_id)
    if existing is not None:
        previous_format = existing.content_format
        if title:
            existing.title = title
        if views > 0 and (existing.views_count or 0) <= views:
            existing.views_count = views
        apply_api_published_at(existing, published_at)
        if duration_seconds > 0:
            existing.duration_seconds = duration_seconds
        existing.channel_id = channel_id
        apply_api_details_to_video_content_format(existing, details)
        _record_terminal_format_outcome_if_applicable(
            session,
            video=existing,
            details=details,
            previous_format=previous_format,
        )
        session.flush()
        return ManualSearchVideoUpsertResult(video=existing, created=False)

    previous_format = VideoFormat.UNKNOWN
    row = Video(
        id=video_id,
        title=title,
        views_count=views,
        likes_count=max(int(details.likes_count or 0), 0),
        comments_count=max(int(details.comments_count or 0), 0),
        published_at=published_at,
        published_at_source=PUBLISHED_AT_SOURCE_API,
        duration_seconds=duration_seconds,
        content_format=VideoFormat.UNKNOWN,
        topic=None,
        tags=list(details.tags),
        channel_id=channel_id,
        automatic_monitoring_withheld=True,
    )
    session.add(row)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError:
        concurrent = session.get(Video, video_id)
        if concurrent is None:
            raise
        previous_format = concurrent.content_format
        if title:
            concurrent.title = title
        if views > 0 and (concurrent.views_count or 0) <= views:
            concurrent.views_count = views
        apply_api_published_at(concurrent, published_at)
        if duration_seconds > 0:
            concurrent.duration_seconds = duration_seconds
        concurrent.channel_id = channel_id
        apply_api_details_to_video_content_format(concurrent, details)
        _record_terminal_format_outcome_if_applicable(
            session,
            video=concurrent,
            details=details,
            previous_format=previous_format,
        )
        session.flush()
        return ManualSearchVideoUpsertResult(video=concurrent, created=False)

    apply_api_details_to_video_content_format(row, details)
    _record_terminal_format_outcome_if_applicable(
        session,
        video=row,
        details=details,
        previous_format=previous_format,
    )
    session.flush()
    return ManualSearchVideoUpsertResult(video=row, created=True)


def fetch_video_details_for_manual_save(
    youtube_client: VideoBatchFetchClient,
    video_id: str,
) -> YouTubeVideoDetails:
    vid = video_id.strip()
    if not vid:
        raise SavedResearchError("video_id is required")
    batch = youtube_client.get_videos([vid])
    if not batch:
        raise SavedVideoNotFoundError(f"YouTube video {vid!r} not found")
    return batch[0]


def save_video_from_manual_search(
    session: Session,
    details: YouTubeVideoDetails,
) -> SavedVideoSaveResult:
    video_id = (details.video_id or "").strip()
    existing = get_saved_video_by_video_id(session, video_id)
    if existing is not None:
        if existing.archived_at is not None:
            raise SavedResearchArchivedError(
                f"Saved video {video_id!r} is archived; restore before saving again",
            )
        return SavedVideoSaveResult(item=existing, created=False, idempotent=True)

    upsert = upsert_corpora_video_from_api_details(session, details)
    video = upsert.video
    channel = session.get(Channel, video.channel_id)
    frozen_payload = build_video_frozen_payload(
        winner=None,
        video=video,
        channel=channel,
        result=None,
        family_memberships=[],
    )
    frozen_payload["context"]["saved_from"] = MANUAL_SEARCH_SAVE_SOURCE
    identity = frozen_payload["identity"]
    now = utc_now()
    row = SavedVideo(
        video_id=video_id,
        saved_at=now,
        status=SavedResearchStatus.WATCHING.value,
        notes="",
        tags_json="[]",
        created_from_attention_run_id=None,
        frozen_title=str(identity["title"]),
        frozen_channel_id=str(identity["channel_id"]),
        frozen_channel_title=str(identity["channel_title"]),
        frozen_payload_json=json.dumps(frozen_payload, ensure_ascii=False),
        latest_observed_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError:
        session.rollback()
        existing = get_saved_video_by_video_id(session, video_id)
        if existing is None:
            raise
        if existing.archived_at is not None:
            raise SavedResearchArchivedError(
                f"Saved video {video_id!r} is archived; restore before saving again",
            )
        return SavedVideoSaveResult(item=existing, created=False, idempotent=True)

    obs_payload = build_manual_search_observation_payload(session, video=video, channel=channel)
    run_id = f"{MANUAL_SEARCH_OBSERVATION_RUN_PREFIX}{now.strftime('%Y%m%dT%H%M%SZ')}"
    obs = _apply_video_observation_row(
        saved_video_id=row.id,
        run_id=run_id,
        observed_at=now,
        payload=obs_payload,
    )
    session.add(obs)
    row.latest_observed_at = obs.observed_at
    record_video_saved(session, row)
    session.flush()
    return SavedVideoSaveResult(item=row, created=True, idempotent=False)


def batch_manual_search_video_context(
    session: Session,
    video_ids: list[str],
) -> list[dict]:
    ids = [v.strip() for v in video_ids if v and v.strip()]
    if not ids:
        return []

    videos = {
        row.id: row
        for row in session.scalars(select(Video).where(Video.id.in_(ids))).all()
    }
    saved_rows = session.scalars(
        select(SavedVideo).where(
            SavedVideo.video_id.in_(ids),
            SavedVideo.archived_at.is_(None),
        ),
    ).all()
    saved_by_video = {row.video_id: row for row in saved_rows}
    snap_map = get_latest_snapshots_for_videos(session, ids)

    snapshot_counts: dict[str, int] = {}
    count_rows = session.execute(
        select(VideoSnapshot.video_id, func.count())
        .where(VideoSnapshot.video_id.in_(ids))
        .group_by(VideoSnapshot.video_id),
    ).all()
    snapshot_counts = {str(vid): int(cnt) for vid, cnt in count_rows}

    items: list[dict] = []
    for vid in ids:
        snap = snap_map.get(vid)
        items.append(
            {
                "video_id": vid,
                "in_corpus": vid in videos,
                "saved_video_id": saved_by_video[vid].id if vid in saved_by_video else None,
                "snapshot_count": snapshot_counts.get(vid, 0),
                "latest_snapshot_at": ensure_utc(snap.captured_at).isoformat() if snap else None,
            },
        )
    return items
