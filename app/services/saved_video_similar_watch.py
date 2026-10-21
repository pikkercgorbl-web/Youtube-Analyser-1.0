"""SavedVideo similar-search watch: confirm queries, scan, schedule (v1)."""

from __future__ import annotations

import asyncio
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.integrations.youtube.client import YouTubeVideoDetails
from app.models.orm import (
    SavedVideo,
    SavedVideoSimilarFinding,
    SavedVideoSimilarFindingFeedback,
    SavedVideoSimilarScan,
    SavedVideoSimilarWatch,
)
from app.services.manual_search_save import save_video_from_manual_search
from app.services.metrics import ensure_utc, utc_now
from app.services.saved_research import SavedResearchArchivedError, SavedResearchError, SavedVideoNotFoundError
from app.services.saved_video_similar_query_suggest import parse_frozen_json, suggest_similar_search_queries
from app.services.saved_video_similar_relevance import (
    attach_relevance_to_payload,
    build_anchor_profile,
    relevance_from_payload,
)
from app.services.saved_video_similar_search import search_similar_videos_for_query, video_search_to_payload
from app.services.saved_video_similar_watch_config import (
    saved_video_similar_watch_settings,
    similar_watch_load_estimate,
)

WatchStatus = Literal["draft", "active", "paused"]
DisplayState = Literal[
    "not_configured",
    "draft",
    "paused",
    "scanning",
    "never_checked",
    "empty",
    "has_results",
    "partial_error",
]

WATCH_DRAFT = "draft"
WATCH_ACTIVE = "active"
WATCH_PAUSED = "paused"


class SimilarWatchError(SavedResearchError):
    pass


class SimilarWatchNotFoundError(SimilarWatchError):
    pass


class SimilarWatchLimitError(SimilarWatchError):
    pass


class SimilarWatchScanInProgressError(SimilarWatchError):
    pass


@dataclass(frozen=True, slots=True)
class SimilarWatchScanSummary:
    scan_id: int
    scan_run_id: str
    queries_attempted: int
    queries_failed: int
    new_findings_count: int
    display_state: str


def _generate_scan_run_id(*, now: datetime | None = None) -> str:
    reference = ensure_utc(now or utc_now())
    return f"saved_similar_{reference.strftime('%Y%m%dT%H%M%SZ')}_{secrets.token_hex(4)}"


def _load_queries(watch: SavedVideoSimilarWatch) -> list[str]:
    try:
        raw = json.loads(watch.queries_json or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    return [str(q).strip() for q in raw if str(q).strip()]


def _load_suggested(watch: SavedVideoSimilarWatch) -> list[str]:
    try:
        raw = json.loads(watch.suggested_queries_json or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    return [str(q).strip() for q in raw if str(q).strip()]


def count_active_similar_watches(session: Session) -> int:
    from app.services.saved_library_watch_batch import count_active_library_watches

    return count_active_library_watches(session)


def get_or_create_watch_draft(session: Session, *, saved_video_id: int) -> SavedVideoSimilarWatch:
    row = session.get(SavedVideo, saved_video_id)
    if row is None:
        raise SavedVideoNotFoundError(f"Saved video id={saved_video_id} not found")
    if row.archived_at is not None:
        raise SavedResearchArchivedError("Saved video is archived")

    watch = session.get(SavedVideoSimilarWatch, saved_video_id)
    frozen = parse_frozen_json(row.frozen_payload_json)
    suggestions = suggest_similar_search_queries(title=row.frozen_title, frozen_payload=frozen)

    if watch is None:
        now = utc_now()
        watch = SavedVideoSimilarWatch(
            saved_video_id=saved_video_id,
            status=WATCH_DRAFT,
            suggested_queries_json=json.dumps(suggestions, ensure_ascii=False),
            last_display_state="draft",
            created_at=now,
            updated_at=now,
        )
        session.add(watch)
        session.flush()
        return watch

    watch.suggested_queries_json = json.dumps(suggestions, ensure_ascii=False)
    if watch.status == WATCH_DRAFT:
        watch.last_display_state = "draft"
    watch.updated_at = utc_now()
    session.flush()
    return watch


def confirm_similar_watch_queries(
    session: Session,
    *,
    saved_video_id: int,
    queries: list[str],
) -> SavedVideoSimilarWatch:
    cfg = saved_video_similar_watch_settings
    cleaned = list(dict.fromkeys(q.strip() for q in queries if q and q.strip()))
    if not cleaned:
        raise SimilarWatchError("At least one query required")
    if len(cleaned) > cfg.max_queries_per_watch:
        raise SimilarWatchError(f"At most {cfg.max_queries_per_watch} queries allowed")

    watch = get_or_create_watch_draft(session, saved_video_id=saved_video_id)
    becoming_active = watch.status not in (WATCH_ACTIVE, WATCH_PAUSED)
    if becoming_active:
        active = count_active_similar_watches(session)
        if active >= cfg.max_active_watches:
            raise SimilarWatchLimitError(
                f"Active similar-search limit reached ({cfg.max_active_watches})",
            )

    now = utc_now()
    watch.queries_json = json.dumps(cleaned, ensure_ascii=False)
    watch.status = WATCH_ACTIVE
    watch.confirmed_at = watch.confirmed_at or now
    watch.last_display_state = "never_checked"
    watch.next_scan_at = None
    watch.batch_query_offset = 0
    watch.last_error = None
    watch.updated_at = now
    session.flush()
    return watch


def pause_similar_watch(session: Session, *, saved_video_id: int) -> SavedVideoSimilarWatch:
    watch = session.get(SavedVideoSimilarWatch, saved_video_id)
    if watch is None:
        raise SimilarWatchNotFoundError("Similar search watch not configured")
    watch.status = WATCH_PAUSED
    watch.last_display_state = "paused"
    watch.next_scan_at = None
    watch.scan_lease_until = None
    watch.updated_at = utc_now()
    session.flush()
    return watch


def pause_similar_watch_for_archived_video(session: Session, *, saved_video_id: int) -> None:
    watch = session.get(SavedVideoSimilarWatch, saved_video_id)
    if watch is None or watch.status != WATCH_ACTIVE:
        return
    watch.status = WATCH_PAUSED
    watch.last_display_state = "paused"
    watch.next_scan_at = None
    watch.scan_lease_until = None
    watch.updated_at = utc_now()
    session.flush()


def resume_similar_watch(session: Session, *, saved_video_id: int) -> SavedVideoSimilarWatch:
    saved = session.get(SavedVideo, saved_video_id)
    if saved is None:
        raise SavedVideoNotFoundError("Saved video not found")
    if saved.archived_at is not None:
        raise SavedResearchArchivedError("Saved video is archived")
    watch = session.get(SavedVideoSimilarWatch, saved_video_id)
    if watch is None or not _load_queries(watch):
        raise SimilarWatchNotFoundError("Confirm queries before resuming")
    cfg = saved_video_similar_watch_settings
    if watch.status != WATCH_ACTIVE:
        if count_active_similar_watches(session) >= cfg.max_active_watches:
            raise SimilarWatchLimitError(f"Active similar-search limit reached ({cfg.max_active_watches})")
    watch.status = WATCH_ACTIVE
    interval = timedelta(hours=cfg.scan_interval_hours)
    watch.next_scan_at = utc_now() + interval
    watch.last_display_state = derive_display_state(session, watch)
    watch.updated_at = utc_now()
    session.flush()
    return watch


def _count_findings(session: Session, saved_video_id: int) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(SavedVideoSimilarFinding)
            .where(SavedVideoSimilarFinding.saved_video_id == saved_video_id),
        )
        or 0,
    )


def _last_scan_partial(watch: SavedVideoSimilarWatch, session: Session) -> bool:
    if watch.last_scan_id is None:
        return False
    scan = session.get(SavedVideoSimilarScan, watch.last_scan_id)
    return scan is not None and scan.queries_failed > 0


def derive_display_state(session: Session, watch: SavedVideoSimilarWatch) -> str:
    if watch.status == WATCH_PAUSED:
        return "paused"
    if watch.status == WATCH_DRAFT:
        return "draft"
    if watch.scan_lease_until and ensure_utc(watch.scan_lease_until) > utc_now():
        return "scanning"
    if watch.last_scan_at is None:
        return "never_checked"
    findings = _count_findings(session, watch.saved_video_id)
    if _last_scan_partial(watch, session):
        return "partial_error"
    if findings > 0:
        return "has_results"
    return "empty"


async def execute_similar_watch_scan_async(
    session: Session,
    *,
    saved_video_id: int,
    trigger: Literal["manual", "scheduled"],
    queries_to_run: list[str] | None = None,
    batch_query_cycle_complete: bool = True,
) -> SimilarWatchScanSummary:
    saved = session.get(SavedVideo, saved_video_id)
    if saved is None:
        raise SavedVideoNotFoundError("Saved video not found")
    if saved.archived_at is not None:
        raise SavedResearchArchivedError("Saved video is archived")

    watch = session.get(SavedVideoSimilarWatch, saved_video_id)
    if watch is None or watch.status != WATCH_ACTIVE:
        raise SimilarWatchError("Similar search is not active")
    all_queries = _load_queries(watch)
    if not all_queries:
        raise SimilarWatchError("No confirmed queries")
    queries = queries_to_run if queries_to_run is not None else all_queries
    if not queries:
        raise SimilarWatchError("No queries to run")

    cfg = saved_video_similar_watch_settings
    anchor = build_anchor_profile(title=saved.frozen_title, frozen_payload=parse_frozen_json(saved.frozen_payload_json))
    now = utc_now()
    if watch.scan_lease_until and ensure_utc(watch.scan_lease_until) > now:
        raise SimilarWatchScanInProgressError("Scan already in progress")

    lease_until = now + timedelta(minutes=cfg.scan_lease_minutes)
    watch.scan_lease_until = lease_until
    watch.last_display_state = "scanning"
    watch.updated_at = now
    session.flush()

    scan_run_id = _generate_scan_run_id(now=now)
    scan = SavedVideoSimilarScan(
        saved_video_id=saved_video_id,
        scan_run_id=scan_run_id,
        trigger=trigger,
        started_at=now,
        status="running",
    )
    session.add(scan)
    session.flush()

    exclude = frozenset({saved.video_id})
    queries_failed = 0
    new_count = 0
    errors: list[str] = []
    touched_video_ids: set[str] = set()

    for query in queries:
        result = await search_similar_videos_for_query(query, exclude_video_ids=exclude)
        scan.queries_attempted += 1
        if result.error:
            queries_failed += 1
            errors.append(f"{query}: {result.error}")
            continue
        for video in result.videos:
            if video.video_id in touched_video_ids:
                continue
            payload = attach_relevance_to_payload(
                video_search_to_payload(video, matched_query=query),
                anchor,
                matched_query=query,
            )
            existing = session.scalar(
                select(SavedVideoSimilarFinding).where(
                    SavedVideoSimilarFinding.saved_video_id == saved_video_id,
                    SavedVideoSimilarFinding.video_id == video.video_id,
                ),
            )
            stamp = utc_now()
            if existing is None:
                row = SavedVideoSimilarFinding(
                    saved_video_id=saved_video_id,
                    video_id=video.video_id,
                    matched_query=query,
                    first_scan_id=scan.id,
                    last_scan_id=scan.id,
                    first_found_at=stamp,
                    last_found_at=stamp,
                    payload_json=json.dumps(payload, ensure_ascii=False),
                )
                session.add(row)
                touched_video_ids.add(video.video_id)
                new_count += 1
            else:
                existing.last_scan_id = scan.id
                existing.last_found_at = stamp
                existing.payload_json = json.dumps(payload, ensure_ascii=False)
                if not existing.matched_query:
                    existing.matched_query = query
                touched_video_ids.add(video.video_id)

    finished = utc_now()
    scan.finished_at = finished
    scan.queries_failed = queries_failed
    scan.new_findings_count = new_count
    scan.status = "partial_error" if queries_failed and scan.queries_attempted > queries_failed else (
        "failed" if queries_failed and queries_failed == scan.queries_attempted else "completed"
    )
    scan.payload_json = json.dumps({"errors": errors}, ensure_ascii=False)

    watch.last_scan_at = finished
    watch.last_scan_id = scan.id
    watch.scan_lease_until = None
    watch.last_error = "; ".join(errors[:3]) if errors else None
    if trigger == "manual":
        watch.batch_query_offset = 0
        watch.next_scan_at = finished + timedelta(hours=cfg.scan_interval_hours)
    elif batch_query_cycle_complete:
        watch.batch_query_offset = 0
        watch.next_scan_at = finished + timedelta(hours=cfg.scan_interval_hours)
    else:
        watch.next_scan_at = finished
    session.flush()
    watch.last_display_state = derive_display_state(session, watch)
    watch.updated_at = finished
    session.flush()

    return SimilarWatchScanSummary(
        scan_id=scan.id,
        scan_run_id=scan_run_id,
        queries_attempted=scan.queries_attempted,
        queries_failed=queries_failed,
        new_findings_count=new_count,
        display_state=watch.last_display_state,
    )


def execute_similar_watch_scan(
    session: Session,
    *,
    saved_video_id: int,
    trigger: Literal["manual", "scheduled"],
    queries_to_run: list[str] | None = None,
    batch_query_cycle_complete: bool = True,
) -> SimilarWatchScanSummary:
    return asyncio.run(
        execute_similar_watch_scan_async(
            session,
            saved_video_id=saved_video_id,
            trigger=trigger,
            queries_to_run=queries_to_run,
            batch_query_cycle_complete=batch_query_cycle_complete,
        ),
    )


def run_similar_watch_batch_for_discovery_cycle(session: Session) -> int:
    """Process due SavedVideo + SavedFamily watches; returns number of watches scanned."""
    from app.services.saved_library_watch_batch import run_library_watch_batch_for_discovery_cycle

    return run_library_watch_batch_for_discovery_cycle(session)


def list_findings_grouped(
    session: Session,
    *,
    saved_video_id: int,
    primary_limit: int = 50,
    other_limit: int = 200,
) -> tuple[list[SavedVideoSimilarFinding], list[SavedVideoSimilarFinding], int, int, int]:
    saved = session.get(SavedVideo, saved_video_id)
    if saved is None:
        return [], [], 0, 0, 0
    anchor = build_anchor_profile(
        title=saved.frozen_title,
        frozen_payload=parse_frozen_json(saved.frozen_payload_json),
    )
    total = int(
        session.scalar(
            select(func.count())
            .select_from(SavedVideoSimilarFinding)
            .where(SavedVideoSimilarFinding.saved_video_id == saved_video_id),
        )
        or 0,
    )
    rows = session.scalars(
        select(SavedVideoSimilarFinding).where(SavedVideoSimilarFinding.saved_video_id == saved_video_id),
    ).all()

    def sort_key(row: SavedVideoSimilarFinding) -> tuple[int, float]:
        try:
            payload = json.loads(row.payload_json or "{}")
        except json.JSONDecodeError:
            payload = {}
        rel = relevance_from_payload(payload, anchor, matched_query=row.matched_query or "")
        ts = ensure_utc(row.last_found_at).timestamp()
        return (-rel.score, -ts)

    primary: list[SavedVideoSimilarFinding] = []
    other: list[SavedVideoSimilarFinding] = []
    for row in rows:
        try:
            payload = json.loads(row.payload_json or "{}")
        except json.JSONDecodeError:
            payload = {}
        rel = relevance_from_payload(payload, anchor, matched_query=row.matched_query or "")
        if rel.tier == "primary":
            primary.append(row)
        else:
            other.append(row)
    primary.sort(key=sort_key)
    other.sort(key=sort_key)
    primary_total = len(primary)
    other_total = len(other)
    return (
        primary[:primary_limit],
        other[:other_limit],
        total,
        primary_total,
        other_total,
    )


def list_findings(
    session: Session,
    *,
    saved_video_id: int,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[SavedVideoSimilarFinding], int]:
    primary, other, total, _, _ = list_findings_grouped(
        session,
        saved_video_id=saved_video_id,
        primary_limit=limit + offset,
        other_limit=0,
    )
    combined = primary + other
    return combined[offset : offset + limit], total


def save_finding_to_saved_research(session: Session, *, saved_video_id: int, finding_id: int):
    finding = session.get(SavedVideoSimilarFinding, finding_id)
    if finding is None or finding.saved_video_id != saved_video_id:
        raise SimilarWatchNotFoundError("Finding not found")
    try:
        payload = json.loads(finding.payload_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    details = YouTubeVideoDetails(
        video_id=finding.video_id,
        channel_id=str(payload.get("channel_id") or ""),
        title=str(payload.get("title") or finding.video_id),
        published_at=utc_now(),
        views_count=int(payload.get("views_count") or 0),
        likes_count=0,
        comments_count=0,
        duration_seconds=0,
    )
    return save_video_from_manual_search(session, details)


def set_similar_finding_feedback(
    session: Session,
    *,
    saved_video_id: int,
    finding_id: int,
    verdict: Literal["fit", "not_fit"],
) -> SavedVideoSimilarFindingFeedback:
    finding = session.get(SavedVideoSimilarFinding, finding_id)
    if finding is None or finding.saved_video_id != saved_video_id:
        raise SimilarWatchNotFoundError("Finding not found")
    row = session.scalar(
        select(SavedVideoSimilarFindingFeedback).where(
            SavedVideoSimilarFindingFeedback.saved_video_id == saved_video_id,
            SavedVideoSimilarFindingFeedback.finding_id == finding_id,
        ),
    )
    now = utc_now()
    if row is None:
        row = SavedVideoSimilarFindingFeedback(
            saved_video_id=saved_video_id,
            finding_id=finding_id,
            verdict=verdict,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        row.verdict = verdict
        row.updated_at = now
    session.flush()
    return row


def active_saved_library_video_ids(session: Session, video_ids: list[str]) -> set[str]:
    """YouTube video_ids that already have a non-archived SavedVideo row."""
    ids = [v.strip() for v in video_ids if v and v.strip()]
    if not ids:
        return set()
    rows = session.scalars(
        select(SavedVideo.video_id).where(
            SavedVideo.video_id.in_(ids),
            SavedVideo.archived_at.is_(None),
        ),
    ).all()
    return {str(v) for v in rows}


def feedback_verdicts_for_watch(session: Session, *, saved_video_id: int) -> dict[int, str]:
    rows = session.scalars(
        select(SavedVideoSimilarFindingFeedback).where(
            SavedVideoSimilarFindingFeedback.saved_video_id == saved_video_id,
        ),
    ).all()
    return {int(r.finding_id): str(r.verdict) for r in rows}


def summarize_scan_findings(
    session: Session,
    *,
    saved_video_id: int,
    scan_id: int,
) -> dict[str, Any]:
    """Stats for one scan only (findings touched in that scan)."""
    saved = session.get(SavedVideo, saved_video_id)
    if saved is None:
        raise SavedVideoNotFoundError("Saved video not found")
    anchor = build_anchor_profile(
        title=saved.frozen_title,
        frozen_payload=parse_frozen_json(saved.frozen_payload_json),
    )
    rows = session.scalars(
        select(SavedVideoSimilarFinding).where(
            SavedVideoSimilarFinding.saved_video_id == saved_video_id,
            SavedVideoSimilarFinding.last_scan_id == scan_id,
        ),
    ).all()
    primary: list[dict[str, Any]] = []
    other: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row.payload_json or "{}")
        except json.JSONDecodeError:
            payload = {}
        rel = relevance_from_payload(payload, anchor, matched_query=row.matched_query or "")
        item = {
            "finding_id": row.id,
            "video_id": row.video_id,
            "title": payload.get("title"),
            "matched_query": row.matched_query,
            "why_found": rel.why_found,
            "other_reason": rel.other_reason,
            "tier": rel.tier,
            "score": rel.score,
        }
        if rel.tier == "primary":
            primary.append(item)
        else:
            other.append(item)
    primary.sort(key=lambda x: (-int(x["score"]),))
    other.sort(key=lambda x: (-int(x["score"]),))
    return {
        "scan_id": scan_id,
        "unique_videos": len(rows),
        "primary_count": len(primary),
        "other_count": len(other),
        "primary": primary,
        "other": other,
    }


def build_watch_api_dict(session: Session, watch: SavedVideoSimilarWatch, *, saved: SavedVideo) -> dict[str, Any]:
    findings_count = _count_findings(session, watch.saved_video_id)
    display = derive_display_state(session, watch)
    watch.last_display_state = display
    return {
        "saved_video_id": watch.saved_video_id,
        "status": watch.status,
        "display_state": display,
        "suggested_queries": _load_suggested(watch),
        "confirmed_queries": _load_queries(watch) if watch.status != WATCH_DRAFT else [],
        "confirmed_at": watch.confirmed_at,
        "next_scan_at": watch.next_scan_at,
        "last_scan_at": watch.last_scan_at,
        "last_error": watch.last_error,
        "findings_count": findings_count,
        "load_estimate": similar_watch_load_estimate(),
    }
