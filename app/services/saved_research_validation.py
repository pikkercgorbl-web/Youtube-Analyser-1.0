"""Validation metrics and feedback overview for Saved Research (Stage 1.22D.1)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.orm import (
    SavedFamily,
    SavedFamilyObservation,
    SavedVideo,
    SavedVideoObservation,
)
from app.services.metrics import ensure_utc
from app.services.saved_research_daily_intelligence import DAILY_INTELLIGENCE_SAVE_ANCHOR_KIND
from app.services.saved_video_manual_refresh import (
    MANUAL_SAVED_VIDEO_REFRESH_SOURCE,
    is_manual_observation_run_id,
)

EvidenceState = Literal["validated", "pending", "insufficient"]
FamilyPresenceState = Literal[
    "in_bounded_snapshot",
    "not_in_bounded_snapshot",
    "unknown",
]

DELAYED_72H_EVIDENCE_STATES = frozenset({"confirmed", "not_confirmed", "pending", "missing", "unavailable"})


def _parse_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text or "{}")
    except json.JSONDecodeError:
        return {}


def observation_is_daily_intelligence_anchor(row: SavedVideoObservation | None) -> bool:
    if row is None:
        return False
    payload = _parse_json(row.payload_json)
    return payload.get("observation_kind") == DAILY_INTELLIGENCE_SAVE_ANCHOR_KIND


def family_observation_is_daily_intelligence_anchor(row: SavedFamilyObservation | None) -> bool:
    if row is None:
        return False
    payload = _parse_json(row.payload_json)
    return payload.get("observation_kind") == DAILY_INTELLIGENCE_SAVE_ANCHOR_KIND


def observation_is_manual(row: SavedVideoObservation | None) -> bool:
    if row is None:
        return False
    payload = _parse_json(row.payload_json)
    if payload.get("observation_kind") == MANUAL_SAVED_VIDEO_REFRESH_SOURCE:
        return True
    return is_manual_observation_run_id(row.attention_run_id)


def measurement_source_for_video(row: SavedVideoObservation | None) -> str | None:
    if row is None:
        return None
    if observation_is_manual(row):
        return "manual_youtube_refresh"
    if observation_is_daily_intelligence_anchor(row):
        return "daily_intelligence_anchor"
    payload = _parse_json(row.payload_json)
    if payload.get("attention_run_id") or row.attention_run_id:
        return "attention_refresh"
    return None


def _pct_change(before: float, after: float) -> float | None:
    if before <= 0:
        return None
    return round((after - before) / before * 100.0, 2)


def compute_video_validation(
    *,
    frozen: dict[str, Any],
    live: SavedVideoObservation | None,
    saved_at: datetime,
    observation_count: int,
) -> dict[str, Any]:
    evidence = frozen.get("evidence") or {}
    frozen_views = evidence.get("views")
    frozen_vph = evidence.get("vph")
    latest_views = live.views if live is not None else None
    latest_vph = live.vph if live is not None else None
    is_manual = observation_is_manual(live)
    source = measurement_source_for_video(live)
    measured_at = ensure_utc(live.observed_at).isoformat() if live else None

    elapsed_hours: float | None = None
    if live is not None:
        elapsed = ensure_utc(live.observed_at) - ensure_utc(saved_at)
        if elapsed.total_seconds() >= 0:
            elapsed_hours = round(elapsed.total_seconds() / 3600.0, 2)

    views_comparable = frozen_views is not None and latest_views is not None
    view_delta: int | None = None
    view_delta_pct: float | None = None
    if views_comparable:
        view_delta = int(latest_views) - int(frozen_views)
        view_delta_pct = _pct_change(float(frozen_views), float(latest_views))

    vph_comparable = frozen_vph is not None and latest_vph is not None
    vph_delta: float | None = None
    vph_delta_pct: float | None = None
    if vph_comparable:
        vph_delta = round(float(latest_vph) - float(frozen_vph), 4)
        vph_delta_pct = _pct_change(float(frozen_vph), float(latest_vph))

    delayed_72h: str | None = None
    delayed_72h_available = False
    is_di_anchor = observation_is_daily_intelligence_anchor(live)
    if live is not None and not is_manual and not is_di_anchor and live.delayed_outcome_state:
        delayed_72h = live.delayed_outcome_state
        delayed_72h_available = delayed_72h in DELAYED_72H_EVIDENCE_STATES

    hypotheses: list[str] = []
    if observation_count <= 1:
        hypotheses.append("Нужна ещё хотя бы одна точка наблюдения для сравнения динамики.")
    if is_manual and delayed_72h_available:
        hypotheses.append("72ч outcome доступен только из Attention-наблюдений, не из ручного refresh.")
    if not views_comparable:
        hypotheses.append("Сравнение просмотров недоступно — нет frozen или latest значения.")
    if live is not None and not live.video_present_in_attention:
        hypotheses.append("Видео сейчас вне bounded Attention sample — это не доказательство провала.")

    evidence_state: EvidenceState
    if not views_comparable and not vph_comparable and not delayed_72h_available:
        evidence_state = "insufficient"
    elif observation_count <= 1 and not delayed_72h_available:
        evidence_state = "pending"
    elif views_comparable or vph_comparable or (
        delayed_72h_available and delayed_72h in ("confirmed", "not_confirmed")
    ):
        evidence_state = "validated"
    else:
        evidence_state = "pending"

    return {
        "evidence_state": evidence_state,
        "frozen_views": frozen_views,
        "frozen_vph": frozen_vph,
        "latest_views": latest_views,
        "latest_vph": latest_vph,
        "view_delta": view_delta,
        "view_delta_pct": view_delta_pct,
        "vph_delta": vph_delta,
        "vph_delta_pct": vph_delta_pct,
        "elapsed_hours_since_save": elapsed_hours,
        "latest_measured_at": measured_at,
        "latest_measurement_source": source,
        "latest_observation_is_manual": is_manual,
        "observation_count": observation_count,
        "delayed_72h_state": delayed_72h if delayed_72h_available else None,
        "delayed_72h_from_manual": False,
        "unverified_hypotheses": hypotheses,
    }


def compute_family_validation(
    *,
    frozen: dict[str, Any],
    live: SavedFamilyObservation | None,
    observation_count: int,
) -> dict[str, Any]:
    family = frozen.get("family") or {}
    frozen_video_count = family.get("video_count")
    frozen_channel_count = family.get("channel_count")
    support_sources = list(family.get("support_sources") or [])
    quality_flags_frozen = list(family.get("quality_flags") or [])

    presence: FamilyPresenceState = "unknown"
    if live is not None:
        presence = "in_bounded_snapshot" if live.family_present else "not_in_bounded_snapshot"

    current_video_count = live.video_count if live is not None and live.family_present else None
    current_channel_count = live.channel_count if live is not None and live.family_present else None
    quality_flags_live: list[str] = []
    if live is not None and live.family_present:
        try:
            quality_flags_live = json.loads(live.quality_flags_json or "[]")
        except json.JSONDecodeError:
            quality_flags_live = []

    video_delta: int | None = None
    channel_delta: int | None = None
    counts_comparable = live is not None and live.family_present
    if counts_comparable and frozen_video_count is not None and current_video_count is not None:
        video_delta = int(current_video_count) - int(frozen_video_count)
    if counts_comparable and frozen_channel_count is not None and current_channel_count is not None:
        channel_delta = int(current_channel_count) - int(frozen_channel_count)

    hypotheses: list[str] = []
    if presence == "not_in_bounded_snapshot":
        hypotheses.append(
            "Тема не в текущем bounded Top-N Attention — это не автоматический провал гипотезы.",
        )
    if observation_count <= 1:
        hypotheses.append("Мало точек наблюдения для оценки динамики темы.")

    evidence_state: EvidenceState
    if live is None:
        evidence_state = "insufficient"
    elif observation_count <= 1:
        evidence_state = "pending"
    elif counts_comparable and (video_delta is not None or channel_delta is not None):
        evidence_state = "validated"
    elif presence == "in_bounded_snapshot":
        evidence_state = "validated"
    else:
        evidence_state = "pending"

    return {
        "evidence_state": evidence_state,
        "frozen_video_count": frozen_video_count,
        "frozen_channel_count": frozen_channel_count,
        "current_video_count": current_video_count,
        "current_channel_count": current_channel_count,
        "video_count_delta": video_delta,
        "channel_count_delta": channel_delta,
        "presence_in_bounded_snapshot": presence,
        "observation_count": observation_count,
        "support_sources_at_save": support_sources,
        "quality_flags_at_save": quality_flags_frozen,
        "quality_flags_latest": quality_flags_live,
        "unverified_hypotheses": hypotheses,
    }


def _observation_counts_videos(session: Session, ids: list[int]) -> dict[int, int]:
    if not ids:
        return {}
    rows = session.execute(
        select(SavedVideoObservation.saved_video_id, func.count())
        .where(SavedVideoObservation.saved_video_id.in_(ids))
        .group_by(SavedVideoObservation.saved_video_id),
    ).all()
    return {int(r[0]): int(r[1]) for r in rows}


def _observation_counts_families(session: Session, ids: list[int]) -> dict[int, int]:
    if not ids:
        return {}
    rows = session.execute(
        select(SavedFamilyObservation.saved_family_id, func.count())
        .where(SavedFamilyObservation.saved_family_id.in_(ids))
        .group_by(SavedFamilyObservation.saved_family_id),
    ).all()
    return {int(r[0]): int(r[1]) for r in rows}


@dataclass(frozen=True, slots=True)
class FeedbackOverviewOptions:
    archived: Literal["active", "archived", "all"] = "active"
    video_limit: int = 50
    video_offset: int = 0
    family_limit: int = 50
    family_offset: int = 0


def build_feedback_overview(session: Session, options: FeedbackOverviewOptions) -> dict[str, Any]:
    from app.services.saved_research import (
        export_frozen_family,
        export_frozen_video,
        latest_family_observations,
        latest_video_observations,
        list_families,
        list_videos,
    )

    videos = list_videos(session, archived=options.archived)
    families = list_families(session, archived=options.archived)

    status_counts: dict[str, int] = {}
    for row in videos + families:
        key = "ARCHIVED" if row.archived_at else row.status
        status_counts[key] = status_counts.get(key, 0) + 1

    video_ids = [v.id for v in videos]
    family_ids = [f.id for f in families]
    live_videos = latest_video_observations(session, video_ids)
    live_families = latest_family_observations(session, family_ids)
    obs_counts_v = _observation_counts_videos(session, video_ids)
    obs_counts_f = _observation_counts_families(session, family_ids)

    evidence_totals = {"validated": 0, "pending": 0, "insufficient": 0}
    video_items: list[dict[str, Any]] = []
    for row in videos:
        frozen = export_frozen_video(row)
        live = live_videos.get(row.id)
        validation = compute_video_validation(
            frozen=frozen,
            live=live,
            saved_at=row.saved_at,
            observation_count=obs_counts_v.get(row.id, 0),
        )
        evidence_totals[validation["evidence_state"]] += 1
        video_items.append(
            {
                "kind": "video",
                "id": row.id,
                "title": row.frozen_title,
                "status": row.status,
                "updated_at": ensure_utc(row.updated_at).isoformat(),
                "validation": validation,
            },
        )

    family_items: list[dict[str, Any]] = []
    for row in families:
        frozen = export_frozen_family(row)
        live = live_families.get(row.id)
        validation = compute_family_validation(
            frozen=frozen,
            live=live,
            observation_count=obs_counts_f.get(row.id, 0),
        )
        evidence_totals[validation["evidence_state"]] += 1
        family_items.append(
            {
                "kind": "family",
                "id": row.id,
                "label": row.frozen_label,
                "status": row.status,
                "updated_at": ensure_utc(row.updated_at).isoformat(),
                "validation": validation,
            },
        )

    video_items.sort(key=lambda r: r["updated_at"], reverse=True)
    family_items.sort(key=lambda r: r["updated_at"], reverse=True)

    measurable_growth = [
        item
        for item in video_items
        if item["validation"].get("view_delta") is not None and item["validation"]["view_delta"] > 0
    ][:10]
    insufficient = [
        item
        for item in video_items + family_items
        if item["validation"]["evidence_state"] == "insufficient"
    ][:15]
    recently_updated = sorted(
        video_items + family_items,
        key=lambda r: r["updated_at"],
        reverse=True,
    )[:12]

    v_slice = video_items[options.video_offset : options.video_offset + options.video_limit]
    f_slice = family_items[options.family_offset : options.family_offset + options.family_limit]

    return {
        "status_counts": status_counts,
        "evidence_summary": evidence_totals,
        "recently_updated": recently_updated,
        "measurable_growth_videos": measurable_growth,
        "insufficient_evidence": insufficient,
        "videos": {
            "items": v_slice,
            "total": len(video_items),
            "limit": options.video_limit,
            "offset": options.video_offset,
        },
        "families": {
            "items": f_slice,
            "total": len(family_items),
            "limit": options.family_limit,
            "offset": options.family_offset,
        },
        "interpretation_notes": [
            "Метрики читаются из frozen snapshot и append-only observations — без YouTube fetch.",
            "Ручное обновление не считается подтверждением 72ч delayed outcome.",
            "Исчезновение темы из bounded Attention sample не трактуется как провал.",
        ],
    }
