"""Read-only research portfolio for validation report (Product Fix 1A)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.models.orm import (
    SavedFamily,
    SavedFamilyObservation,
    SavedResearchEvent,
    SavedVideo,
    SavedVideoObservation,
)
from app.services.metrics import ensure_utc
from app.services.saved_research import export_frozen_family, export_frozen_video, latest_family_observations, latest_video_observations
from app.services.saved_research_feedback import latest_feedback_by_entities
from app.services.saved_research_daily_intelligence import DAILY_INTELLIGENCE_SAVE_ANCHOR_KIND
from app.services.saved_research_validation import compute_family_validation, compute_video_validation

NEW_ANALYTICAL_OBSERVATION_IN_PERIOD_DEFINITION = (
    "Distinct SavedVideo / SavedFamily entities (every row in saved_videos / saved_families, "
    "including archived bookmarks — archive does not delete observation history; not limited to "
    "saved_in_period) with at least one row in saved_video_observations or "
    "saved_family_observations where observed_at is within the report period, "
    "observation_kind is not "
    f"{DAILY_INTELLIGENCE_SAVE_ANCHOR_KIND!r} (Daily Intelligence save anchor), "
    "and observed_at is strictly after the entity's earliest such analytical row. "
    "User SavedResearchEvent rows (status, notes) are excluded. "
    "Each entity counts at most once."
)


def _parse_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text or "{}")
    except json.JSONDecodeError:
        return {}


def _apply_saved_period_filter_video(stmt, period_start: datetime | None, period_end: datetime | None):
    if period_start is not None:
        stmt = stmt.where(SavedVideo.saved_at >= ensure_utc(period_start))
    if period_end is not None:
        stmt = stmt.where(SavedVideo.saved_at <= ensure_utc(period_end))
    return stmt


def _apply_saved_period_filter_family(stmt, period_start: datetime | None, period_end: datetime | None):
    if period_start is not None:
        stmt = stmt.where(SavedFamily.saved_at >= ensure_utc(period_start))
    if period_end is not None:
        stmt = stmt.where(SavedFamily.saved_at <= ensure_utc(period_end))
    return stmt


def _current_status_key(archived_at: datetime | None, status: str) -> str:
    return "ARCHIVED" if archived_at is not None else status


def _observation_counts_videos(session: Session, ids: list[int]) -> dict[int, int]:
    if not ids:
        return {}
    rows = session.execute(
        select(SavedVideoObservation.saved_video_id, func.count())
        .where(SavedVideoObservation.saved_video_id.in_(ids))
        .group_by(SavedVideoObservation.saved_video_id),
    ).all()
    return {int(r[0]): int(r[1]) for r in rows}


def _observation_kind_expr(session: Session, payload_column):
    """SQLite: json_extract; PostgreSQL: payload_json::jsonb ->> 'observation_kind'."""
    if session.get_bind().dialect.name == "postgresql":
        return cast(payload_column, JSONB).op("->>")("observation_kind")
    return func.json_extract(payload_column, "$.observation_kind")


def _is_analytical_observation_kind(kind_expr):
    return (kind_expr.is_(None)) | (kind_expr != DAILY_INTELLIGENCE_SAVE_ANCHOR_KIND)


def _count_entities_with_new_analytical_observation_in_period(
    session: Session,
    observation_model: type[SavedVideoObservation] | type[SavedFamilyObservation],
    entity_fk_column,
    *,
    period_start: datetime | None,
    period_end: datetime | None,
) -> int:
    if period_start is None and period_end is None:
        return 0

    kind = _observation_kind_expr(session, observation_model.payload_json)
    analytical = _is_analytical_observation_kind(kind)

    first_analytical = (
        select(
            entity_fk_column.label("entity_id"),
            func.min(observation_model.observed_at).label("first_at"),
        )
        .where(analytical)
        .group_by(entity_fk_column)
        .subquery()
    )

    stmt = select(func.count(func.distinct(entity_fk_column))).select_from(observation_model)
    stmt = stmt.join(
        first_analytical,
        first_analytical.c.entity_id == entity_fk_column,
    )
    stmt = stmt.where(analytical)
    stmt = stmt.where(observation_model.observed_at > first_analytical.c.first_at)
    if period_start is not None:
        stmt = stmt.where(observation_model.observed_at >= ensure_utc(period_start))
    if period_end is not None:
        stmt = stmt.where(observation_model.observed_at <= ensure_utc(period_end))

    return int(session.scalar(stmt) or 0)


def _cohort_with_new_analytical_observation_in_period(
    session: Session,
    *,
    period_start: datetime | None,
    period_end: datetime | None,
) -> int | None:
    if period_start is None and period_end is None:
        return None
    videos = _count_entities_with_new_analytical_observation_in_period(
        session,
        SavedVideoObservation,
        SavedVideoObservation.saved_video_id,
        period_start=period_start,
        period_end=period_end,
    )
    families = _count_entities_with_new_analytical_observation_in_period(
        session,
        SavedFamilyObservation,
        SavedFamilyObservation.saved_family_id,
        period_start=period_start,
        period_end=period_end,
    )
    return videos + families


def _observation_counts_families(session: Session, ids: list[int]) -> dict[int, int]:
    if not ids:
        return {}
    rows = session.execute(
        select(SavedFamilyObservation.saved_family_id, func.count())
        .where(SavedFamilyObservation.saved_family_id.in_(ids))
        .group_by(SavedFamilyObservation.saved_family_id),
    ).all()
    return {int(r[0]): int(r[1]) for r in rows}


def _load_research_events_in_period(
    session: Session,
    *,
    period_start: datetime | None,
    period_end: datetime | None,
) -> list[SavedResearchEvent]:
    stmt = select(SavedResearchEvent).where(SavedResearchEvent.entity_kind.in_(("video", "family")))
    if period_start is not None:
        stmt = stmt.where(SavedResearchEvent.occurred_at >= ensure_utc(period_start))
    if period_end is not None:
        stmt = stmt.where(SavedResearchEvent.occurred_at <= ensure_utc(period_end))
    return list(session.scalars(stmt).all())


def _aggregate_research_decisions(events: list[SavedResearchEvent]) -> dict[str, Any]:
    transition_counts = {
        "to_WANT_TO_TEST": 0,
        "to_TESTING": 0,
        "to_DROPPED": 0,
        "to_WATCHING": 0,
    }
    events_by_type: dict[str, int] = {}
    status_changed_total = 0
    for event in events:
        events_by_type[event.event_type] = events_by_type.get(event.event_type, 0) + 1
        if event.event_type != "status_changed":
            continue
        status_changed_total += 1
        payload = _parse_json(event.payload_json)
        new_status = payload.get("new_status")
        key = f"to_{new_status}"
        if key in transition_counts:
            transition_counts[key] += 1
    return {
        "status_transition_events": transition_counts,
        "status_changed_events": status_changed_total,
        "events_by_type": events_by_type,
        "total_events": len(events),
    }


def build_research_portfolio_report(
    session: Session,
    *,
    period_start: datetime | None,
    period_end: datetime | None,
    legacy_topics_saved_in_period: int,
) -> dict[str, Any]:
    """
    Aggregates SavedVideo + SavedFamily for portfolio UI.

    Temporal contracts (explicit in response):
    - saved_in_period: saved_at within [start, end] (all rows if bounds unset).
    - decisions_in_period: SavedResearchEvent.occurred_at within bounds.
    - current_status: cohort saved_in_period as of now (archived → ARCHIVED).
    - observations: latest row + counts from append-only observation tables.
    """
    video_stmt = select(SavedVideo)
    video_stmt = _apply_saved_period_filter_video(video_stmt, period_start, period_end)
    cohort_videos = list(session.scalars(video_stmt).all())

    family_stmt = select(SavedFamily)
    family_stmt = _apply_saved_period_filter_family(family_stmt, period_start, period_end)
    cohort_families = list(session.scalars(family_stmt).all())

    video_ids = [v.id for v in cohort_videos]
    family_ids = [f.id for f in cohort_families]

    live_videos = latest_video_observations(session, video_ids)
    live_families = latest_family_observations(session, family_ids)
    obs_counts_v = _observation_counts_videos(session, video_ids)
    obs_counts_f = _observation_counts_families(session, family_ids)
    fb_videos = latest_feedback_by_entities(session, entity_kind="video", entity_ids=video_ids)
    fb_families = latest_feedback_by_entities(session, entity_kind="family", entity_ids=family_ids)

    current_status: dict[str, int] = {}
    for row in cohort_videos + cohort_families:
        key = _current_status_key(row.archived_at, row.status)
        current_status[key] = current_status.get(key, 0) + 1

    verdict_distribution: dict[str, int] = {}
    cohort_with_feedback = 0
    for fb in list(fb_videos.values()) + list(fb_families.values()):
        cohort_with_feedback += 1
        verdict_distribution[fb.verdict] = verdict_distribution.get(fb.verdict, 0) + 1

    evidence_state_distribution: dict[str, int] = {"validated": 0, "pending": 0, "insufficient": 0}
    cohort_with_any_observation = 0
    cohort_with_multiple_observations = 0

    for row in cohort_videos:
        obs_n = obs_counts_v.get(row.id, 0)
        if obs_n >= 1:
            cohort_with_any_observation += 1
        if obs_n > 1:
            cohort_with_multiple_observations += 1
        frozen = export_frozen_video(row)
        validation = compute_video_validation(
            frozen=frozen,
            live=live_videos.get(row.id),
            saved_at=row.saved_at,
            observation_count=obs_n,
        )
        state = validation["evidence_state"]
        evidence_state_distribution[state] = evidence_state_distribution.get(state, 0) + 1

    for row in cohort_families:
        obs_n = obs_counts_f.get(row.id, 0)
        if obs_n >= 1:
            cohort_with_any_observation += 1
        if obs_n > 1:
            cohort_with_multiple_observations += 1
        frozen = export_frozen_family(row)
        validation = compute_family_validation(
            frozen=frozen,
            live=live_families.get(row.id),
            observation_count=obs_n,
        )
        state = validation["evidence_state"]
        evidence_state_distribution[state] = evidence_state_distribution.get(state, 0) + 1

    new_analytical_obs_in_period = _cohort_with_new_analytical_observation_in_period(
        session,
        period_start=period_start,
        period_end=period_end,
    )

    research_events = _load_research_events_in_period(
        session,
        period_start=period_start,
        period_end=period_end,
    )
    decisions = _aggregate_research_decisions(research_events)

    cohort_total = len(cohort_videos) + len(cohort_families)
    combined_saved_total = cohort_total + legacy_topics_saved_in_period

    still_watching = current_status.get("WATCHING", 0)
    in_testing = current_status.get("TESTING", 0)
    dropped = current_status.get("DROPPED", 0)
    want_to_test = current_status.get("WANT_TO_TEST", 0)

    saved_items: list[dict[str, Any]] = []
    for row in cohort_videos:
        latest_obs = row.latest_observed_at
        saved_items.append(
            {
                "kind": "video",
                "id": row.id,
                "title": row.frozen_title or row.video_id,
                "saved_at": ensure_utc(row.saved_at).isoformat(),
                "current_status": _current_status_key(row.archived_at, row.status),
                "has_latest_feedback": row.id in fb_videos,
                "observation_count": obs_counts_v.get(row.id, 0),
                "video_id": row.video_id,
                "latest_observed_at": ensure_utc(latest_obs).isoformat() if latest_obs else None,
            },
        )
    for row in cohort_families:
        latest_obs = row.latest_observed_at
        saved_items.append(
            {
                "kind": "family",
                "id": row.id,
                "title": row.frozen_label or row.family_key,
                "saved_at": ensure_utc(row.saved_at).isoformat(),
                "current_status": _current_status_key(row.archived_at, row.status),
                "has_latest_feedback": row.id in fb_families,
                "observation_count": obs_counts_f.get(row.id, 0),
                "video_id": None,
                "latest_observed_at": ensure_utc(latest_obs).isoformat() if latest_obs else None,
            },
        )
    saved_items.sort(key=lambda item: item["saved_at"], reverse=True)

    cohort_without_feedback = cohort_total - cohort_with_feedback
    has_saved_cohort = cohort_total > 0 or legacy_topics_saved_in_period > 0
    has_decisions_in_period = (
        decisions["status_changed_events"] > 0
        or decisions["events_by_type"].get("archived", 0) > 0
        or cohort_with_feedback > 0
    )

    return {
        "temporal_contracts": {
            "saved_in_period": (
                "SavedVideo.saved_at / SavedFamily.saved_at within period bounds; "
                "all saves if bounds unset."
            ),
            "decisions_in_period": (
                "SavedResearchEvent.occurred_at within period bounds for video and family entities."
            ),
            "current_status": "Status (or ARCHIVED) now for objects in saved_in_period cohort.",
            "observations": (
                "Append-only saved_*_observations; evidence buckets use latest row and counts."
            ),
            "new_analytical_observation_in_period": NEW_ANALYTICAL_OBSERVATION_IN_PERIOD_DEFINITION,
            "legacy_topics_saved_in_period": (
                "SavedTopic.created_at within period; see top-level topics_saved_in_period."
            ),
        },
        "saved_in_period": {
            "videos": len(cohort_videos),
            "families": len(cohort_families),
            "legacy_topics": legacy_topics_saved_in_period,
            "research_combined": cohort_total,
            "combined_total": combined_saved_total,
        },
        "current_status_counts": current_status,
        "decisions_in_period": decisions,
        "latest_feedback": {
            "research_verdict_distribution": verdict_distribution,
            "cohort_with_latest_feedback": cohort_with_feedback,
            "cohort_without_latest_feedback": cohort_without_feedback,
        },
        "observations": {
            "cohort_with_any_observation": cohort_with_any_observation,
            "cohort_with_multiple_observations": cohort_with_multiple_observations,
            "evidence_state_distribution": evidence_state_distribution,
            "cohort_with_new_analytical_observation_in_period": new_analytical_obs_in_period,
        },
        "pending_signals": {
            "cohort_still_watching": still_watching,
            "cohort_want_to_test": want_to_test,
            "cohort_in_testing": in_testing,
            "cohort_dropped": dropped,
            "cohort_without_feedback": cohort_without_feedback,
            "cohort_single_observation_only": cohort_total
            - cohort_with_multiple_observations
            if cohort_total
            else 0,
        },
        "saved_in_period_items": saved_items,
        "portfolio_hints": {
            "has_saved_research": has_saved_cohort,
            "has_decisions_in_period": has_decisions_in_period,
            "saved_without_decisions_message": (
                "У вас есть сохранённые исследования, но вы ещё не фиксировали решения."
                if has_saved_cohort and not has_decisions_in_period
                else None
            ),
        },
        "interpretation_notes": [
            "Сохранение — это закладка для наблюдения, не факт тестирования идеи.",
            "Статус TESTING означает намерение пользователя, не автоматический outcome Radar.",
            "Оценки аналитика (verdict) и legacy finding_rating — разные шкалы; не объединяются.",
            "Evidence state описывает доступность измерений, не успешность ниши.",
            "Архив не удаляет объект из saved_in_period, если сохранение было в выбранном периоде.",
        ],
    }
