"""Set-based 72h maturity aggregates for operations overview (Stage 1.19B1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.keyword_performance_evaluation import (
    HORIZON_HOURS,
    HORIZON_SNAPSHOT_TOLERANCE_HOURS,
)
from app.services.metrics import ensure_utc, utc_now

OutcomeAttributionMode = Literal["all_hits", "first_discovery"]


@dataclass
class MaturityAggregateResult:
    attribution_mode: OutcomeAttributionMode
    horizon_hours: int
    tolerance_hours: int
    attributed_observation_count: int = 0
    pending_72h_count: int = 0
    matured_72h_count: int = 0
    valid_72h_outcome_count: int = 0
    missing_72h_outcome_count: int = 0
    matures_next_6h: int = 0
    matures_next_24h: int = 0
    matures_next_48h: int = 0


def _dialect(session: Session) -> str:
    return session.get_bind().dialect.name


def _maturity_at_expr(dialect: str) -> str:
    if dialect == "postgresql":
        return "discovered_at + (:horizon_hours * INTERVAL '1 hour')"
    return "datetime(discovered_at, '+' || :horizon_hours || ' hours')"


def _snapshot_window_sql(dialect: str, maturity_ref: str) -> tuple[str, str]:
    if dialect == "postgresql":
        return (
            f"{maturity_ref} - (:tolerance_hours * INTERVAL '1 hour')",
            f"{maturity_ref} + (:tolerance_hours * INTERVAL '1 hour')",
        )
    return (
        f"julianday({maturity_ref}) - (:tolerance_hours / 24.0)",
        f"julianday({maturity_ref}) + (:tolerance_hours / 24.0)",
    )


def _abs_epoch_diff(dialect: str, left: str, right: str) -> str:
    if dialect == "postgresql":
        return f"ABS(EXTRACT(EPOCH FROM ({left} - {right})))"
    return f"ABS((julianday({left}) - julianday({right})) * 86400.0)"


_PAIR_FIRST_CTE = """
    pair_first AS (
        SELECT
            id,
            keyword_id,
            video_id,
            discovered_at,
            views_at_discovery,
            ROW_NUMBER() OVER (
                PARTITION BY keyword_id, video_id
                ORDER BY discovered_at ASC, id ASC
            ) AS pair_rn
        FROM keyword_discovery_hits
    ),
    pair_baselines AS (
        SELECT keyword_id, video_id, discovered_at, views_at_discovery
        FROM pair_first
        WHERE pair_rn = 1
    )
"""


def _annotated_cte(attribution_mode: OutcomeAttributionMode, dialect: str) -> str:
    maturity_at = _maturity_at_expr(dialect)
    if attribution_mode == "all_hits":
        return f"""
            WITH {_PAIR_FIRST_CTE},
            baselines AS (
                SELECT keyword_id, video_id, discovered_at, views_at_discovery
                FROM pair_baselines
            ),
            annotated AS (
                SELECT
                    keyword_id,
                    video_id,
                    discovered_at,
                    views_at_discovery,
                    {maturity_at} AS maturity_at
                FROM baselines
            )
        """
    return f"""
        WITH ranked_hits AS (
            SELECT
                id,
                keyword_id,
                video_id,
                discovered_at,
                views_at_discovery,
                ROW_NUMBER() OVER (
                    PARTITION BY keyword_id, video_id
                    ORDER BY discovered_at ASC, id ASC
                ) AS pair_rn,
                ROW_NUMBER() OVER (
                    PARTITION BY video_id
                    ORDER BY discovered_at ASC, keyword_id ASC
                ) AS owner_rn
            FROM keyword_discovery_hits
        ),
        baselines AS (
            SELECT keyword_id, video_id, discovered_at, views_at_discovery
            FROM ranked_hits
            WHERE pair_rn = 1 AND owner_rn = 1
        ),
        annotated AS (
            SELECT
                keyword_id,
                video_id,
                discovered_at,
                views_at_discovery,
                {maturity_at} AS maturity_at
            FROM baselines
        )
    """


def _aggregate_counts_sql(attribution_mode: OutcomeAttributionMode, dialect: str) -> str:
    base = _annotated_cte(attribution_mode, dialect)
    if dialect == "postgresql":
        return f"""
            {base}
            SELECT
                COUNT(*)::int AS attributed,
                COUNT(*) FILTER (WHERE maturity_at > :now_ts)::int AS pending,
                COUNT(*) FILTER (WHERE maturity_at <= :now_ts)::int AS matured,
                COUNT(*) FILTER (
                    WHERE maturity_at > :now_ts
                      AND maturity_at <= :now_ts + (:win6 * INTERVAL '1 hour')
                )::int AS matures_next_6h,
                COUNT(*) FILTER (
                    WHERE maturity_at > :now_ts
                      AND maturity_at <= :now_ts + (:win24 * INTERVAL '1 hour')
                )::int AS matures_next_24h,
                COUNT(*) FILTER (
                    WHERE maturity_at > :now_ts
                      AND maturity_at <= :now_ts + (:win48 * INTERVAL '1 hour')
                )::int AS matures_next_48h
            FROM annotated
        """
    return f"""
        {base}
        SELECT
            COUNT(*) AS attributed,
            SUM(CASE WHEN maturity_at > :now_ts THEN 1 ELSE 0 END) AS pending,
            SUM(CASE WHEN maturity_at <= :now_ts THEN 1 ELSE 0 END) AS matured,
            SUM(CASE WHEN maturity_at > :now_ts
                AND maturity_at <= datetime(:now_ts, '+' || :win6 || ' hours') THEN 1 ELSE 0 END)
                AS matures_next_6h,
            SUM(CASE WHEN maturity_at > :now_ts
                AND maturity_at <= datetime(:now_ts, '+' || :win24 || ' hours') THEN 1 ELSE 0 END)
                AS matures_next_24h,
            SUM(CASE WHEN maturity_at > :now_ts
                AND maturity_at <= datetime(:now_ts, '+' || :win48 || ' hours') THEN 1 ELSE 0 END)
                AS matures_next_48h
        FROM annotated
    """


def _valid_missing_sql(attribution_mode: OutcomeAttributionMode, dialect: str) -> str:
    base = _annotated_cte(attribution_mode, dialect)
    cap_from, cap_to = _snapshot_window_sql(dialect, "e.maturity_at")
    abs_diff = _abs_epoch_diff(dialect, "s.captured_at", "e.maturity_at")
    if dialect == "postgresql":
        snap_window = f"""
               AND s.captured_at >= {cap_from}
               AND s.captured_at <= {cap_to}
        """
    else:
        snap_window = f"""
               AND julianday(s.captured_at) >= {cap_from}
               AND julianday(s.captured_at) <= {cap_to}
        """
    return f"""
        {base},
        eligible AS (
            SELECT keyword_id, video_id, maturity_at
            FROM annotated
            WHERE maturity_at <= :now_ts
              AND views_at_discovery IS NOT NULL
        ),
        ranked_snaps AS (
            SELECT
                e.keyword_id,
                e.video_id,
                ROW_NUMBER() OVER (
                    PARTITION BY e.keyword_id, e.video_id
                    ORDER BY {abs_diff} ASC, s.captured_at ASC, s.id ASC
                ) AS snap_rn
            FROM eligible e
            INNER JOIN video_snapshots s
                ON s.video_id = e.video_id
               AND s.views IS NOT NULL
               {snap_window}
        ),
        matched AS (
            SELECT keyword_id, video_id
            FROM ranked_snaps
            WHERE snap_rn = 1
        )
        SELECT
            (SELECT COUNT(*) FROM eligible) AS eligible_count,
            (SELECT COUNT(*) FROM matched) AS valid_count
    """


def _combined_maturity_sql(attribution_mode: OutcomeAttributionMode, dialect: str) -> str:
    base = _annotated_cte(attribution_mode, dialect).rstrip()
    cap_from, cap_to = _snapshot_window_sql(dialect, "e.maturity_at")
    abs_diff = _abs_epoch_diff(dialect, "s.captured_at", "e.maturity_at")
    if dialect == "postgresql":
        snap_window = f"""
               AND s.captured_at >= {cap_from}
               AND s.captured_at <= {cap_to}
        """
        count_select = """
            COUNT(*)::int AS attributed,
            COUNT(*) FILTER (WHERE maturity_at > :now_ts)::int AS pending,
            COUNT(*) FILTER (WHERE maturity_at <= :now_ts)::int AS matured,
            COUNT(*) FILTER (
                WHERE maturity_at > :now_ts
                  AND maturity_at <= :now_ts + (:win6 * INTERVAL '1 hour')
            )::int AS matures_next_6h,
            COUNT(*) FILTER (
                WHERE maturity_at > :now_ts
                  AND maturity_at <= :now_ts + (:win24 * INTERVAL '1 hour')
            )::int AS matures_next_24h,
            COUNT(*) FILTER (
                WHERE maturity_at > :now_ts
                  AND maturity_at <= :now_ts + (:win48 * INTERVAL '1 hour')
            )::int AS matures_next_48h
        """
    else:
        snap_window = f"""
               AND julianday(s.captured_at) >= {cap_from}
               AND julianday(s.captured_at) <= {cap_to}
        """
        count_select = """
            COUNT(*) AS attributed,
            SUM(CASE WHEN maturity_at > :now_ts THEN 1 ELSE 0 END) AS pending,
            SUM(CASE WHEN maturity_at <= :now_ts THEN 1 ELSE 0 END) AS matured,
            SUM(CASE WHEN maturity_at > :now_ts
                AND maturity_at <= datetime(:now_ts, '+' || :win6 || ' hours') THEN 1 ELSE 0 END)
                AS matures_next_6h,
            SUM(CASE WHEN maturity_at > :now_ts
                AND maturity_at <= datetime(:now_ts, '+' || :win24 || ' hours') THEN 1 ELSE 0 END)
                AS matures_next_24h,
            SUM(CASE WHEN maturity_at > :now_ts
                AND maturity_at <= datetime(:now_ts, '+' || :win48 || ' hours') THEN 1 ELSE 0 END)
                AS matures_next_48h
        """
    return f"""
        {base},
        eligible AS (
            SELECT keyword_id, video_id, maturity_at
            FROM annotated
            WHERE maturity_at <= :now_ts
              AND views_at_discovery IS NOT NULL
        ),
        ranked_snaps AS (
            SELECT
                e.keyword_id,
                e.video_id,
                ROW_NUMBER() OVER (
                    PARTITION BY e.keyword_id, e.video_id
                    ORDER BY {abs_diff} ASC, s.captured_at ASC, s.id ASC
                ) AS snap_rn
            FROM eligible e
            INNER JOIN video_snapshots s
                ON s.video_id = e.video_id
               AND s.views IS NOT NULL
               {snap_window}
        ),
        matched AS (
            SELECT keyword_id, video_id
            FROM ranked_snaps
            WHERE snap_rn = 1
        )
        SELECT
            {count_select},
            (SELECT COUNT(*) FROM eligible) AS eligible_count,
            (SELECT COUNT(*) FROM matched) AS valid_count
        FROM annotated
    """


def _bind_params(reference: datetime) -> dict:
    return {
        "now_ts": ensure_utc(reference),
        "horizon_hours": HORIZON_HOURS,
        "tolerance_hours": HORIZON_SNAPSHOT_TOLERANCE_HOURS,
        "win6": 6,
        "win24": 24,
        "win48": 48,
    }


def compute_maturity_aggregate_sql(
    session: Session,
    *,
    attribution_mode: OutcomeAttributionMode = "all_hits",
    now: datetime | None = None,
) -> MaturityAggregateResult:
    reference = ensure_utc(now or utc_now())
    dialect = _dialect(session)
    params = _bind_params(reference)

    row = session.execute(
        text(_combined_maturity_sql(attribution_mode, dialect)),
        params,
    ).mappings().one()

    eligible = int(row["eligible_count"] or 0)
    valid = int(row["valid_count"] or 0)

    return MaturityAggregateResult(
        attribution_mode=attribution_mode,
        horizon_hours=HORIZON_HOURS,
        tolerance_hours=HORIZON_SNAPSHOT_TOLERANCE_HOURS,
        attributed_observation_count=int(row["attributed"] or 0),
        pending_72h_count=int(row["pending"] or 0),
        matured_72h_count=int(row["matured"] or 0),
        valid_72h_outcome_count=valid,
        missing_72h_outcome_count=int(row["matured"] or 0) - valid,
        matures_next_6h=int(row["matures_next_6h"] or 0),
        matures_next_24h=int(row["matures_next_24h"] or 0),
        matures_next_48h=int(row["matures_next_48h"] or 0),
    )
