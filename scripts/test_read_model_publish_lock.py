"""Publish lock for read-model refresh (Stage 3)."""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.models.orm import AttentionRun, ReadModelPublishLock
from app.services.attention_engine_types import AttentionEngineConfig
from app.services.attention_read_model import load_attention_snapshot, refresh_attention_engine
from app.services.metrics import utc_now
from app.services.read_model_publish_lock import (
    PUBLISH_LOCK_ATTENTION,
    ReadModelPublishNotAuthorizedError,
    acquire_read_model_publish_lock,
    release_read_model_publish_lock,
)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_second_publisher_blocked() -> None:
    session = _session()
    first = acquire_read_model_publish_lock(session, kind=PUBLISH_LOCK_ATTENTION)
    assert first.acquired and first.token
    second = acquire_read_model_publish_lock(session, kind=PUBLISH_LOCK_ATTENTION)
    assert not second.acquired
    release_read_model_publish_lock(session, kind=PUBLISH_LOCK_ATTENTION, token=first.token)
    third = acquire_read_model_publish_lock(session, kind=PUBLISH_LOCK_ATTENTION)
    assert third.acquired and third.token != first.token


def test_stale_lock_recovery() -> None:
    session = _session()
    first = acquire_read_model_publish_lock(session, kind=PUBLISH_LOCK_ATTENTION)
    assert first.token
    row = session.get(ReadModelPublishLock, PUBLISH_LOCK_ATTENTION)
    assert row is not None
    row.lock_acquired_at = utc_now() - timedelta(hours=5)
    session.flush()
    recovered = acquire_read_model_publish_lock(
        session,
        kind=PUBLISH_LOCK_ATTENTION,
        stale_after_minutes=60,
    )
    assert recovered.acquired and recovered.token != first.token


def test_release_requires_matching_token() -> None:
    session = _session()
    first = acquire_read_model_publish_lock(session, kind=PUBLISH_LOCK_ATTENTION)
    assert first.token
    release_read_model_publish_lock(session, kind=PUBLISH_LOCK_ATTENTION, token="wrong")
    row = session.get(ReadModelPublishLock, PUBLISH_LOCK_ATTENTION)
    assert row is not None and row.lock_token == first.token
    release_read_model_publish_lock(session, kind=PUBLISH_LOCK_ATTENTION, token=first.token)
    assert row.lock_token is None


def test_publish_token_enforced() -> None:
    session = _session()
    lock = acquire_read_model_publish_lock(session, kind=PUBLISH_LOCK_ATTENTION)
    assert lock.token
    try:
        refresh_attention_engine(
            session,
            config=AttentionEngineConfig(),
            now=utc_now(),
            publish_token="invalid",
        )
        raise AssertionError("expected not authorized")
    except ReadModelPublishNotAuthorizedError:
        session.rollback()


def main() -> int:
    test_second_publisher_blocked()
    test_stale_lock_recovery()
    test_release_requires_matching_token()
    test_publish_token_enforced()
    print("OK read model publish lock")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
