"""Materialize keyword performance read model (Stage 1.20E.4)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import load_dotenv

from app.db.migrations import run_startup_migrations
from app.models.db import SessionLocal, engine
from app.services.keyword_performance_read_model import refresh_keyword_performance_read_model
from app.services.read_model_publish_lock import (
    PUBLISH_LOCK_KEYWORD_PERFORMANCE,
    ReadModelPublishBusyError,
    ReadModelPublishNotAuthorizedError,
    acquire_read_model_publish_lock,
    release_read_model_publish_lock,
)


def main() -> int:
    load_dotenv(ROOT / ".env")
    run_startup_migrations(engine)
    session = SessionLocal()
    try:
        lock = acquire_read_model_publish_lock(session, kind=PUBLISH_LOCK_KEYWORD_PERFORMANCE)
        if not lock.acquired:
            raise ReadModelPublishBusyError(
                kind=PUBLISH_LOCK_KEYWORD_PERFORMANCE,
                holder=lock.holder,
                reason=lock.reason,
            )
        session.commit()
        assert lock.token is not None
        publish_token = lock.token
        try:
            run_id, rows = refresh_keyword_performance_read_model(session, publish_token=publish_token)
            session.commit()
            print(f"keyword_performance_read_model run_id={run_id} rows={rows}")
        except Exception:
            session.rollback()
            raise
        finally:
            release_read_model_publish_lock(session, kind=PUBLISH_LOCK_KEYWORD_PERFORMANCE, token=publish_token)
            session.commit()
    except (ReadModelPublishBusyError, ReadModelPublishNotAuthorizedError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
