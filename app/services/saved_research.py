"""Saved Research — SavedVideo + SavedFamily (Stage 1.22C)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.orm import (
    Channel,
    SavedFamily,
    SavedFamilyObservation,
    SavedResearchStatus,
    SavedVideo,
    SavedVideoObservation,
    Video,
)
from app.services.attention_engine_types import (
    AttentionEngineResult,
    PatternFamily,
    VideoWinner,
    pattern_family_to_dict,
    pattern_to_dict,
    video_winner_to_dict,
    youtube_watch_url,
)
from app.services.metrics import ensure_utc, utc_now
from app.services.saved_topics import (
    build_frozen_snapshot as build_legacy_family_frozen,
    build_observation_payload as build_legacy_family_observation_payload,
    validate_notes,
    validate_tags,
)
from app.services.saved_research_decisions import (
    record_archived,
    record_family_saved,
    record_notes_changed,
    record_restored,
    record_status_change,
    record_tags_changed,
    record_video_saved,
)
from app.services.video_snapshot_storage import get_latest_snapshots_for_videos

VIDEO_ABSENCE_MESSAGE = "Видео не входит в текущую выборку Attention Engine."

MAX_NOTES_LENGTH = 4000
MAX_TAGS = 20
MAX_TAG_LENGTH = 64

SavedResearchUserStatus = Literal["WATCHING", "WANT_TO_TEST", "TESTING", "DROPPED"]


class SavedResearchError(Exception):
    pass


class SavedVideoNotFoundError(SavedResearchError):
    pass


class SavedFamilyNotInSnapshotError(SavedResearchError):
    pass


class SavedResearchArchivedError(SavedResearchError):
    pass


@dataclass(frozen=True, slots=True)
class SavedVideoSaveResult:
    item: SavedVideo
    created: bool
    idempotent: bool


@dataclass(frozen=True, slots=True)
class SavedFamilySaveResult:
    item: SavedFamily
    created: bool
    idempotent: bool


def _load_attention_snapshot(session: Session) -> AttentionEngineResult | None:
    from app.services.attention_read_model import load_attention_snapshot

    return load_attention_snapshot(session)


def _family_map(result: AttentionEngineResult) -> dict[str, PatternFamily]:
    return {row.family_key: row for row in result.families}


def _winner_map(result: AttentionEngineResult) -> dict[str, VideoWinner]:
    return {row.video_id: row for row in result.video_winners}


def families_for_video(result: AttentionEngineResult, video_id: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for family in result.families:
        if video_id in family.video_ids:
            rows.append({"family_key": family.family_key, "label": family.label})
    rows.sort(key=lambda row: row["label"].lower())
    return rows


def build_video_frozen_payload(
    *,
    winner: VideoWinner | None,
    video: Video,
    channel: Channel | None,
    result: AttentionEngineResult | None,
    family_memberships: list[dict[str, str]],
) -> dict[str, Any]:
    title = winner.title if winner else video.title
    channel_id = winner.channel_id if winner else video.channel_id
    channel_title = winner.channel_title if winner else (channel.title if channel else "")
    payload: dict[str, Any] = {
        "identity": {
            "video_id": video.id,
            "title": title,
            "channel_id": channel_id,
            "channel_title": channel_title,
            "youtube_url": winner.youtube_url if winner else youtube_watch_url(video.id),
        },
        "evidence": video_winner_to_dict(winner) if winner else {
            "video_id": video.id,
            "title": title,
            "views": int(video.views_count),
            "from_canonical_video": True,
        },
        "context": {
            "video_topic": video.topic,
            "keyword_ids": list(winner.keyword_ids) if winner else [],
            "pattern_memberships": [],
            "family_memberships": family_memberships,
        },
    }
    if result is not None:
        payload["attention_run_id"] = result.summary.run_id
        payload["attention_computed_at"] = ensure_utc(result.summary.computed_at).isoformat()
    return payload


def build_video_observation_payload(
    *,
    video_id: str,
    result: AttentionEngineResult,
    session: Session,
) -> dict[str, Any]:
    winner = _winner_map(result).get(video_id)
    observed_at = ensure_utc(result.summary.computed_at)
    latest_snaps = get_latest_snapshots_for_videos(session, [video_id])
    snap = latest_snaps.get(video_id)
    families = families_for_video(result, video_id)
    present = winner is not None
    payload: dict[str, Any] = {
        "attention_run_id": result.summary.run_id,
        "attention_computed_at": observed_at.isoformat(),
        "video_present_in_attention": present,
        "absence_message": None if present else VIDEO_ABSENCE_MESSAGE,
        "monitoring_snapshot_available": snap is not None,
        "family_memberships": families,
    }
    if winner is not None:
        payload["winner"] = video_winner_to_dict(winner)
        payload["views"] = winner.views
        payload["vph"] = winner.vph
        payload["subscriber_count"] = winner.subscribers
        payload["breakout_rank"] = winner.breakout_rank
        payload["acceleration_state"] = winner.acceleration_state
        payload["delayed_outcome_state"] = winner.delayed_outcome_state
        payload["reason_codes"] = list(winner.reason_codes)
    elif snap is not None:
        payload["views"] = snap.views
        payload["vph"] = snap.vph
        payload["subscriber_count"] = snap.subscribers
    return payload


def _apply_video_observation_row(
    *,
    saved_video_id: int,
    run_id: str,
    observed_at: datetime,
    payload: dict[str, Any],
) -> SavedVideoObservation:
    winner = payload.get("winner") or {}
    return SavedVideoObservation(
        saved_video_id=saved_video_id,
        attention_run_id=run_id,
        observed_at=observed_at,
        video_present_in_attention=bool(payload.get("video_present_in_attention")),
        monitoring_snapshot_available=bool(payload.get("monitoring_snapshot_available")),
        views=payload.get("views"),
        vph=payload.get("vph"),
        subscriber_count=payload.get("subscriber_count"),
        breakout_rank=payload.get("breakout_rank"),
        acceleration_state=payload.get("acceleration_state"),
        delayed_outcome_state=payload.get("delayed_outcome_state"),
        family_keys_json=json.dumps(
            [row["family_key"] for row in (payload.get("family_memberships") or [])],
            ensure_ascii=False,
        ),
        reason_codes_json=json.dumps(payload.get("reason_codes") or [], ensure_ascii=False),
        payload_json=json.dumps(payload, ensure_ascii=False),
    )


def build_family_frozen_payload(*, family: PatternFamily, result: AttentionEngineResult) -> dict[str, Any]:
    return build_legacy_family_frozen(family=family, result=result)


def build_family_observation_payload(
    *,
    family: PatternFamily | None,
    result: AttentionEngineResult,
) -> dict[str, Any]:
    return build_legacy_family_observation_payload(family=family, result=result)


def _apply_family_observation_row(
    *,
    saved_family_id: int,
    run_id: str,
    observed_at: datetime,
    payload: dict[str, Any],
) -> SavedFamilyObservation:
    present = bool(payload.get("present_in_snapshot"))
    counts = payload.get("counts") or {}
    family = payload.get("family") or {}
    return SavedFamilyObservation(
        saved_family_id=saved_family_id,
        attention_run_id=run_id,
        observed_at=observed_at,
        family_present=present,
        label=str(family.get("label")) if present and family.get("label") else None,
        video_count=counts.get("video_count"),
        channel_count=counts.get("channel_count"),
        keyword_count=counts.get("keyword_count"),
        last_24h_count=counts.get("videos_last_24h"),
        previous_24h_count=counts.get("videos_previous_24h"),
        previous_48_24h_count=counts.get("videos_previous_48_24h"),
        support_sources_json=json.dumps(family.get("support_sources") or [], ensure_ascii=False),
        quality_flags_json=json.dumps(family.get("quality_flags") or [], ensure_ascii=False),
        payload_json=json.dumps(payload, ensure_ascii=False),
    )


def save_video(session: Session, *, video_id: str) -> SavedVideoSaveResult:
    video = session.get(Video, video_id)
    if video is None:
        raise SavedVideoNotFoundError(f"Video {video_id!r} not found in canonical corpus")

    existing = session.scalar(select(SavedVideo).where(SavedVideo.video_id == video_id).limit(1))
    if existing is not None:
        if existing.archived_at is not None:
            raise SavedResearchArchivedError(
                f"Saved video {video_id!r} is archived; restore before saving again",
            )
        return SavedVideoSaveResult(item=existing, created=False, idempotent=True)

    result = _load_attention_snapshot(session)
    winner = _winner_map(result).get(video_id) if result else None
    channel = session.get(Channel, video.channel_id)
    family_memberships = families_for_video(result, video_id) if result else []
    frozen_payload = build_video_frozen_payload(
        winner=winner,
        video=video,
        channel=channel,
        result=result,
        family_memberships=family_memberships,
    )
    identity = frozen_payload["identity"]
    now = utc_now()
    row = SavedVideo(
        video_id=video_id,
        saved_at=now,
        status=SavedResearchStatus.WATCHING.value,
        notes="",
        tags_json="[]",
        created_from_attention_run_id=result.summary.run_id if result else None,
        frozen_title=str(identity["title"]),
        frozen_channel_id=str(identity["channel_id"]),
        frozen_channel_title=str(identity["channel_title"]),
        frozen_payload_json=json.dumps(frozen_payload, ensure_ascii=False),
        latest_observed_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.flush()

    if result is None:
        raise SavedResearchError("Attention snapshot unavailable; cannot create initial observation")

    payload = build_video_observation_payload(video_id=video_id, result=result, session=session)
    obs = _apply_video_observation_row(
        saved_video_id=row.id,
        run_id=result.summary.run_id,
        observed_at=ensure_utc(result.summary.computed_at),
        payload=payload,
    )
    session.add(obs)
    row.latest_observed_at = obs.observed_at
    record_video_saved(session, row)
    session.flush()
    return SavedVideoSaveResult(item=row, created=True, idempotent=False)


def save_family(session: Session, *, family_key: str) -> SavedFamilySaveResult:
    result = _load_attention_snapshot(session)
    if result is None:
        raise SavedFamilyNotInSnapshotError("Attention snapshot unavailable")
    family = _family_map(result).get(family_key)
    if family is None:
        raise SavedFamilyNotInSnapshotError(
            f"Pattern family {family_key!r} not found in current Attention snapshot",
        )

    existing = session.scalar(select(SavedFamily).where(SavedFamily.family_key == family_key).limit(1))
    if existing is not None:
        if existing.archived_at is not None:
            raise SavedResearchArchivedError(
                f"Saved family {family_key!r} is archived; restore before saving again",
            )
        return SavedFamilySaveResult(item=existing, created=False, idempotent=True)

    now = utc_now()
    frozen = build_family_frozen_payload(family=family, result=result)
    row = SavedFamily(
        family_key=family_key,
        saved_at=now,
        status=SavedResearchStatus.WATCHING.value,
        notes="",
        tags_json="[]",
        created_from_attention_run_id=result.summary.run_id,
        frozen_label=family.label,
        frozen_kind=family.family_kind,
        frozen_payload_json=json.dumps(frozen, ensure_ascii=False),
        latest_observed_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.flush()

    payload = build_family_observation_payload(family=family, result=result)
    obs = _apply_family_observation_row(
        saved_family_id=row.id,
        run_id=result.summary.run_id,
        observed_at=ensure_utc(result.summary.computed_at),
        payload=payload,
    )
    session.add(obs)
    row.latest_observed_at = obs.observed_at
    record_family_saved(session, row)
    session.flush()
    return SavedFamilySaveResult(item=row, created=True, idempotent=False)


def append_saved_research_observations_for_result(
    session: Session,
    *,
    run_id: str,
    result: AttentionEngineResult,
) -> tuple[int, int]:
    """Append observations for active saved videos/families. Caller owns commit."""
    video_added = _append_video_observations(session, run_id=run_id, result=result)
    family_added = _append_family_observations(session, run_id=run_id, result=result)
    return video_added, family_added


def _append_video_observations(session: Session, *, run_id: str, result: AttentionEngineResult) -> int:
    rows = session.scalars(
        select(SavedVideo).where(SavedVideo.archived_at.is_(None)).order_by(SavedVideo.id.asc()),
    ).all()
    if not rows:
        return 0
    ids = [row.id for row in rows]
    skip = {
        r[0]
        for r in session.execute(
            select(SavedVideoObservation.saved_video_id).where(
                SavedVideoObservation.saved_video_id.in_(ids),
                SavedVideoObservation.attention_run_id == run_id,
            ),
        ).all()
    }
    added = 0
    observed_at = ensure_utc(result.summary.computed_at)
    for row in rows:
        if row.id in skip:
            continue
        payload = build_video_observation_payload(
            video_id=row.video_id,
            result=result,
            session=session,
        )
        obs = _apply_video_observation_row(
            saved_video_id=row.id,
            run_id=run_id,
            observed_at=observed_at,
            payload=payload,
        )
        session.add(obs)
        row.latest_observed_at = observed_at
        row.updated_at = utc_now()
        added += 1
    if added:
        session.flush()
    return added


def _append_family_observations(session: Session, *, run_id: str, result: AttentionEngineResult) -> int:
    rows = session.scalars(
        select(SavedFamily).where(SavedFamily.archived_at.is_(None)).order_by(SavedFamily.id.asc()),
    ).all()
    if not rows:
        return 0
    families = _family_map(result)
    ids = [row.id for row in rows]
    skip = {
        r[0]
        for r in session.execute(
            select(SavedFamilyObservation.saved_family_id).where(
                SavedFamilyObservation.saved_family_id.in_(ids),
                SavedFamilyObservation.attention_run_id == run_id,
            ),
        ).all()
    }
    added = 0
    observed_at = ensure_utc(result.summary.computed_at)
    for row in rows:
        if row.id in skip:
            continue
        family = families.get(row.family_key)
        payload = build_family_observation_payload(family=family, result=result)
        obs = _apply_family_observation_row(
            saved_family_id=row.id,
            run_id=run_id,
            observed_at=observed_at,
            payload=payload,
        )
        session.add(obs)
        row.latest_observed_at = observed_at
        row.updated_at = utc_now()
        added += 1
    if added:
        session.flush()
    return added


def patch_video(
    session: Session,
    item_id: int,
    *,
    status: SavedResearchUserStatus | None = None,
    notes: str | None = None,
    tags: list[str] | None = None,
) -> SavedVideo | None:
    row = session.get(SavedVideo, item_id)
    if row is None:
        return None
    previous_status = row.status
    had_notes = bool(row.notes.strip())
    try:
        previous_tag_count = len(json.loads(row.tags_json or "[]"))
    except json.JSONDecodeError:
        previous_tag_count = 0
    if status is not None:
        record_status_change(
            session,
            entity_kind="video",
            entity_id=row.id,
            previous=previous_status,
            new=status,
        )
        row.status = status
    if notes is not None:
        new_notes = validate_notes(notes)
        record_notes_changed(
            session,
            entity_kind="video",
            entity_id=row.id,
            had_notes=had_notes,
            has_notes=bool(new_notes.strip()),
        )
        row.notes = new_notes
    if tags is not None:
        new_tags = validate_tags(tags)
        record_tags_changed(
            session,
            entity_kind="video",
            entity_id=row.id,
            previous_count=previous_tag_count,
            new_count=len(new_tags),
        )
        row.tags_json = json.dumps(new_tags, ensure_ascii=False)
    row.updated_at = utc_now()
    session.flush()
    return row


def patch_family(
    session: Session,
    item_id: int,
    *,
    status: SavedResearchUserStatus | None = None,
    notes: str | None = None,
    tags: list[str] | None = None,
) -> SavedFamily | None:
    row = session.get(SavedFamily, item_id)
    if row is None:
        return None
    previous_status = row.status
    had_notes = bool(row.notes.strip())
    try:
        previous_tag_count = len(json.loads(row.tags_json or "[]"))
    except json.JSONDecodeError:
        previous_tag_count = 0
    if status is not None:
        record_status_change(
            session,
            entity_kind="family",
            entity_id=row.id,
            previous=previous_status,
            new=status,
        )
        row.status = status
    if notes is not None:
        new_notes = validate_notes(notes)
        record_notes_changed(
            session,
            entity_kind="family",
            entity_id=row.id,
            had_notes=had_notes,
            has_notes=bool(new_notes.strip()),
        )
        row.notes = new_notes
    if tags is not None:
        new_tags = validate_tags(tags)
        record_tags_changed(
            session,
            entity_kind="family",
            entity_id=row.id,
            previous_count=previous_tag_count,
            new_count=len(new_tags),
        )
        row.tags_json = json.dumps(new_tags, ensure_ascii=False)
    row.updated_at = utc_now()
    session.flush()
    return row


def archive_video(session: Session, item_id: int) -> SavedVideo | None:
    row = session.get(SavedVideo, item_id)
    if row is None:
        return None
    if row.archived_at is None:
        row.archived_at = utc_now()
        row.updated_at = utc_now()
        record_archived(session, entity_kind="video", entity_id=row.id)
        from app.services.saved_video_similar_watch import pause_similar_watch_for_archived_video

        pause_similar_watch_for_archived_video(session, saved_video_id=row.id)
        session.flush()
    return row


def restore_video(session: Session, item_id: int) -> SavedVideo | None:
    row = session.get(SavedVideo, item_id)
    if row is None:
        return None
    was_archived = row.archived_at is not None
    row.archived_at = None
    row.updated_at = utc_now()
    if was_archived:
        record_restored(session, entity_kind="video", entity_id=row.id)
    session.flush()
    result = _load_attention_snapshot(session)
    if result is not None:
        existing = session.scalar(
            select(SavedVideoObservation.id)
            .where(
                SavedVideoObservation.saved_video_id == row.id,
                SavedVideoObservation.attention_run_id == result.summary.run_id,
            )
            .limit(1),
        )
        if existing is None:
            payload = build_video_observation_payload(
                video_id=row.video_id,
                result=result,
                session=session,
            )
            obs = _apply_video_observation_row(
                saved_video_id=row.id,
                run_id=result.summary.run_id,
                observed_at=ensure_utc(result.summary.computed_at),
                payload=payload,
            )
            session.add(obs)
            row.latest_observed_at = obs.observed_at
            session.flush()
    return row


def archive_family(session: Session, item_id: int) -> SavedFamily | None:
    row = session.get(SavedFamily, item_id)
    if row is None:
        return None
    if row.archived_at is None:
        row.archived_at = utc_now()
        row.updated_at = utc_now()
        record_archived(session, entity_kind="family", entity_id=row.id)
        from app.services.saved_family_topic_watch import pause_family_topic_watch_for_archived_family

        pause_family_topic_watch_for_archived_family(session, saved_family_id=row.id)
        session.flush()
    return row


def restore_family(session: Session, item_id: int) -> SavedFamily | None:
    row = session.get(SavedFamily, item_id)
    if row is None:
        return None
    was_archived = row.archived_at is not None
    row.archived_at = None
    row.updated_at = utc_now()
    if was_archived:
        record_restored(session, entity_kind="family", entity_id=row.id)
    session.flush()
    result = _load_attention_snapshot(session)
    if result is not None:
        existing = session.scalar(
            select(SavedFamilyObservation.id)
            .where(
                SavedFamilyObservation.saved_family_id == row.id,
                SavedFamilyObservation.attention_run_id == result.summary.run_id,
            )
            .limit(1),
        )
        if existing is None:
            family = _family_map(result).get(row.family_key)
            payload = build_family_observation_payload(family=family, result=result)
            obs = _apply_family_observation_row(
                saved_family_id=row.id,
                run_id=result.summary.run_id,
                observed_at=ensure_utc(result.summary.computed_at),
                payload=payload,
            )
            session.add(obs)
            row.latest_observed_at = obs.observed_at
            session.flush()
    return row


def list_videos(
    session: Session,
    *,
    archived: Literal["active", "archived", "all"] = "active",
    status: str | None = None,
    tag: str | None = None,
) -> list[SavedVideo]:
    stmt = select(SavedVideo).order_by(SavedVideo.updated_at.desc(), SavedVideo.id.desc())
    if archived == "active":
        stmt = stmt.where(SavedVideo.archived_at.is_(None))
    elif archived == "archived":
        stmt = stmt.where(SavedVideo.archived_at.is_not(None))
    if status:
        stmt = stmt.where(SavedVideo.status == status)
    if tag:
        stmt = stmt.where(func.lower(SavedVideo.tags_json).like(f"%{tag.strip().lower()}%"))
    return list(session.scalars(stmt).all())


def list_families(
    session: Session,
    *,
    archived: Literal["active", "archived", "all"] = "active",
    status: str | None = None,
    tag: str | None = None,
) -> list[SavedFamily]:
    stmt = select(SavedFamily).order_by(SavedFamily.updated_at.desc(), SavedFamily.id.desc())
    if archived == "active":
        stmt = stmt.where(SavedFamily.archived_at.is_(None))
    elif archived == "archived":
        stmt = stmt.where(SavedFamily.archived_at.is_not(None))
    if status:
        stmt = stmt.where(SavedFamily.status == status)
    if tag:
        stmt = stmt.where(func.lower(SavedFamily.tags_json).like(f"%{tag.strip().lower()}%"))
    return list(session.scalars(stmt).all())


def latest_video_observations(
    session: Session,
    saved_video_ids: list[int],
) -> dict[int, SavedVideoObservation]:
    if not saved_video_ids:
        return {}
    subq = (
        select(
            SavedVideoObservation.saved_video_id,
            func.max(SavedVideoObservation.observed_at).label("max_obs"),
        )
        .where(SavedVideoObservation.saved_video_id.in_(saved_video_ids))
        .group_by(SavedVideoObservation.saved_video_id)
        .subquery()
    )
    rows = session.scalars(
        select(SavedVideoObservation)
        .join(
            subq,
            (SavedVideoObservation.saved_video_id == subq.c.saved_video_id)
            & (SavedVideoObservation.observed_at == subq.c.max_obs),
        )
        .order_by(SavedVideoObservation.id.desc()),
    ).all()
    out: dict[int, SavedVideoObservation] = {}
    for row in rows:
        out.setdefault(row.saved_video_id, row)
    return out


def latest_family_observations(
    session: Session,
    saved_family_ids: list[int],
) -> dict[int, SavedFamilyObservation]:
    if not saved_family_ids:
        return {}
    subq = (
        select(
            SavedFamilyObservation.saved_family_id,
            func.max(SavedFamilyObservation.observed_at).label("max_obs"),
        )
        .where(SavedFamilyObservation.saved_family_id.in_(saved_family_ids))
        .group_by(SavedFamilyObservation.saved_family_id)
        .subquery()
    )
    rows = session.scalars(
        select(SavedFamilyObservation)
        .join(
            subq,
            (SavedFamilyObservation.saved_family_id == subq.c.saved_family_id)
            & (SavedFamilyObservation.observed_at == subq.c.max_obs),
        )
        .order_by(SavedFamilyObservation.id.desc()),
    ).all()
    out: dict[int, SavedFamilyObservation] = {}
    for row in rows:
        out.setdefault(row.saved_family_id, row)
    return out


def list_video_history(
    session: Session,
    saved_video_id: int,
    *,
    limit: int,
    offset: int,
) -> tuple[list[SavedVideoObservation], int]:
    total = int(
        session.scalar(
            select(func.count())
            .select_from(SavedVideoObservation)
            .where(SavedVideoObservation.saved_video_id == saved_video_id),
        )
        or 0,
    )
    rows = session.scalars(
        select(SavedVideoObservation)
        .where(SavedVideoObservation.saved_video_id == saved_video_id)
        .order_by(SavedVideoObservation.observed_at.desc(), SavedVideoObservation.id.desc())
        .offset(offset)
        .limit(limit),
    ).all()
    return list(rows), total


def list_family_history(
    session: Session,
    saved_family_id: int,
    *,
    limit: int,
    offset: int,
) -> tuple[list[SavedFamilyObservation], int]:
    total = int(
        session.scalar(
            select(func.count())
            .select_from(SavedFamilyObservation)
            .where(SavedFamilyObservation.saved_family_id == saved_family_id),
        )
        or 0,
    )
    rows = session.scalars(
        select(SavedFamilyObservation)
        .where(SavedFamilyObservation.saved_family_id == saved_family_id)
        .order_by(SavedFamilyObservation.observed_at.desc(), SavedFamilyObservation.id.desc())
        .offset(offset)
        .limit(limit),
    ).all()
    return list(rows), total


def video_metric_deltas(frozen: dict[str, Any], live: SavedVideoObservation | None) -> dict[str, int] | None:
    if live is None:
        return None
    evidence = frozen.get("evidence") or {}
    deltas: dict[str, int] = {}
    for key, frozen_key in (("views", "views"), ("subscriber_count", "subscribers")):
        before = evidence.get(frozen_key if frozen_key != "subscribers" else "subscribers")
        after = getattr(live, key if key != "subscriber_count" else "subscriber_count", None)
        if before is not None and after is not None:
            deltas[key] = int(after) - int(before)
    return deltas or None


def family_count_deltas(frozen: dict[str, Any], live: SavedFamilyObservation | None) -> dict[str, int] | None:
    if live is None or not live.family_present:
        return None
    family = frozen.get("family") or {}
    deltas: dict[str, int] = {}
    for key, attr in (
        ("video_count", "video_count"),
        ("channel_count", "channel_count"),
        ("keyword_count", "keyword_count"),
    ):
        before = family.get(key)
        after = getattr(live, attr, None)
        if before is not None and after is not None:
            deltas[key] = int(after) - int(before)
    return deltas or None


def export_frozen_video(row: SavedVideo) -> dict[str, Any]:
    return json.loads(row.frozen_payload_json or "{}")


def export_frozen_family(row: SavedFamily) -> dict[str, Any]:
    return json.loads(row.frozen_payload_json or "{}")


def get_saved_video_by_video_id(session: Session, video_id: str) -> SavedVideo | None:
    return session.scalar(select(SavedVideo).where(SavedVideo.video_id == video_id).limit(1))


def get_saved_family_by_family_key(session: Session, family_key: str) -> SavedFamily | None:
    return session.scalar(select(SavedFamily).where(SavedFamily.family_key == family_key).limit(1))
