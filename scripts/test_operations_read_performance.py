"""Read-path performance guards for operations/monitoring APIs."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from datetime import datetime, timezone

from app.models.db import Base
from app.models.orm import MonitoringCycleRun
from app.services.monitoring_api_service import get_monitoring_overview
from app.services.operations_overview_service import build_operations_overview


def _memory_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_operations_overview_does_not_run_outcome_planner_by_default() -> None:
    session = _memory_session()
    with patch(
        "app.services.operations_overview_service.plan_delayed_outcome_capture",
    ) as mocked:
        build_operations_overview(session)
        mocked.assert_not_called()


def test_monitoring_overview_uses_cycle_without_live_planner() -> None:
    session = _memory_session()
    now = datetime.now(timezone.utc)
    session.add(
        MonitoringCycleRun(
            run_id="m1",
            started_at=now,
            finished_at=now,
            runtime_seconds=1.0,
            cycle_status="ok",
            loaded_video_count=10,
            eligible_video_count=8,
            tier_a_count=3,
            tier_b_count=3,
            tier_c_count=2,
            due_count=1,
            overdue_count=0,
        ),
    )
    session.commit()
    with patch(
        "app.services.monitoring_api_service.build_active_monitoring_enriched",
    ) as mocked:
        get_monitoring_overview(session, live_planner=False)
        mocked.assert_not_called()


def test_operations_overview_sql_query_count_bounded_in_memory() -> None:
    session = _memory_session()
    count = {"n": 0}

    def before(_c, _cursor, _stmt, *_a, **_k) -> None:
        count["n"] += 1

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", before)
    try:
        build_operations_overview(session)
    finally:
        event.remove(engine, "before_cursor_execute", before)
    assert count["n"] < 50


def main() -> None:
    test_operations_overview_does_not_run_outcome_planner_by_default()
    test_monitoring_overview_uses_cycle_without_live_planner()
    test_operations_overview_sql_query_count_bounded_in_memory()
    print("All operations read performance tests passed.")


if __name__ == "__main__":
    main()
