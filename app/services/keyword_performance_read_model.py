"""Persisted keyword performance read model (Stage 1.20E.4)."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from typing import Literal

from sqlalchemy import String, delete, func, or_, select
from sqlalchemy.orm import Session

from app.models.orm import (
    KeywordPerformanceGlobalSnapshot,
    KeywordPerformanceKeywordSnapshot,
    TargetKeyword,
)
from app.services.keyword_performance_evaluation import (
    AttributionMode,
    EvidenceDetail,
    HORIZON_HOURS,
    HORIZON_SNAPSHOT_TOLERANCE_HOURS,
    KeywordBatchAggregates,
    KeywordEvaluationContext,
    KeywordEvaluationOptions,
    build_global_breakout_bundle,
    evaluate_keywords_batch,
    make_evaluation_context,
)
from app.services.keyword_performance_service import (
    KeywordPerformanceListResult,
    KeywordPerformanceMetrics,
    _batch_to_metrics,
    _schedule_fields_fast,
    evaluate_keyword_performance_batch,
)
from app.services.metrics import ensure_utc, utc_now

ReadModelSource = Literal["snapshot", "live_evaluation", "unavailable"]

_ATTRIBUTION_MODES: tuple[AttributionMode, ...] = ("all_hits", "first_discovery")


def _run_id(reference: datetime) -> str:
    return f"keyword_performance_{ensure_utc(reference).strftime('%Y%m%dT%H%M%SZ')}"


def _agg_to_dict(agg: KeywordBatchAggregates) -> dict:
    payload = asdict(agg)
    for key in ("first_scan_at", "last_scan_at"):
        if payload.get(key) is not None:
            payload[key] = ensure_utc(payload[key]).isoformat()
    ed = payload.get("evidence_detail")
    if ed is not None:
        payload["evidence_detail"] = dict(ed)
    return payload


def _agg_from_dict(payload: dict) -> KeywordBatchAggregates:
    for key in ("first_scan_at", "last_scan_at"):
        if payload.get(key):
            payload[key] = datetime.fromisoformat(payload[key])
    ed = payload.pop("evidence_detail", None)
    agg = KeywordBatchAggregates(**payload)
    if ed:
        agg.evidence_detail = EvidenceDetail(
            scan_count=int(ed.get("scan_count", 0)),
            unique_video_count=int(ed.get("unique_video_count", 0)),
            breakout_eligible_video_count=int(ed.get("breakout_eligible_video_count", 0)),
            observed_72h_video_count=int(ed.get("observed_72h_video_count", 0)),
        )
    return agg


def get_latest_global_snapshot(session: Session) -> KeywordPerformanceGlobalSnapshot | None:
    return session.scalar(
        select(KeywordPerformanceGlobalSnapshot)
        .order_by(
            KeywordPerformanceGlobalSnapshot.evaluated_at.desc(),
            KeywordPerformanceGlobalSnapshot.id.desc(),
        )
        .limit(1),
    )


def _context_from_global(
    global_row: KeywordPerformanceGlobalSnapshot,
    *,
    attribution_mode: AttributionMode,
) -> KeywordEvaluationContext:
    return KeywordEvaluationContext(
        evaluated_at=ensure_utc(global_row.evaluated_at),
        attribution_mode=attribution_mode,
        window_from=None,
        window_to=None,
        ranking_version=global_row.ranking_version,
        global_eligible_video_count=int(global_row.global_eligible_video_count),
        horizon_hours=HORIZON_HOURS,
        horizon_snapshot_tolerance_hours=HORIZON_SNAPSHOT_TOLERANCE_HOURS,
        top_decile_rank_cutoff=int(global_row.top_decile_rank_cutoff),
    )


def refresh_keyword_performance_read_model(
    session: Session,
    *,
    evaluated_at: datetime | None = None,
    chunk_size: int = 40,
) -> tuple[str, int]:
    """Recompute full metrics off-UI; persists global + per-keyword rows for both attribution modes."""
    reference = evaluated_at or utc_now()
    run_id = _run_id(reference)
    bundle = build_global_breakout_bundle(session, evaluated_at=reference)
    global_n = bundle.global_eligible_video_count
    context_probe = make_evaluation_context(
        global_eligible_video_count=global_n,
        evaluated_at=reference,
    )
    session.execute(delete(KeywordPerformanceKeywordSnapshot))
    session.execute(delete(KeywordPerformanceGlobalSnapshot))
    session.add(
        KeywordPerformanceGlobalSnapshot(
            run_id=run_id,
            evaluated_at=reference,
            global_eligible_video_count=global_n,
            top_decile_rank_cutoff=context_probe.top_decile_rank_cutoff,
            ranking_version=context_probe.ranking_version,
        ),
    )
    session.flush()
    keywords = list(session.scalars(select(TargetKeyword).order_by(TargetKeyword.id.asc())).all())
    options = KeywordEvaluationOptions(include_breakout=True, include_delayed=True)
    written = 0
    for mode in _ATTRIBUTION_MODES:
        context = KeywordEvaluationContext(
            evaluated_at=reference,
            attribution_mode=mode,
            window_from=None,
            window_to=None,
            ranking_version=context_probe.ranking_version,
            global_eligible_video_count=global_n,
            horizon_hours=HORIZON_HOURS,
            horizon_snapshot_tolerance_hours=HORIZON_SNAPSHOT_TOLERANCE_HOURS,
            top_decile_rank_cutoff=context_probe.top_decile_rank_cutoff,
        )
        for start in range(0, len(keywords), chunk_size):
            chunk = keywords[start : start + chunk_size]
            batch = evaluate_keywords_batch(
                session,
                chunk,
                context=context,
                breakout_map=bundle.breakout_map,
                include_current_tiers=False,
                options=options,
                monitoring_states_by_id=bundle.states_by_id,
            )
            for keyword in chunk:
                agg = batch.get(keyword.id)
                if agg is None:
                    continue
                session.add(
                    KeywordPerformanceKeywordSnapshot(
                        keyword_id=keyword.id,
                        attribution_mode=mode,
                        global_run_id=run_id,
                        evaluated_at=reference,
                        metrics_json=json.dumps(_agg_to_dict(agg)),
                    ),
                )
                written += 1
    session.flush()
    return run_id, written


def _keyword_list_stmt(
    attribution_mode: AttributionMode,
    *,
    lifecycle_status: str | None,
    search: str | None,
):
    stmt = (
        select(TargetKeyword, KeywordPerformanceKeywordSnapshot)
        .join(
            KeywordPerformanceKeywordSnapshot,
            (KeywordPerformanceKeywordSnapshot.keyword_id == TargetKeyword.id)
            & (KeywordPerformanceKeywordSnapshot.attribution_mode == attribution_mode),
        )
        .order_by(TargetKeyword.id.asc())
    )
    if lifecycle_status:
        stmt = stmt.where(TargetKeyword.lifecycle_status == lifecycle_status.lower())
    if search:
        needle = search.strip().lower()
        if needle:
            pattern = f"%{needle}%"
            stmt = stmt.where(
                or_(
                    func.lower(TargetKeyword.keyword).like(pattern),
                    func.cast(TargetKeyword.id, String).like(pattern),  # type: ignore[name-defined]
                ),
            )
    return stmt


def count_keyword_performance_snapshots(
    session: Session,
    *,
    attribution_mode: AttributionMode,
    lifecycle_status: str | None = None,
    search: str | None = None,
) -> int:
    inner = _keyword_list_stmt(
        attribution_mode,
        lifecycle_status=lifecycle_status,
        search=search,
    )
    return int(session.scalar(select(func.count()).select_from(inner.subquery())) or 0)


def list_keyword_performance_from_snapshots(
    session: Session,
    *,
    limit: int,
    offset: int = 0,
    attribution_mode: AttributionMode = "all_hits",
    lifecycle_status: str | None = None,
    search: str | None = None,
) -> KeywordPerformanceListResult | None:
    global_row = get_latest_global_snapshot(session)
    if global_row is None:
        return None
    total = count_keyword_performance_snapshots(
        session,
        attribution_mode=attribution_mode,
        lifecycle_status=lifecycle_status,
        search=search,
    )
    if total == 0:
        context = _context_from_global(global_row, attribution_mode=attribution_mode)
        return KeywordPerformanceListResult(context=context, items=[])

    stmt = _keyword_list_stmt(
        attribution_mode,
        lifecycle_status=lifecycle_status,
        search=search,
    )
    page_limit = max(1, min(limit, 500))
    rows = session.execute(stmt.offset(max(0, offset)).limit(page_limit)).all()
    context = _context_from_global(global_row, attribution_mode=attribution_mode)
    reference = context.evaluated_at
    items: list[KeywordPerformanceMetrics] = []
    for keyword, snap_row in rows:
        agg = _agg_from_dict(json.loads(snap_row.metrics_json))
        agg.keyword = keyword.keyword
        items.append(
            _batch_to_metrics(
                agg,
                keyword,
                context,
                _schedule_fields_fast(keyword, reference),
            ),
        )
    return KeywordPerformanceListResult(context=context, items=items)


def get_keyword_performance_from_snapshot(
    session: Session,
    keyword_id: int,
    *,
    attribution_mode: AttributionMode = "all_hits",
) -> KeywordPerformanceMetrics | None:
    global_row = get_latest_global_snapshot(session)
    if global_row is None:
        return None
    snap = session.scalar(
        select(KeywordPerformanceKeywordSnapshot).where(
            KeywordPerformanceKeywordSnapshot.keyword_id == keyword_id,
            KeywordPerformanceKeywordSnapshot.attribution_mode == attribution_mode,
        ),
    )
    keyword = session.get(TargetKeyword, keyword_id)
    if snap is None or keyword is None:
        return None
    context = _context_from_global(global_row, attribution_mode=attribution_mode)
    agg = _agg_from_dict(json.loads(snap.metrics_json))
    agg.keyword = keyword.keyword
    return _batch_to_metrics(
        agg,
        keyword,
        context,
        _schedule_fields_fast(keyword, context.evaluated_at),
    )


def list_keyword_performance_live_page(
    session: Session,
    *,
    limit: int,
    offset: int = 0,
    from_timestamp: datetime | None = None,
    to_timestamp: datetime | None = None,
    include_current_tiers: bool = False,
    include_breakout: bool = True,
    include_delayed: bool = True,
    attribution_mode: AttributionMode = "all_hits",
) -> KeywordPerformanceListResult:
    keyword_records = list(
        session.scalars(
            select(TargetKeyword)
            .order_by(TargetKeyword.id.asc())
            .offset(max(0, offset))
            .limit(max(1, min(limit, 500))),
        ).all(),
    )
    return evaluate_keyword_performance_batch(
        session,
        keyword_records,
        from_timestamp=from_timestamp,
        to_timestamp=to_timestamp,
        attribution_mode=attribution_mode,
        include_current_tiers=include_current_tiers,
        include_breakout=include_breakout,
        include_delayed=include_delayed,
    )
