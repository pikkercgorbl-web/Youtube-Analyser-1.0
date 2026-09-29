"""Profile legacy vs SQL maturity path (Stage 1.19B1)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import event, func, select, text

from app.models.db import SessionLocal
from app.models.orm import KeywordDiscoveryHit
from app.services.operations_maturity_sql import (
    _combined_maturity_sql,
    _dialect,
    compute_maturity_aggregate_sql,
)
from app.services.operations_overview_service import compute_keyword_outcome_maturity_legacy


def _count_queries(session, fn) -> tuple[object, int, float]:
    engine = session.get_bind()
    count = 0

    def before_cursor_execute(*_a, **_k) -> None:
        nonlocal count
        count += 1

    event.listen(engine, "before_cursor_execute", before_cursor_execute, retval=False)
    try:
        start = time.perf_counter()
        result = fn()
        elapsed = time.perf_counter() - start
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
    return result, count, elapsed


def _legacy_phases(session, mode: str) -> dict:
    from app.models.orm import KeywordDiscoveryHit as Hit
    from app.services.keyword_performance_evaluation import (
        _first_discovery_owner,
        _first_hit_per_keyword_video,
        load_snapshots_for_horizon,
        match_horizon_outcome,
    )
    from app.services.metrics import utc_now

    now = utc_now()
    phases: dict[str, float | int] = {}

    t0 = time.perf_counter()
    hits = list(session.scalars(select(Hit)).all())
    phases["load_raw_hits_sec"] = round(time.perf_counter() - t0, 4)
    phases["raw_hit_rows"] = len(hits)

    t0 = time.perf_counter()
    if mode == "first_discovery":
        owner = _first_discovery_owner(hits)
        first_map = _first_hit_per_keyword_video(hits)
        baselines = []
        for vid, kid in owner.items():
            hit = first_map.get((kid, vid))
            if hit:
                baselines.append(hit)
    else:
        first_map = _first_hit_per_keyword_video(hits)
        baselines = list(first_map.values())
    phases["dedupe_baselines_sec"] = round(time.perf_counter() - t0, 4)
    phases["baseline_objects"] = len(baselines)

    t0 = time.perf_counter()
    matured = []
    pending = 0
    for hit in baselines:
        from datetime import timedelta

        from app.services.keyword_performance_evaluation import HORIZON_HOURS
        from app.services.metrics import ensure_utc

        maturity_at = ensure_utc(hit.discovered_at) + timedelta(hours=HORIZON_HOURS)
        if now < maturity_at:
            pending += 1
        else:
            if hit.views_at_discovery is not None:
                matured.append(hit)
    phases["classify_pending_matured_sec"] = round(time.perf_counter() - t0, 4)
    phases["pending_count"] = pending
    phases["matured_with_views"] = len(matured)

    t0 = time.perf_counter()
    snapshots = {}
    if matured:
        from datetime import timedelta

        from app.services.keyword_performance_evaluation import (
            HORIZON_HOURS,
            HORIZON_SNAPSHOT_TOLERANCE_HOURS,
        )
        from app.services.metrics import ensure_utc

        min_d = min(ensure_utc(h.discovered_at) for h in matured)
        max_d = max(ensure_utc(h.discovered_at) for h in matured)
        captured_from = min_d + timedelta(hours=HORIZON_HOURS - HORIZON_SNAPSHOT_TOLERANCE_HOURS)
        captured_to = max_d + timedelta(hours=HORIZON_HOURS + HORIZON_SNAPSHOT_TOLERANCE_HOURS)
        video_ids = {h.video_id for h in matured}
        snapshots = load_snapshots_for_horizon(
            session,
            video_ids,
            captured_from=captured_from,
            captured_to=captured_to,
        )
    phases["horizon_snapshot_query_sec"] = round(time.perf_counter() - t0, 4)
    phases["snapshot_videos_loaded"] = len(snapshots)

    t0 = time.perf_counter()
    valid = 0
    missing = 0
    from app.services.operations_overview_service import KeywordVideoBaseline

    for hit in matured:
        base = KeywordVideoBaseline(
            keyword_id=hit.keyword_id,
            video_id=hit.video_id,
            discovery_at=hit.discovered_at,
            views_at_discovery=hit.views_at_discovery,
            vph_at_discovery=hit.vph_at_discovery,
        )
        if match_horizon_outcome(base, snapshots) is None:
            missing += 1
        else:
            valid += 1
    phases["snapshot_matching_sec"] = round(time.perf_counter() - t0, 4)
    phases["valid_count"] = valid
    phases["missing_count"] = missing
    return phases


def main() -> int:
    session = SessionLocal()
    try:
        raw_hits = session.scalar(select(func.count()).select_from(KeywordDiscoveryHit)) or 0
        legacy_report: dict = {"raw_hits": raw_hits}
        for mode in ("all_hits", "first_discovery"):
            legacy, legacy_q, legacy_t = _count_queries(
                session,
                lambda m=mode: compute_keyword_outcome_maturity_legacy(
                    session,
                    attribution_mode=m,
                ),
            )
            sql, sql_q, sql_t = _count_queries(
                session,
                lambda m=mode: compute_maturity_aggregate_sql(session, attribution_mode=m),
            )
            legacy_report[mode] = {
                "legacy_runtime_sec": round(legacy_t, 4),
                "legacy_sql_queries": legacy_q,
                "sql_runtime_sec": round(sql_t, 4),
                "sql_queries": sql_q,
                "parity": {
                    "attributed": legacy.attributed_observation_count
                    == sql.attributed_observation_count,
                    "pending": legacy.pending_72h_count == sql.pending_72h_count,
                    "matured": legacy.matured_72h_count == sql.matured_72h_count,
                    "valid": legacy.valid_72h_outcome_count == sql.valid_72h_outcome_count,
                    "missing": legacy.missing_72h_outcome_count
                    == sql.missing_72h_outcome_count,
                    "next_6h": legacy.matures_next_6h == sql.matures_next_6h,
                    "next_24h": legacy.matures_next_24h == sql.matures_next_24h,
                    "next_48h": legacy.matures_next_48h == sql.matures_next_48h,
                },
                "legacy_counts": {
                    "attributed": legacy.attributed_observation_count,
                    "valid": legacy.valid_72h_outcome_count,
                    "missing": legacy.missing_72h_outcome_count,
                },
                "sql_counts": {
                    "attributed": sql.attributed_observation_count,
                    "valid": sql.valid_72h_outcome_count,
                    "missing": sql.missing_72h_outcome_count,
                },
            }
            if mode == "all_hits":
                legacy_report["legacy_phases_all_hits"] = _legacy_phases(session, "all_hits")

        dialect = _dialect(session)
        if dialect == "postgresql":
            params = {
                "now_ts": __import__(
                    "app.services.metrics",
                    fromlist=["utc_now"],
                ).utc_now(),
                "horizon_hours": 72,
                "tolerance_hours": 12,
                "win6": 6,
                "win24": 24,
                "win48": 48,
            }
            explain_combined = session.execute(
                text("EXPLAIN ANALYZE " + _combined_maturity_sql("all_hits", dialect)),
                params,
            ).all()
            legacy_report["explain_analyze"] = {
                "combined_maturity_all_hits": [row[0] for row in explain_combined],
            }

        print(json.dumps(legacy_report, indent=2))
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
