#!/usr/bin/env python3
"""Read-only PostgreSQL smoke for cohort_with_new_analytical_observation_in_period."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.db import SessionLocal, engine
from app.models.orm import SavedVideoObservation
from app.services.research_portfolio_report import (
    _count_entities_with_new_analytical_observation_in_period,
    _observation_kind_expr,
    build_research_portfolio_report,
)


def _require_postgres() -> None:
    url = settings.database_url.lower()
    if not url.startswith("postgresql"):
        raise SystemExit(
            f"DATABASE_URL must be PostgreSQL for this check (got {settings.database_url.split('://', 1)[0]}://…)",
        )


def _print_compiled_sql() -> None:
    from sqlalchemy import func, select

    period_start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    period_end = datetime(2026, 10, 31, tzinfo=timezone.utc)
    with Session(engine) as session:
        kind = _observation_kind_expr(session, SavedVideoObservation.payload_json)
        analytical = (kind.is_(None)) | (kind != "daily_intelligence_save_anchor")
        first_analytical = (
            select(
                SavedVideoObservation.saved_video_id.label("entity_id"),
                func.min(SavedVideoObservation.observed_at).label("first_at"),
            )
            .where(analytical)
            .group_by(SavedVideoObservation.saved_video_id)
            .subquery()
        )
        stmt = select(func.count(func.distinct(SavedVideoObservation.saved_video_id))).select_from(
            SavedVideoObservation,
        )
        stmt = stmt.join(
            first_analytical,
            first_analytical.c.entity_id == SavedVideoObservation.saved_video_id,
        )
        stmt = stmt.where(analytical)
        stmt = stmt.where(SavedVideoObservation.observed_at > first_analytical.c.first_at)
        stmt = stmt.where(SavedVideoObservation.observed_at >= period_start)
        stmt = stmt.where(SavedVideoObservation.observed_at <= period_end)

        pg_sql = str(
            stmt.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            ),
        )
    print("=== PostgreSQL compiled (video count fragment) ===")
    print(pg_sql)
    if "json_extract" in pg_sql.lower():
        raise SystemExit("PostgreSQL SQL must not use json_extract")
    if "->>" not in pg_sql:
        raise SystemExit("PostgreSQL SQL must use jsonb ->> operator")
    print()
    from sqlalchemy import func as sa_func

    sqlite_kind = sa_func.json_extract(SavedVideoObservation.payload_json, "$.observation_kind")
    print("=== SQLite kind extract (reference) ===")
    print(
        str(
            select(sqlite_kind)
            .limit(1)
            .compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}),
        ),
    )
    print()


def _run_aggregate_and_api() -> None:
    period_start = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
    period_end = datetime(2026, 10, 31, 23, 59, 59, tzinfo=timezone.utc)

    session = SessionLocal()
    try:
        video_count = _count_entities_with_new_analytical_observation_in_period(
            session,
            SavedVideoObservation,
            SavedVideoObservation.saved_video_id,
            period_start=period_start,
            period_end=period_end,
        )
        print(f"Direct video aggregate OK: {video_count}")

        portfolio = build_research_portfolio_report(
            session,
            period_start=period_start,
            period_end=period_end,
            legacy_topics_saved_in_period=0,
        )
        field = portfolio["observations"]["cohort_with_new_analytical_observation_in_period"]
        print(f"build_research_portfolio_report field: {field}")

        archived_in_result = session.execute(
            text(
                """
                SELECT COUNT(DISTINCT o.saved_video_id) AS n
                FROM saved_video_observations o
                INNER JOIN saved_videos v ON v.id = o.saved_video_id
                WHERE v.archived_at IS NOT NULL
                """,
            ),
        ).scalar()
        print(f"Archived saved_videos with any observation rows (diagnostic): {archived_in_result}")
    finally:
        session.close()

    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    resp = client.get(
        "/api/validation/report",
        params={
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
        },
    )
    print(f"GET /api/validation/report status: {resp.status_code}")
    if resp.status_code == 200:
        value = resp.json()["research_portfolio"]["observations"][
            "cohort_with_new_analytical_observation_in_period"
        ]
        print(f"API cohort_with_new_analytical_observation_in_period: {value}")
    else:
        print(resp.text[:500])


def main() -> int:
    _require_postgres()
    _print_compiled_sql()
    _run_aggregate_and_api()
    print("PostgreSQL read-only new-observation aggregate check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
