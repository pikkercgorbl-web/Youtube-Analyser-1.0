"""Batch read-model for keyword lifecycle evidence (Stage 1.20B). Facts only — no lifecycle automation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.orm import KeywordLifecycleEvent, KeywordScanRun, TargetKeyword
from app.services.keyword_evidence_types import (
    BreakoutEvidence,
    DelayedOutcomeEvidence,
    DiscoveryEvidence,
    DiscoveryVphEvidence,
    EvidenceFamilyMeta,
    KeywordEvidence,
    KeywordEvidenceListResult,
    LifecycleContextEvidence,
    RedundancyEvidence,
    ScanEvidence,
    SchedulingEvidence,
)
from app.services.keyword_performance_evaluation import (
    AttributionMode,
    KeywordBatchAggregates,
    KeywordEvaluationOptions,
    build_global_breakout_bundle,
    evaluate_keywords_batch,
    make_evaluation_context,
)
from app.services.keyword_schedule_state import is_keyword_due
from app.services.keyword_scheduling_policy import PROBATION_READY_SCAN_COUNT, LIFECYCLE_PROBATION
from app.services.metrics import utc_now

logger = logging.getLogger(__name__)

MANUAL_ACTOR_SOURCES = frozenset({"api", "manual"})


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


@dataclass(frozen=True, slots=True)
class _ScanBatchRow:
    total: int
    successful: int
    failed: int
    latest_at: datetime | None
    latest_status: str | None
    total_raw_candidates: int
    total_unique_candidates: int
    total_persisted_videos: int


@dataclass(frozen=True, slots=True)
class _LifecycleBatchRow:
    latest_actor_source: str | None
    last_manual_change_at: datetime | None


def _load_scan_batch(session: Session, keyword_ids: list[int]) -> dict[int, _ScanBatchRow]:
    if not keyword_ids:
        return {}

    agg = session.execute(
        select(
            KeywordScanRun.keyword_id,
            func.count().label("total"),
            func.count().filter(KeywordScanRun.status == "ok").label("successful"),
            func.count().filter(KeywordScanRun.status == "failed").label("failed"),
            func.max(KeywordScanRun.finished_at).label("latest_at"),
            func.coalesce(func.sum(KeywordScanRun.raw_candidates), 0).label("sum_raw"),
            func.coalesce(func.sum(KeywordScanRun.unique_candidates), 0).label("sum_unique"),
            func.coalesce(func.sum(KeywordScanRun.persisted_videos), 0).label("sum_persisted"),
        )
        .where(KeywordScanRun.keyword_id.in_(keyword_ids))
        .group_by(KeywordScanRun.keyword_id),
    ).all()

    latest_status_by_id: dict[int, str] = {}
    sub = (
        select(
            KeywordScanRun.keyword_id,
            func.max(KeywordScanRun.finished_at).label("mx"),
        )
        .where(KeywordScanRun.keyword_id.in_(keyword_ids))
        .group_by(KeywordScanRun.keyword_id)
        .subquery()
    )
    status_rows = session.execute(
        select(KeywordScanRun.keyword_id, KeywordScanRun.status).join(
            sub,
            (KeywordScanRun.keyword_id == sub.c.keyword_id)
            & (KeywordScanRun.finished_at == sub.c.mx),
        ),
    ).all()
    for kid, status in status_rows:
        latest_status_by_id[int(kid)] = status

    out: dict[int, _ScanBatchRow] = {}
    for row in agg:
        kid = int(row.keyword_id)
        out[kid] = _ScanBatchRow(
            total=int(row.total or 0),
            successful=int(row.successful or 0),
            failed=int(row.failed or 0),
            latest_at=row.latest_at,
            latest_status=latest_status_by_id.get(kid),
            total_raw_candidates=int(row.sum_raw or 0),
            total_unique_candidates=int(row.sum_unique or 0),
            total_persisted_videos=int(row.sum_persisted or 0),
        )
    return out


def _load_lifecycle_batch(session: Session, keyword_ids: list[int]) -> dict[int, _LifecycleBatchRow]:
    if not keyword_ids:
        return {}

    events = list(
        session.scalars(
            select(KeywordLifecycleEvent)
            .where(KeywordLifecycleEvent.keyword_id.in_(keyword_ids))
            .order_by(KeywordLifecycleEvent.keyword_id.asc(), KeywordLifecycleEvent.changed_at.desc()),
        ).all(),
    )
    latest_actor: dict[int, str] = {}
    last_manual: dict[int, datetime] = {}
    for event in events:
        kid = event.keyword_id
        if kid not in latest_actor:
            latest_actor[kid] = event.actor_source
        if event.actor_source in MANUAL_ACTOR_SOURCES:
            prev = last_manual.get(kid)
            if prev is None or event.changed_at > prev:
                last_manual[kid] = event.changed_at

    return {
        kid: _LifecycleBatchRow(
            latest_actor_source=latest_actor.get(kid),
            last_manual_change_at=last_manual.get(kid),
        )
        for kid in keyword_ids
    }


def _scan_meta(total: int) -> EvidenceFamilyMeta:
    if total <= 0:
        return EvidenceFamilyMeta(availability="insufficient", role="primary")
    return EvidenceFamilyMeta(availability="available", role="primary")


def _discovery_meta(scan_total: int) -> EvidenceFamilyMeta:
    if scan_total <= 0:
        return EvidenceFamilyMeta(availability="insufficient", role="primary")
    return EvidenceFamilyMeta(availability="available", role="primary")


def _vph_meta(count: int) -> EvidenceFamilyMeta:
    if count <= 0:
        return EvidenceFamilyMeta(availability="insufficient", role="supporting")
    return EvidenceFamilyMeta(availability="available", role="supporting")


def _breakout_meta(*, included: bool, eligible: int, global_n: int | None) -> EvidenceFamilyMeta:
    if not included:
        return EvidenceFamilyMeta(availability="unavailable", role="not_ready")
    if global_n is not None and global_n <= 0:
        return EvidenceFamilyMeta(availability="unavailable", role="not_ready")
    if eligible <= 0:
        return EvidenceFamilyMeta(availability="insufficient", role="supporting")
    return EvidenceFamilyMeta(availability="available", role="supporting")


def _delayed_meta(*, included: bool, attributed: int, matured: int) -> EvidenceFamilyMeta:
    if not included:
        return EvidenceFamilyMeta(availability="unavailable", role="not_ready")
    if attributed <= 0:
        return EvidenceFamilyMeta(availability="insufficient", role="not_ready")
    if matured <= 0:
        return EvidenceFamilyMeta(availability="insufficient", role="not_ready")
    return EvidenceFamilyMeta(availability="available", role="not_ready")


def _scheduling_fields_fast(
    keyword: TargetKeyword,
    *,
    evaluated_at: datetime,
    successful_scan_count: int,
) -> tuple[bool, str | None]:
    due = is_keyword_due(keyword, now=evaluated_at)
    hint = None
    if keyword.lifecycle_status == LIFECYCLE_PROBATION and successful_scan_count >= PROBATION_READY_SCAN_COUNT:
        hint = "probation_ready_for_review"
    return due, hint


def _merge_evidence(
    keyword: TargetKeyword,
    agg: KeywordBatchAggregates,
    scan_row: _ScanBatchRow | None,
    lifecycle_row: _LifecycleBatchRow | None,
    *,
    attribution_mode: str,
    evaluated_at: datetime,
    include_breakout: bool,
    include_delayed: bool,
    ranking_version: str | None,
    global_eligible_video_count: int | None,
    horizon_hours: int | None,
    horizon_tolerance: float | None,
) -> KeywordEvidence:
    scan_total = scan_row.total if scan_row else agg.scan_count
    successful = scan_row.successful if scan_row else 0
    failed = scan_row.failed if scan_row else max(0, scan_total - successful)
    sum_raw = scan_row.total_raw_candidates if scan_row else 0
    sum_unique = scan_row.total_unique_candidates if scan_row else 0
    sum_persisted = scan_row.total_persisted_videos if scan_row else 0

    is_due, scheduling_hint = _scheduling_fields_fast(
        keyword,
        evaluated_at=evaluated_at,
        successful_scan_count=successful,
    )

    unique_videos = agg.unique_video_count
    new_to_db = agg.new_to_corpus_video_count
    attributed = agg.attributed_video_count

    breakout_rate = agg.top_decile_breakout_rate if include_breakout and agg.breakout_eligible_video_count > 0 else None

    median_growth = agg.median_absolute_view_growth_72h if include_delayed and agg.observed_72h_video_count > 0 else None
    p90_growth = agg.p90_absolute_view_growth_72h if include_delayed and agg.observed_72h_video_count > 0 else None

    return KeywordEvidence(
        keyword_id=keyword.id,
        keyword=keyword.keyword,
        lifecycle_status=keyword.lifecycle_status,
        source_type=keyword.source_type,
        parent_keyword_id=keyword.parent_keyword_id,
        scan=ScanEvidence(
            meta=_scan_meta(scan_total),
            total_scan_count=scan_total,
            successful_scan_count=successful,
            failed_scan_count=failed,
            latest_scan_at=scan_row.latest_at if scan_row else agg.last_scan_at,
            latest_scan_status=scan_row.latest_status if scan_row else None,
            total_raw_candidates=sum_raw,
            total_unique_candidates=sum_unique,
            total_persisted_videos=sum_persisted,
        ),
        discovery=DiscoveryEvidence(
            meta=_discovery_meta(scan_total),
            total_discovery_hits=agg.discovery_hit_count,
            unique_discovered_video_count=unique_videos,
            new_to_database_video_count=new_to_db,
            persisted_for_monitoring_count=agg.persisted_for_monitoring_count,
            attributed_observation_count=attributed,
            unique_candidate_rate=_ratio(sum_unique, sum_raw),
            persistence_rate=_ratio(sum_persisted, sum_unique),
            new_video_rate=_ratio(new_to_db, unique_videos) if unique_videos else None,
        ),
        redundancy=RedundancyEvidence(
            meta=EvidenceFamilyMeta(
                availability="available" if agg.discovery_hit_count > 0 else "insufficient",
                role="supporting",
            ),
            within_keyword_duplicate_count=agg.within_keyword_duplicate_hit_count,
            cross_keyword_duplicate_count=agg.cross_keyword_duplicate_count,
            duplicate_hit_count=agg.duplicate_hit_count,
            duplicate_rate=agg.duplicate_rate,
            unique_yield_rate=_ratio(new_to_db, unique_videos) if unique_videos else None,
        ),
        discovery_vph=DiscoveryVphEvidence(
            meta=_vph_meta(agg.discovery_vph_observation_count),
            observation_count=agg.discovery_vph_observation_count,
            median_discovery_vph=agg.median_vph_at_discovery,
            p90_discovery_vph=agg.p90_vph_at_discovery,
        ),
        breakout=BreakoutEvidence(
            meta=_breakout_meta(
                included=include_breakout,
                eligible=agg.breakout_eligible_video_count,
                global_n=global_eligible_video_count,
            ),
            breakout_eligible_count=agg.breakout_eligible_video_count if include_breakout else 0,
            top_decile_breakout_count=agg.top_decile_breakout_count if include_breakout else 0,
            top_decile_breakout_rate=breakout_rate,
            ranking_version=ranking_version if include_breakout else None,
            global_eligible_video_count=global_eligible_video_count if include_breakout else None,
        ),
        delayed_outcome=DelayedOutcomeEvidence(
            meta=_delayed_meta(
                included=include_delayed,
                attributed=attributed,
                matured=agg.matured_72h_video_count,
            ),
            attributed_observation_count=attributed,
            matured_72h_count=agg.matured_72h_video_count if include_delayed else 0,
            valid_72h_outcome_count=agg.observed_72h_video_count if include_delayed else 0,
            missing_72h_outcome_count=agg.missing_72h_video_count if include_delayed else 0,
            median_72h_growth=median_growth,
            p90_72h_growth=p90_growth,
            horizon_hours=horizon_hours if include_delayed else None,
            horizon_snapshot_tolerance_hours=horizon_tolerance if include_delayed else None,
        ),
        lifecycle_context=LifecycleContextEvidence(
            meta=EvidenceFamilyMeta(availability="available", role="primary"),
            status_changed_at=keyword.status_changed_at,
            status_reason=keyword.status_reason,
            last_manual_change_at=lifecycle_row.last_manual_change_at if lifecycle_row else None,
            latest_lifecycle_actor_source=lifecycle_row.latest_actor_source if lifecycle_row else None,
        ),
        scheduling=SchedulingEvidence(
            meta=EvidenceFamilyMeta(availability="available", role="primary"),
            last_checked=keyword.last_checked,
            next_scan_at=keyword.next_scan_at,
            scan_interval_seconds=keyword.scan_interval_seconds,
            is_due=is_due,
            scheduling_hint=scheduling_hint,
        ),
        attribution_mode=attribution_mode,
        evaluated_at=evaluated_at,
        include_breakout=include_breakout,
        include_delayed=include_delayed,
    )


def list_keyword_evidence(
    session: Session,
    *,
    limit: int = 100,
    lifecycle_status: str | None = None,
    attribution_mode: AttributionMode = "all_hits",
    include_breakout: bool = False,
    include_delayed: bool = False,
    evaluated_at: datetime | None = None,
) -> KeywordEvidenceListResult:
    reference = evaluated_at or utc_now()
    stmt = select(TargetKeyword).order_by(TargetKeyword.id.asc())
    if lifecycle_status:
        stmt = stmt.where(TargetKeyword.lifecycle_status == lifecycle_status)
    keyword_records = list(session.scalars(stmt.limit(max(1, limit))).all())
    return _build_evidence_list(
        session,
        keyword_records,
        attribution_mode=attribution_mode,
        include_breakout=include_breakout,
        include_delayed=include_delayed,
        evaluated_at=reference,
    )


def get_keyword_evidence(
    session: Session,
    keyword_id: int,
    *,
    attribution_mode: AttributionMode = "all_hits",
    include_breakout: bool = True,
    include_delayed: bool = True,
    evaluated_at: datetime | None = None,
) -> KeywordEvidence | None:
    keyword = session.get(TargetKeyword, keyword_id)
    if keyword is None:
        return None
    result = _build_evidence_list(
        session,
        [keyword],
        attribution_mode=attribution_mode,
        include_breakout=include_breakout,
        include_delayed=include_delayed,
        evaluated_at=evaluated_at or utc_now(),
    )
    return result.items[0] if result.items else None


def _build_evidence_list(
    session: Session,
    keyword_records: list[TargetKeyword],
    *,
    attribution_mode: AttributionMode,
    include_breakout: bool,
    include_delayed: bool,
    evaluated_at: datetime,
) -> KeywordEvidenceListResult:
    if not keyword_records:
        return KeywordEvidenceListResult(
            evaluated_at=evaluated_at,
            attribution_mode=attribution_mode,
            include_breakout=include_breakout,
            include_delayed=include_delayed,
            ranking_version=None,
            global_eligible_video_count=None,
            items=[],
        )

    keyword_ids = [k.id for k in keyword_records]
    scan_batch = _load_scan_batch(session, keyword_ids)
    lifecycle_batch = _load_lifecycle_batch(session, keyword_ids)

    options = KeywordEvaluationOptions(
        include_breakout=include_breakout,
        include_delayed=include_delayed,
    )
    breakout_map: dict = {}
    global_n = 0
    states_by_id = None
    if include_breakout:
        bundle = build_global_breakout_bundle(session, evaluated_at=evaluated_at)
        breakout_map = bundle.breakout_map
        global_n = bundle.global_eligible_video_count
        states_by_id = bundle.states_by_id

    ctx = make_evaluation_context(
        global_eligible_video_count=global_n if include_breakout else 0,
        attribution_mode=attribution_mode,
        evaluated_at=evaluated_at,
    )
    batch = evaluate_keywords_batch(
        session,
        keyword_records,
        context=ctx,
        breakout_map=breakout_map,
        include_current_tiers=False,
        options=options,
        monitoring_states_by_id=states_by_id,
    )

    items: list[KeywordEvidence] = []
    for keyword in keyword_records:
        agg = batch.get(keyword.id)
        if agg is None:
            continue
        items.append(
            _merge_evidence(
                keyword,
                agg,
                scan_batch.get(keyword.id),
                lifecycle_batch.get(keyword.id),
                attribution_mode=attribution_mode,
                evaluated_at=ctx.evaluated_at,
                include_breakout=include_breakout,
                include_delayed=include_delayed,
                ranking_version=ctx.ranking_version if include_breakout else None,
                global_eligible_video_count=ctx.global_eligible_video_count if include_breakout else None,
                horizon_hours=ctx.horizon_hours,
                horizon_tolerance=ctx.horizon_snapshot_tolerance_hours,
            ),
        )

    return KeywordEvidenceListResult(
        evaluated_at=ctx.evaluated_at,
        attribution_mode=ctx.attribution_mode,
        include_breakout=include_breakout,
        include_delayed=include_delayed,
        ranking_version=ctx.ranking_version if include_breakout else None,
        global_eligible_video_count=ctx.global_eligible_video_count if include_breakout else None,
        items=items,
    )
