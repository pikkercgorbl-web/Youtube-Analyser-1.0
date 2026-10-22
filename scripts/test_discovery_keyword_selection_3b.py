"""Fix 3B — discovery keyword selection source priority."""

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
from app.services.discovery_keyword_selection import select_discovery_keywords
from app.services.keyword_scheduling_policy import LIFECYCLE_PROBATION, SOURCE_SEED, SOURCE_SUGGESTION

UTC = timezone.utc


def _session():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _now() -> datetime:
    return datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


def test_seed_selected_before_suggestion_when_same_overdue() -> None:
    session = _session()
    now = _now()
    due_at = now - timedelta(hours=2)
    session.add_all(
        [
            TargetKeyword(
                keyword="suggestion-kw",
                lifecycle_status=LIFECYCLE_PROBATION,
                source_type=SOURCE_SUGGESTION,
                next_scan_at=due_at,
            ),
            TargetKeyword(
                keyword="seed-kw",
                lifecycle_status=LIFECYCLE_PROBATION,
                source_type=SOURCE_SEED,
                next_scan_at=due_at,
            ),
        ],
    )
    session.commit()
    batch = select_discovery_keywords(session, batch_size=1, now=now)
    assert len(batch) == 1
    assert batch[0].source_type == SOURCE_SEED


def test_large_probation_queue_respects_overdue_first() -> None:
    session = _session()
    now = _now()
    for i in range(50):
        session.add(
            TargetKeyword(
                keyword=f"sugg-{i}",
                lifecycle_status=LIFECYCLE_PROBATION,
                source_type=SOURCE_SUGGESTION,
                next_scan_at=now - timedelta(hours=1),
            ),
        )
    session.add(
        TargetKeyword(
            keyword="very-late",
            lifecycle_status=LIFECYCLE_PROBATION,
            source_type=SOURCE_SUGGESTION,
            next_scan_at=now - timedelta(days=3),
        ),
    )
    session.commit()
    batch = select_discovery_keywords(session, batch_size=1, now=now)
    assert batch[0].keyword == "very-late"


if __name__ == "__main__":
    test_seed_selected_before_suggestion_when_same_overdue()
    test_large_probation_queue_respects_overdue_first()
    print("ok")
