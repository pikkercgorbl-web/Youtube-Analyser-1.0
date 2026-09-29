"""Wall-time and SQL profiling for keyword performance list (Stage 1.18D1)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.models.orm import KeywordDiscoveryHit, TargetKeyword
from app.services.keyword_performance_evaluation import (
    KeywordEvaluationOptions,
    build_global_breakout_bundle,
    evaluate_keywords_batch,
    make_evaluation_context,
)
from app.services.keyword_performance_service import (
    KeywordPerformanceListResult,
    _batch_to_metrics,
    _schedule_fields_fast,
)
from app.services.metrics import utc_now


@dataclass
class KeywordPerformanceProfile:
    phases_seconds: dict[str, float] = field(default_factory=dict)
    sql_query_count: int = 0
    sql_statements_sample: list[str] = field(default_factory=list)
    row_counts: dict[str, int] = field(default_factory=dict)
    modes: dict[str, Any] = field(default_factory=dict)


def _attach_query_listener(session: Session) -> tuple[list[str], Any, Any]:
    engine = session.get_bind()
    statements: list[str] = []

    def before_cursor_execute(
        conn,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ) -> None:
        statements.append(str(statement))

    event.listen(engine, "before_cursor_execute", before_cursor_execute, retval=False)
    return statements, engine, before_cursor_execute


def profile_list_keyword_performance(
    session: Session,
    *,
    limit: int = 100,
    include_breakout: bool = True,
    include_delayed: bool = True,
    include_current_tiers: bool = False,
    attribution_mode: str = "all_hits",
) -> tuple[KeywordPerformanceProfile, KeywordPerformanceListResult]:
    profile = KeywordPerformanceProfile(
        modes={
            "include_breakout": include_breakout,
            "include_delayed": include_delayed,
            "include_current_tiers": include_current_tiers,
            "attribution_mode": attribution_mode,
        },
    )
    statements, engine, query_handler = _attach_query_listener(session)

    reference = utc_now()
    options = KeywordEvaluationOptions(
        include_breakout=include_breakout,
        include_delayed=include_delayed,
    )

    try:
        t0 = time.perf_counter()
        keyword_records = list(
            session.scalars(
                select(TargetKeyword).order_by(TargetKeyword.id.asc()).limit(max(1, limit)),
            ).all(),
        )
        profile.phases_seconds["keyword_load"] = time.perf_counter() - t0
        profile.row_counts["keywords_loaded"] = len(keyword_records)

        bundle = None
        breakout_map: dict = {}
        global_n = 0
        states_by_id = None

        t1 = time.perf_counter()
        if options.include_breakout:
            bundle = build_global_breakout_bundle(session, evaluated_at=reference)
            breakout_map = bundle.breakout_map
            global_n = bundle.global_eligible_video_count
            states_by_id = bundle.states_by_id
            profile.row_counts["global_monitoring_videos"] = len(bundle.states_by_id)
            profile.row_counts["global_breakout_eligible"] = global_n
        profile.phases_seconds["breakout_monitoring_pool"] = time.perf_counter() - t1

        context = make_evaluation_context(
            global_eligible_video_count=global_n if options.include_breakout else 0,
            attribution_mode=attribution_mode,  # type: ignore[arg-type]
            evaluated_at=reference,
        )

        t2 = time.perf_counter()
        batch = evaluate_keywords_batch(
            session,
            keyword_records,
            context=context,
            breakout_map=breakout_map,
            include_current_tiers=include_current_tiers,
            options=options,
            monitoring_states_by_id=states_by_id,
        )
        profile.phases_seconds["batch_evaluation"] = time.perf_counter() - t2

        t3 = time.perf_counter()
        items = [
            _batch_to_metrics(
                batch[keyword.id],
                keyword,
                context,
                _schedule_fields_fast(keyword, reference),
            )
            for keyword in keyword_records
            if keyword.id in batch
        ]
        profile.phases_seconds["serialization_prep"] = time.perf_counter() - t3

        hit_count = session.scalar(select(func.count()).select_from(KeywordDiscoveryHit)) or 0
        profile.row_counts["discovery_hits_total"] = int(hit_count)
        profile.row_counts["attributed_videos_sum"] = sum(
            i.attributed_video_count or 0 for i in items
        )

        result = KeywordPerformanceListResult(context=context, items=items)
    finally:
        event.remove(engine, "before_cursor_execute", query_handler)

    profile.sql_query_count = len(statements)
    profile.sql_statements_sample = statements[:12]
    profile.phases_seconds["total"] = sum(
        profile.phases_seconds.get(k, 0.0)
        for k in (
            "keyword_load",
            "breakout_monitoring_pool",
            "batch_evaluation",
            "serialization_prep",
        )
    )
    return profile, result
