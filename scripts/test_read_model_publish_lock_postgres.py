"""PostgreSQL regression tests for read_model_publish_lock (Stage 3 acceptance)."""

from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _test_url() -> str:
    url = os.environ.get("SAVED_TOPICS_POSTGRES_TEST_URL", "").strip()
    if not url or "postgresql" not in url.lower():
        raise SystemExit("Set SAVED_TOPICS_POSTGRES_TEST_URL to a dedicated PostgreSQL test database.")
    prod = os.environ.get("DATABASE_URL", "").strip()
    if prod and prod.rstrip("/") == url.rstrip("/"):
        raise SystemExit("Test URL must not equal DATABASE_URL")
    if "restore_check" in url.lower() and os.environ.get("ALLOW_RESTORE_CHECK_INTEGRATION") != "1":
        raise SystemExit("Refusing restore_check without ALLOW_RESTORE_CHECK_INTEGRATION=1.")
    return url


def _sessions():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.migrations import run_startup_migrations
    from app.models.db import Base

    engine = create_engine(_test_url(), pool_pre_ping=True)
    run_startup_migrations(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    return factory(), factory(), engine


def test_concurrent_second_publisher_blocked() -> None:
    from app.services.read_model_publish_lock import (
        PUBLISH_LOCK_ATTENTION,
        acquire_read_model_publish_lock,
        release_read_model_publish_lock,
    )

    s1, s2, _ = _sessions()
    try:
        first = acquire_read_model_publish_lock(s1, kind=PUBLISH_LOCK_ATTENTION)
        assert first.acquired and first.token
        s1.commit()
        second = acquire_read_model_publish_lock(s2, kind=PUBLISH_LOCK_ATTENTION)
        assert not second.acquired and second.reason == "lock_held"
        release_read_model_publish_lock(s1, kind=PUBLISH_LOCK_ATTENTION, token=first.token)
        s1.commit()
    finally:
        s1.close()
        s2.close()


def test_stale_takeover_same_hostname_old_publish_blocked() -> None:
    """A and B use default identity; after stale takeover B owns lock; A publish with stale token fails."""
    from sqlalchemy import func, select

    from app.models.orm import ReadModelPublishLock, SavedTopicObservation
    from app.services.attention_engine_types import AttentionEngineConfig
    from app.services.attention_read_model import load_attention_snapshot, refresh_attention_engine
    from app.services.metrics import utc_now
    from app.services.read_model_publish_lock import (
        PUBLISH_LOCK_ATTENTION,
        ReadModelPublishNotAuthorizedError,
        acquire_read_model_publish_lock,
        release_read_model_publish_lock,
    )

    s_a, s_b, _ = _sessions()
    try:
        refresh_attention_engine(s_a, config=AttentionEngineConfig(), now=utc_now())
        s_a.commit()
        run_before = load_attention_snapshot(s_a).summary.run_id
        obs_before = s_a.scalar(select(func.count()).select_from(SavedTopicObservation)) or 0

        lock_a = acquire_read_model_publish_lock(s_a, kind=PUBLISH_LOCK_ATTENTION)
        assert lock_a.acquired and lock_a.token
        s_a.commit()

        row = s_a.get(ReadModelPublishLock, PUBLISH_LOCK_ATTENTION)
        assert row is not None
        row.lock_acquired_at = utc_now() - timedelta(hours=5)
        s_a.commit()

        lock_b = acquire_read_model_publish_lock(
            s_b,
            kind=PUBLISH_LOCK_ATTENTION,
            stale_after_minutes=60,
        )
        assert lock_b.acquired and lock_b.token and lock_b.token != lock_a.token
        s_b.commit()

        try:
            refresh_attention_engine(
                s_a,
                config=AttentionEngineConfig(),
                now=utc_now() + timedelta(minutes=2),
                publish_token=lock_a.token,
            )
            s_a.commit()
            raise AssertionError("stale token must not publish")
        except ReadModelPublishNotAuthorizedError:
            s_a.rollback()

        assert load_attention_snapshot(s_a).summary.run_id == run_before
        obs_after = s_a.scalar(select(func.count()).select_from(SavedTopicObservation)) or 0
        assert obs_after == obs_before

        release_read_model_publish_lock(s_a, kind=PUBLISH_LOCK_ATTENTION, token=lock_a.token)
        s_a.commit()
        s_b.expire_all()
        row_b = s_b.get(ReadModelPublishLock, PUBLISH_LOCK_ATTENTION)
        assert row_b is not None and row_b.lock_token == lock_b.token

        refresh_attention_engine(
            s_b,
            config=AttentionEngineConfig(),
            now=utc_now() + timedelta(minutes=3),
            publish_token=lock_b.token,
        )
        s_b.commit()
        run_after = load_attention_snapshot(s_b).summary.run_id
        assert run_after != run_before

        release_read_model_publish_lock(s_b, kind=PUBLISH_LOCK_ATTENTION, token=lock_b.token)
        s_b.commit()
        assert s_b.get(ReadModelPublishLock, PUBLISH_LOCK_ATTENTION).lock_token is None
    finally:
        s_a.close()
        s_b.close()


def test_failed_publish_preserves_attention_snapshot_and_observations() -> None:
    from sqlalchemy import func, select

    from app.models.orm import AttentionRun, SavedTopicObservation
    from app.services.attention_engine_types import AttentionEngineConfig
    from app.services.attention_read_model import load_attention_snapshot, refresh_attention_engine
    from app.services.metrics import utc_now
    from app.services.read_model_publish_lock import (
        PUBLISH_LOCK_ATTENTION,
        acquire_read_model_publish_lock,
        release_read_model_publish_lock,
    )

    session, _, _ = _sessions()
    try:
        refresh_attention_engine(session, config=AttentionEngineConfig(), now=utc_now())
        session.commit()
        before = load_attention_snapshot(session)
        assert before is not None
        run_before = before.summary.run_id
        obs_before = session.scalar(select(func.count()).select_from(SavedTopicObservation)) or 0

        lock = acquire_read_model_publish_lock(session, kind=PUBLISH_LOCK_ATTENTION)
        assert lock.token
        session.commit()
        try:
            with patch(
                "app.services.attention_read_model.persist_attention_result",
                side_effect=RuntimeError("simulated publish failure"),
            ):
                try:
                    refresh_attention_engine(
                        session,
                        config=AttentionEngineConfig(),
                        now=utc_now(),
                        publish_token=lock.token,
                    )
                    session.commit()
                except RuntimeError:
                    session.rollback()
        finally:
            release_read_model_publish_lock(session, kind=PUBLISH_LOCK_ATTENTION, token=lock.token)
            session.commit()

        after = load_attention_snapshot(session)
        assert after is not None
        assert after.summary.run_id == run_before
        assert session.scalar(select(AttentionRun).where(AttentionRun.run_id == run_before)) is not None
        obs_after = session.scalar(select(func.count()).select_from(SavedTopicObservation)) or 0
        assert obs_after == obs_before
    finally:
        session.close()


def main() -> int:
    test_concurrent_second_publisher_blocked()
    test_stale_takeover_same_hostname_old_publish_blocked()
    test_failed_publish_preserves_attention_snapshot_and_observations()
    print("OK read model publish lock postgres")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
