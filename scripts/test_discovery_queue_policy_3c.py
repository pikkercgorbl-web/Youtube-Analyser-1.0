"""Fix 3C — discovery queue policy and tiered selection."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.models.orm import TargetKeyword
from app.services.discovery_keyword_selection import (
    select_discovery_keywords,
    select_discovery_keywords_legacy,
)
from app.services.discovery_queue_policy import (
    effective_probation_interval_hours,
    estimate_daily_keyword_slots,
    priority_reserved_slots,
    probation_keyword_slots_per_day,
    resolve_selector_keyword_batch_size,
)
from app.services.discovery_keyword_selection import select_discovery_keywords
from app.services.keyword_scheduling_policy import (
    LIFECYCLE_ACTIVE,
    LIFECYCLE_PROBATION,
    SOURCE_SEED,
    SOURCE_SUGGESTION,
)

UTC = timezone.utc


def _session():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _now() -> datetime:
    return datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


def test_daily_slot_estimate() -> None:
    slots = estimate_daily_keyword_slots(batch_size=5, interval_seconds=300)
    assert slots == 1440.0


def test_selector_batch_four_when_exploration_on() -> None:
    assert (
        resolve_selector_keyword_batch_size(
            worker_keyword_batch_size=5,
            exploration_enabled=True,
            exploration_fraction=0.2,
        )
        == 4
    )


def test_probation_interval_uses_measured_scale_not_864() -> None:
    # Observed ~724 scan-runs / 181 cycles → batch 4; general structural 2×186≈372/day.
    structural = probation_keyword_slots_per_day(batch_size=4, cycles_per_day=186.0)
    assert structural == 372.0
    assert effective_probation_interval_hours(probation_due_count=0, probation_slots_per_day=372) == 6.0
    hours = effective_probation_interval_hours(
        probation_due_count=1610,
        probation_slots_per_day=372.0,
    )
    assert 100.0 < hours < 110.0


def test_four_keyword_slots_two_priority_max() -> None:
    session = _session()
    now = _now()
    for i in range(4):
        session.add(
            TargetKeyword(
                keyword=f"seed-{i}",
                lifecycle_status=LIFECYCLE_ACTIVE,
                source_type=SOURCE_SEED,
                next_scan_at=now - timedelta(hours=5 + i),
            ),
        )
    for i in range(5):
        session.add(
            TargetKeyword(
                keyword=f"prob-{i}",
                lifecycle_status=LIFECYCLE_PROBATION,
                source_type=SOURCE_SUGGESTION,
                next_scan_at=now - timedelta(hours=1),
            ),
        )
    session.commit()
    batch = select_discovery_keywords(session, batch_size=4, now=now)
    assert len(batch) == 4
    priority_n = sum(1 for r in batch if r.source_type == SOURCE_SEED)
    assert priority_n == 2
    assert sum(1 for r in batch if r.lifecycle_status == LIFECYCLE_PROBATION) == 2


def test_unused_priority_slots_spill_to_general() -> None:
    session = _session()
    now = _now()
    session.add(
        TargetKeyword(
            keyword="only-seed",
            lifecycle_status=LIFECYCLE_ACTIVE,
            source_type=SOURCE_SEED,
            next_scan_at=now - timedelta(hours=10),
        ),
    )
    for i in range(6):
        session.add(
            TargetKeyword(
                keyword=f"p-{i}",
                lifecycle_status=LIFECYCLE_PROBATION,
                source_type=SOURCE_SUGGESTION,
                next_scan_at=now - timedelta(hours=1),
            ),
        )
    session.commit()
    batch = select_discovery_keywords(session, batch_size=5, now=now)
    assert len(batch) == 5
    assert batch[0].keyword == "only-seed"
    assert sum(1 for r in batch if r.lifecycle_status == LIFECYCLE_PROBATION) == 4


def test_seed_wins_over_heavier_overdue_suggestion() -> None:
    session = _session()
    now = _now()
    session.add_all(
        [
            TargetKeyword(
                keyword="sugg-old",
                lifecycle_status=LIFECYCLE_PROBATION,
                source_type=SOURCE_SUGGESTION,
                next_scan_at=now - timedelta(hours=50),
            ),
            TargetKeyword(
                keyword="seed-active",
                lifecycle_status=LIFECYCLE_ACTIVE,
                source_type=SOURCE_SEED,
                next_scan_at=now - timedelta(hours=39),
            ),
        ],
    )
    session.commit()
    legacy = select_discovery_keywords_legacy(session, batch_size=1, now=now)
    assert legacy[0].keyword == "sugg-old"
    batch = select_discovery_keywords(session, batch_size=2, now=now)
    assert batch[0].keyword == "seed-active"
    assert len(batch) == 2


def test_never_scanned_probation_gets_general_slot() -> None:
    session = _session()
    now = _now()
    for i in range(8):
        session.add(
            TargetKeyword(
                keyword=f"old-{i}",
                lifecycle_status=LIFECYCLE_PROBATION,
                source_type=SOURCE_SUGGESTION,
                next_scan_at=now - timedelta(hours=2),
                last_checked=now - timedelta(days=1),
            ),
        )
    session.add(
        TargetKeyword(
            keyword="new-probation",
            lifecycle_status=LIFECYCLE_PROBATION,
            source_type=SOURCE_SUGGESTION,
            next_scan_at=now - timedelta(minutes=30),
            last_checked=None,
        ),
    )
    session.commit()
    batch = select_discovery_keywords(session, batch_size=3, now=now)
    keywords = {row.keyword for row in batch}
    assert "new-probation" in keywords


def test_reserved_slots_count() -> None:
    assert priority_reserved_slots(5) == 2
    assert priority_reserved_slots(1) == 1


if __name__ == "__main__":
    test_daily_slot_estimate()
    test_selector_batch_four_when_exploration_on()
    test_probation_interval_uses_measured_scale_not_864()
    test_four_keyword_slots_two_priority_max()
    test_unused_priority_slots_spill_to_general()
    test_seed_wins_over_heavier_overdue_suggestion()
    test_never_scanned_probation_gets_general_slot()
    test_reserved_slots_count()
    print("ok")
