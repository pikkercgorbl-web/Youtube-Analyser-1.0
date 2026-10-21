"""SavedFamily topic video search watch (shares InnerTube budget with SavedVideo similar watch)."""

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
    SavedFamily,
    SavedFamilyTopicFinding,
    SavedFamilyTopicScan,
    SavedFamilyTopicWatch,
    TargetKeyword,
)
from app.services.manual_search_save import save_video_from_manual_search
from app.services.metrics import ensure_utc, utc_now
from app.services.saved_family_topic_query_suggest import (
    FamilyTopicQueryPlan,
    TopicQuerySuggestionItem,
    build_family_topic_query_plan,
)
from app.services.saved_family_topic_query_suggest import labels_align as topic_labels_align
from app.services.saved_research import SavedResearchArchivedError, SavedResearchError
from app.services.saved_video_similar_query_suggest import parse_frozen_json
from app.services.saved_video_similar_search import search_similar_videos_for_query, video_search_to_payload
from app.services.saved_video_similar_watch import (
    WATCH_ACTIVE,
    WATCH_DRAFT,
    WATCH_PAUSED,
    SimilarWatchError,
    SimilarWatchLimitError,
    SimilarWatchNotFoundError,
    SimilarWatchScanInProgressError,
    active_saved_library_video_ids,
)
from app.services.saved_video_similar_watch_config import (
    saved_video_similar_watch_settings,
    similar_watch_load_estimate,
)

WATCH_NOT_CONFIGURED = "not_configured"


class SavedFamilyNotFoundError(SavedResearchError):
    pass


@dataclass(frozen=True, slots=True)
class FamilyTopicWatchScanSummary:
    scan_id: int
    scan_run_id: str
    queries_attempted: int
    queries_failed: int
    new_findings_count: int
    display_state: str


def _generate_scan_run_id(*, now: datetime | None = None) -> str:
    reference = ensure_utc(now or utc_now())
    return f"saved_family_topic_{reference.strftime('%Y%m%dT%H%M%SZ')}_{secrets.token_hex(4)}"


def _load_queries(watch: SavedFamilyTopicWatch) -> list[str]:
    try:
        raw = json.loads(watch.queries_json or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    return [str(q).strip() for q in raw if str(q).strip()]


def _load_suggested(watch: SavedFamilyTopicWatch) -> list[str]:
    try:
        raw = json.loads(watch.suggested_queries_json or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    return [str(q).strip() for q in raw if str(q).strip()]


def _keyword_texts_by_id_for_family(session: Session, frozen: dict[str, Any]) -> dict[int, str]:
    raw_ids = frozen.get("keyword_ids")
    if not isinstance(raw_ids, list):
        return {}
    ids: list[int] = []
    for item in raw_ids:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    if not ids:
        return {}
    rows = session.scalars(select(TargetKeyword).where(TargetKeyword.id.in_(ids))).all()
    by_id = {row.id: row.keyword.strip() for row in rows if row.keyword and row.keyword.strip()}
    return {i: by_id[i] for i in ids if i in by_id}


def family_topic_query_plan_for_saved(session: Session, saved: SavedFamily) -> FamilyTopicQueryPlan:
    frozen = parse_frozen_json(saved.frozen_payload_json)
    return build_family_topic_query_plan(
        frozen_label=saved.frozen_label,
        frozen_payload=frozen,
        keyword_texts_by_id=_keyword_texts_by_id_for_family(session, frozen),
    )


def _queries_span_multiple_directions(queries: list[str], plan: FamilyTopicQueryPlan) -> bool:
    if len(plan.directions) < 2 or len(queries) < 2:
        return False
    matched: set[str] = set()
    for query in queries:
        for direction in plan.directions:
            for item in direction.suggestions:
                if query.casefold() == item.query.casefold() or topic_labels_align(query, item.query):
                    matched.add(direction.direction_id)
                    break
    return len(matched) > 1


def _plan_item_to_dict(item: TopicQuerySuggestionItem) -> dict[str, Any]:
    return {
        "query": item.query,
        "source_type": item.source_type,
        "source_explanation": item.source_explanation,
        "supporting_video_count": item.supporting_video_count,
    }


def _family_video_ids(frozen: dict[str, Any]) -> frozenset[str]:
    raw = frozen.get("video_ids")
    if not isinstance(raw, list):
        return frozenset()
    return frozenset(str(v).strip() for v in raw if v and str(v).strip())


def _count_findings(session: Session, saved_family_id: int) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(SavedFamilyTopicFinding)
            .where(SavedFamilyTopicFinding.saved_family_id == saved_family_id),
        )
        or 0,
    )


def _last_scan_partial(watch: SavedFamilyTopicWatch, session: Session) -> bool:
    if watch.last_scan_id is None:
        return False
    scan = session.get(SavedFamilyTopicScan, watch.last_scan_id)
    if scan is None:
        return False
    return scan.status == "partial_error"


def derive_display_state(session: Session, watch: SavedFamilyTopicWatch) -> str:
    if watch.status == WATCH_DRAFT:
        return "draft"
    if watch.status == WATCH_PAUSED:
        return "paused"
    now = utc_now()
    if watch.scan_lease_until and ensure_utc(watch.scan_lease_until) > now:
        return "scanning"
    if watch.last_scan_at is None:
        return "never_checked"
    if _last_scan_partial(watch, session):
        return "partial_error"
    if _count_findings(session, watch.saved_family_id) > 0:
        return "has_results"
    return "empty"


def get_or_create_family_topic_watch_draft(session: Session, *, saved_family_id: int) -> SavedFamilyTopicWatch:
    row = session.get(SavedFamily, saved_family_id)
    if row is None:
        raise SavedFamilyNotFoundError(f"Saved family id={saved_family_id} not found")
    if row.archived_at is not None:
        raise SavedResearchArchivedError("Saved family is archived")

    plan = family_topic_query_plan_for_saved(session, row)
    suggestion_strings = [item.query for item in plan.suggestions]

    watch = session.get(SavedFamilyTopicWatch, saved_family_id)
    if watch is None:
        now = utc_now()
        watch = SavedFamilyTopicWatch(
            saved_family_id=saved_family_id,
            status=WATCH_DRAFT,
            suggested_queries_json=json.dumps(suggestion_strings, ensure_ascii=False),
            last_display_state=WATCH_DRAFT,
            created_at=now,
            updated_at=now,
        )
        session.add(watch)
        session.flush()
        return watch

    if watch.status == WATCH_DRAFT:
        watch.suggested_queries_json = json.dumps(suggestion_strings, ensure_ascii=False)
        watch.last_display_state = WATCH_DRAFT
        watch.updated_at = utc_now()
        session.flush()
    return watch


def confirm_family_topic_watch_queries(
    session: Session,
    *,
    saved_family_id: int,
    queries: list[str],
) -> SavedFamilyTopicWatch:
    cfg = saved_video_similar_watch_settings
    cleaned = list(dict.fromkeys(q.strip() for q in queries if q and q.strip()))
    if not cleaned:
        raise SimilarWatchError("At least one query required")
    if len(cleaned) > cfg.max_queries_per_watch:
        raise SimilarWatchError(f"At most {cfg.max_queries_per_watch} queries allowed")

    saved = session.get(SavedFamily, saved_family_id)
    if saved is None:
        raise SavedFamilyNotFoundError("Saved family not found")
    if saved.archived_at is not None:
        raise SavedResearchArchivedError("Saved family is archived")
    plan = family_topic_query_plan_for_saved(session, saved)
    if plan.mode == "heterogeneous" and not cleaned and not plan.suggestions:
        raise SimilarWatchError(plan.message or "Задайте запросы вручную")
    if _queries_span_multiple_directions(cleaned, plan):
        raise SimilarWatchError(
            "Запросы относятся к разным направлениям. Выберите одно направление или отредактируйте набор.",
        )

    watch = session.get(SavedFamilyTopicWatch, saved_family_id)
    if watch is None:
        watch = get_or_create_family_topic_watch_draft(session, saved_family_id=saved_family_id)
    becoming_active = watch.status not in (WATCH_ACTIVE, WATCH_PAUSED)
    if becoming_active:
        from app.services.saved_library_watch_batch import count_active_library_watches

        active = count_active_library_watches(session)
        if active >= cfg.max_active_watches:
            raise SimilarWatchLimitError(
                f"Active library search watch limit reached ({cfg.max_active_watches})",
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


def pause_family_topic_watch(session: Session, *, saved_family_id: int) -> SavedFamilyTopicWatch:
    watch = session.get(SavedFamilyTopicWatch, saved_family_id)
    if watch is None:
        raise SimilarWatchNotFoundError("Topic search watch not configured")
    watch.status = WATCH_PAUSED
    watch.last_display_state = "paused"
    watch.next_scan_at = None
    watch.scan_lease_until = None
    watch.updated_at = utc_now()
    session.flush()
    return watch


def pause_family_topic_watch_for_archived_family(session: Session, *, saved_family_id: int) -> None:
    watch = session.get(SavedFamilyTopicWatch, saved_family_id)
    if watch is None or watch.status != WATCH_ACTIVE:
        return
    watch.status = WATCH_PAUSED
    watch.last_display_state = "paused"
    watch.next_scan_at = None
    watch.scan_lease_until = None
    watch.updated_at = utc_now()
    session.flush()


def resume_family_topic_watch(session: Session, *, saved_family_id: int) -> SavedFamilyTopicWatch:
    watch = session.get(SavedFamilyTopicWatch, saved_family_id)
    if watch is None:
        raise SimilarWatchNotFoundError("Topic search watch not configured")
    saved = session.get(SavedFamily, saved_family_id)
    if saved is None:
        raise SavedFamilyNotFoundError("Saved family not found")
    if saved.archived_at is not None:
        raise SavedResearchArchivedError("Saved family is archived")

    cfg = saved_video_similar_watch_settings
    if watch.status == WATCH_PAUSED:
        from app.services.saved_library_watch_batch import count_active_library_watches

        if count_active_library_watches(session) >= cfg.max_active_watches:
            raise SimilarWatchLimitError(
                f"Active library search watch limit reached ({cfg.max_active_watches})",
            )

    now = utc_now()
    watch.status = WATCH_ACTIVE
    watch.last_display_state = derive_display_state(session, watch)
    watch.next_scan_at = watch.next_scan_at or (now + timedelta(hours=cfg.scan_interval_hours))
    watch.updated_at = now
    session.flush()
    return watch


async def execute_family_topic_watch_scan_async(
    session: Session,
    *,
    saved_family_id: int,
    trigger: Literal["manual", "scheduled"],
    queries_to_run: list[str] | None = None,
    batch_query_cycle_complete: bool = True,
) -> FamilyTopicWatchScanSummary:
    saved = session.get(SavedFamily, saved_family_id)
    if saved is None:
        raise SavedFamilyNotFoundError("Saved family not found")
    if saved.archived_at is not None:
        raise SavedResearchArchivedError("Saved family is archived")

    watch = session.get(SavedFamilyTopicWatch, saved_family_id)
    if watch is None or watch.status != WATCH_ACTIVE:
        raise SimilarWatchError("Topic search is not active")
    all_queries = _load_queries(watch)
    if not all_queries:
        raise SimilarWatchError("No confirmed queries")
    queries = queries_to_run if queries_to_run is not None else all_queries
    if not queries:
        raise SimilarWatchError("No queries to run")

    cfg = saved_video_similar_watch_settings
    frozen = parse_frozen_json(saved.frozen_payload_json)
    exclude = _family_video_ids(frozen)
    now = utc_now()
    if watch.scan_lease_until and ensure_utc(watch.scan_lease_until) > now:
        raise SimilarWatchScanInProgressError("Scan already in progress")

    lease_until = now + timedelta(minutes=cfg.scan_lease_minutes)
    watch.scan_lease_until = lease_until
    watch.last_display_state = "scanning"
    watch.updated_at = now
    session.flush()

    scan_run_id = _generate_scan_run_id(now=now)
    scan = SavedFamilyTopicScan(
        saved_family_id=saved_family_id,
        scan_run_id=scan_run_id,
        trigger=trigger,
        started_at=now,
        status="running",
    )
    session.add(scan)
    session.flush()

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
            payload = video_search_to_payload(video, matched_query=query)
            existing = session.scalar(
                select(SavedFamilyTopicFinding).where(
                    SavedFamilyTopicFinding.saved_family_id == saved_family_id,
                    SavedFamilyTopicFinding.video_id == video.video_id,
                ),
            )
            stamp = utc_now()
            if existing is None:
                row = SavedFamilyTopicFinding(
                    saved_family_id=saved_family_id,
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
    scan.status = (
        "partial_error"
        if queries_failed and scan.queries_attempted > queries_failed
        else ("failed" if queries_failed and queries_failed == scan.queries_attempted else "completed")
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

    return FamilyTopicWatchScanSummary(
        scan_id=scan.id,
        scan_run_id=scan_run_id,
        queries_attempted=scan.queries_attempted,
        queries_failed=queries_failed,
        new_findings_count=new_count,
        display_state=watch.last_display_state,
    )


def execute_family_topic_watch_scan(
    session: Session,
    *,
    saved_family_id: int,
    trigger: Literal["manual", "scheduled"],
    queries_to_run: list[str] | None = None,
    batch_query_cycle_complete: bool = True,
) -> FamilyTopicWatchScanSummary:
    return asyncio.run(
        execute_family_topic_watch_scan_async(
            session,
            saved_family_id=saved_family_id,
            trigger=trigger,
            queries_to_run=queries_to_run,
            batch_query_cycle_complete=batch_query_cycle_complete,
        ),
    )


def count_findings_by_query(session: Session, *, saved_family_id: int) -> dict[str, int]:
    rows = session.scalars(
        select(SavedFamilyTopicFinding.matched_query).where(
            SavedFamilyTopicFinding.saved_family_id == saved_family_id,
        ),
    ).all()
    counts: dict[str, int] = {}
    for matched in rows:
        key = (matched or "").strip() or "—"
        counts[key] = counts.get(key, 0) + 1
    return counts


def list_family_topic_findings(
    session: Session,
    *,
    saved_family_id: int,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[SavedFamilyTopicFinding], int]:
    total = int(
        session.scalar(
            select(func.count())
            .select_from(SavedFamilyTopicFinding)
            .where(SavedFamilyTopicFinding.saved_family_id == saved_family_id),
        )
        or 0,
    )
    rows = session.scalars(
        select(SavedFamilyTopicFinding)
        .where(SavedFamilyTopicFinding.saved_family_id == saved_family_id)
        .order_by(SavedFamilyTopicFinding.last_found_at.desc())
        .offset(offset)
        .limit(limit),
    ).all()
    return list(rows), total


def save_family_topic_finding_to_saved_research(
    session: Session,
    *,
    saved_family_id: int,
    finding_id: int,
):
    finding = session.get(SavedFamilyTopicFinding, finding_id)
    if finding is None or finding.saved_family_id != saved_family_id:
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


def build_family_topic_watch_api_dict(
    session: Session,
    watch: SavedFamilyTopicWatch,
    *,
    saved: SavedFamily,
) -> dict[str, Any]:
    findings_count = _count_findings(session, watch.saved_family_id)
    display = derive_display_state(session, watch)
    watch.last_display_state = display
    plan = family_topic_query_plan_for_saved(session, saved)
    suggested_items = [_plan_item_to_dict(item) for item in plan.suggestions]
    suggested_queries = [item["query"] for item in suggested_items]
    if watch.status in (WATCH_ACTIVE, WATCH_PAUSED):
        # Do not imply stale DB suggestions override live plan; confirmed queries stay as stored.
        pass
    elif not suggested_queries:
        suggested_queries = _load_suggested(watch)
    directions = [
        {
            "direction_id": d.direction_id,
            "label": d.label,
            "explanation": d.explanation,
            "suggestions": [_plan_item_to_dict(s) for s in d.suggestions],
        }
        for d in plan.directions
    ]
    return {
        "saved_family_id": watch.saved_family_id,
        "status": watch.status,
        "display_state": display,
        "suggested_queries": suggested_queries,
        "suggested_query_items": suggested_items,
        "suggestion_mode": plan.mode,
        "suggestion_message": plan.message,
        "mixed_keyword_provenance": plan.mixed_keyword_provenance,
        "search_directions": directions,
        "confirmed_queries": _load_queries(watch) if watch.status != WATCH_DRAFT else [],
        "confirmed_at": watch.confirmed_at,
        "next_scan_at": watch.next_scan_at,
        "last_scan_at": watch.last_scan_at,
        "last_error": watch.last_error,
        "findings_count": findings_count,
        "load_estimate": similar_watch_load_estimate(),
        "topic_label": saved.frozen_label or saved.family_key,
        "anchor_label": plan.anchor_label,
    }
