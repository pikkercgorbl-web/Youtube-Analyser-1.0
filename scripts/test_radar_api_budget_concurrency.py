"""PostgreSQL concurrency tests for Radar API budget ledger (Stage 2)."""

from __future__ import annotations

import os
import sys
import threading
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _test_url() -> str:
    url = os.environ.get("RADAR_BUDGET_POSTGRES_TEST_URL", "").strip()
    if not url:
        url = os.environ.get("SAVED_TOPICS_POSTGRES_TEST_URL", "").strip()
    if not url or "postgresql" not in url.lower():
        raise SystemExit("Set RADAR_BUDGET_POSTGRES_TEST_URL to a dedicated PostgreSQL test database.")
    if "restore_check" in url.lower() and os.environ.get("RADAR_BUDGET_ALLOW_RESTORE") != "1":
        raise SystemExit("Refusing restore_check; use a dedicated test DB or RADAR_BUDGET_ALLOW_RESTORE=1.")
    return url


def _setup_schema(engine) -> None:
    from app.models.orm import Base

    Base.metadata.create_all(engine, tables=[Base.metadata.tables["radar_api_budget_daily"]])


def test_concurrent_last_slots() -> None:
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.models.orm import RadarApiBudgetDay
    from app.services.radar_api_budget import BUDGET_KIND_VIDEOS_LIST, try_reserve_id_units

    engine = create_engine(_test_url(), pool_pre_ping=True)
    _setup_schema(engine)
    Session = sessionmaker(bind=engine)
    day = date(2099, 1, 2)
    kind = BUDGET_KIND_VIDEOS_LIST + "_concurrent_test"

    setup = Session()
    try:
        setup.query(RadarApiBudgetDay).filter(
            RadarApiBudgetDay.budget_kind == kind,
            RadarApiBudgetDay.utc_day == day,
        ).delete()
        setup.add(
            RadarApiBudgetDay(
                budget_kind=kind,
                utc_day=day,
                id_units_reserved=98,
                http_requests=0,
            ),
        )
        setup.commit()
    finally:
        setup.close()

    results: list[int] = []
    lock = threading.Lock()

    def worker(request: int) -> None:
        session = Session()
        try:
            now = datetime(2099, 1, 2, 12, 0, tzinfo=timezone.utc)
            r = try_reserve_id_units(
                session,
                budget_kind=kind,
                unit_count=request,
                daily_limit=100,
                now=now,
            )
            session.commit()
            with lock:
                results.append(r.reserved)
        finally:
            session.close()

    t1 = threading.Thread(target=worker, args=(5,))
    t2 = threading.Thread(target=worker, args=(5,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert sum(results) == 2, results
    verify = Session()
    try:
        row = verify.get(RadarApiBudgetDay, {"budget_kind": kind, "utc_day": day})
        assert row is not None
        assert int(row.id_units_reserved) == 100
    finally:
        verify.close()


def test_race_create_day_row() -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models.orm import RadarApiBudgetDay
    from app.services.radar_api_budget import BUDGET_KIND_CHANNELS_LIST, try_reserve_id_units

    engine = create_engine(_test_url(), pool_pre_ping=True)
    _setup_schema(engine)
    Session = sessionmaker(bind=engine)
    day = date(2099, 1, 3)
    kind = BUDGET_KIND_CHANNELS_LIST + "_race_day"

    setup = Session()
    try:
        setup.query(RadarApiBudgetDay).filter(
            RadarApiBudgetDay.budget_kind == kind,
            RadarApiBudgetDay.utc_day == day,
        ).delete()
        setup.commit()
    finally:
        setup.close()

    reserved_sum: list[int] = []

    def worker() -> None:
        session = Session()
        try:
            now = datetime(2099, 1, 3, 8, 0, tzinfo=timezone.utc)
            r = try_reserve_id_units(session, budget_kind=kind, unit_count=3, daily_limit=10, now=now)
            session.commit()
            reserved_sum.append(r.reserved)
        finally:
            session.close()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(reserved_sum) == 10
    verify = Session()
    try:
        row = verify.get(RadarApiBudgetDay, {"budget_kind": kind, "utc_day": day})
        assert row is not None
        assert int(row.id_units_reserved) == 10
    finally:
        verify.close()


def test_concurrent_http_increment() -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models.orm import RadarApiBudgetDay
    from app.services.radar_api_budget import BUDGET_KIND_CHANNELS_LIST, record_http_requests

    engine = create_engine(_test_url(), pool_pre_ping=True)
    _setup_schema(engine)
    Session = sessionmaker(bind=engine)
    day = date(2099, 1, 4)
    kind = BUDGET_KIND_CHANNELS_LIST + "_http"

    setup = Session()
    try:
        setup.query(RadarApiBudgetDay).filter(
            RadarApiBudgetDay.budget_kind == kind,
            RadarApiBudgetDay.utc_day == day,
        ).delete()
        setup.add(
            RadarApiBudgetDay(budget_kind=kind, utc_day=day, id_units_reserved=0, http_requests=0),
        )
        setup.commit()
    finally:
        setup.close()

    def bump() -> None:
        session = Session()
        try:
            record_http_requests(
                session,
                budget_kind=kind,
                request_count=1,
                now=datetime(2099, 1, 4, 9, 0, tzinfo=timezone.utc),
            )
            session.commit()
        finally:
            session.close()

    threads = [threading.Thread(target=bump) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    verify = Session()
    try:
        row = verify.get(RadarApiBudgetDay, {"budget_kind": kind, "utc_day": day})
        assert row is not None
        assert int(row.http_requests) == 20
    finally:
        verify.close()


def test_dry_run_read_does_not_insert() -> None:
    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import sessionmaker

    from app.models.orm import RadarApiBudgetDay
    from app.services.radar_api_budget import (
        BUDGET_KIND_VIDEOS_LIST,
        count_budget_rows,
        read_budget_day,
        remaining_id_units,
    )

    engine = create_engine(_test_url(), pool_pre_ping=True)
    _setup_schema(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        before = count_budget_rows(session)
        now = datetime(2099, 6, 1, 0, 0, tzinfo=timezone.utc)
        snap = read_budget_day(session, budget_kind=BUDGET_KIND_VIDEOS_LIST, now=now)
        assert snap.id_units_reserved == 0
        assert remaining_id_units(session, budget_kind=BUDGET_KIND_VIDEOS_LIST, daily_limit=100, now=now) == 100
        session.flush()
        after = count_budget_rows(session)
        assert after == before
    finally:
        session.close()


def test_reservation_survives_processing_failure() -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models.orm import RadarApiBudgetDay
    from app.services.radar_api_budget import BUDGET_KIND_VIDEOS_LIST, try_reserve_id_units

    engine = create_engine(_test_url(), pool_pre_ping=True)
    _setup_schema(engine)
    Session = sessionmaker(bind=engine)
    day = date(2099, 1, 5)
    kind = BUDGET_KIND_VIDEOS_LIST + "_fail"

    session = Session()
    try:
        session.query(RadarApiBudgetDay).filter(
            RadarApiBudgetDay.budget_kind == kind,
            RadarApiBudgetDay.utc_day == day,
        ).delete()
        session.commit()
        now = datetime(2099, 1, 5, 10, 0, tzinfo=timezone.utc)
        r = try_reserve_id_units(session, budget_kind=kind, unit_count=4, daily_limit=50, now=now)
        session.commit()
        assert r.reserved == 4
        session.rollback()
        row = session.get(RadarApiBudgetDay, {"budget_kind": kind, "utc_day": day})
        assert row is not None
        assert int(row.id_units_reserved) == 4
    finally:
        session.close()


def main() -> int:
    test_concurrent_last_slots()
    test_race_create_day_row()
    test_concurrent_http_increment()
    test_dry_run_read_does_not_insert()
    test_reservation_survives_processing_failure()
    print("OK radar API budget concurrency (PostgreSQL)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
