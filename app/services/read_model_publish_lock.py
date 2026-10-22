"""Cross-process publish locks for read-model refresh (Stage 3)."""

from __future__ import annotations

import os
import socket
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.orm import Session

from app.models.orm import ReadModelPublishLock
from app.services.metrics import ensure_utc, utc_now

PUBLISH_LOCK_ATTENTION = "attention"
PUBLISH_LOCK_KEYWORD_PERFORMANCE = "keyword_performance"
DEFAULT_PUBLISH_STALE_MINUTES = 180


class ReadModelPublishBusyError(RuntimeError):
    def __init__(self, *, kind: str, holder: str | None, reason: str) -> None:
        super().__init__(f"read model publish lock busy: kind={kind} holder={holder} reason={reason}")
        self.kind = kind
        self.holder = holder
        self.reason = reason


class ReadModelPublishNotAuthorizedError(RuntimeError):
    def __init__(self, *, kind: str, token: str) -> None:
        super().__init__(f"read model publish not authorized: kind={kind} token={token[:8]}…")
        self.kind = kind
        self.token = token


@dataclass(frozen=True, slots=True)
class PublishLockResult:
    acquired: bool
    reason: str
    holder: str | None = None
    token: str | None = None


def publish_lock_diagnostics(*, kind: str) -> str:
    """Human-readable identity (hostname/kind/PID); not used for ownership equality."""
    return f"{socket.gethostname()}:{kind}:{os.getpid()}"


def _new_lock_token() -> str:
    return uuid.uuid4().hex


def _get_or_create_lock_row(session: Session, kind: str) -> ReadModelPublishLock:
    row = session.get(ReadModelPublishLock, kind)
    if row is not None:
        return row
    row = ReadModelPublishLock(kind=kind)
    session.add(row)
    session.flush()
    return row


def acquire_read_model_publish_lock(
    session: Session,
    *,
    kind: str,
    holder: str | None = None,
    stale_after_minutes: int = DEFAULT_PUBLISH_STALE_MINUTES,
) -> PublishLockResult:
    diagnostics = holder or publish_lock_diagnostics(kind=kind)
    row = _get_or_create_lock_row(session, kind)
    now = utc_now()

    if row.lock_token is not None and row.lock_acquired_at is not None:
        age = now - ensure_utc(row.lock_acquired_at)
        if age <= timedelta(minutes=stale_after_minutes):
            return PublishLockResult(
                acquired=False,
                reason="lock_held",
                holder=row.lock_holder,
                token=None,
            )

    token = _new_lock_token()
    row.lock_holder = diagnostics
    row.lock_token = token
    row.lock_acquired_at = now
    row.updated_at = now
    session.flush()
    return PublishLockResult(acquired=True, reason="acquired", holder=diagnostics, token=token)


def assert_publish_lock_token(session: Session, *, kind: str, token: str) -> None:
    """
    Verify this run still owns the lock immediately before mutating read-model rows.

    Uses row lock (SELECT FOR UPDATE) in the current transaction so takeover cannot
    slip in between check and publish commit.
    """
    row = session.get(ReadModelPublishLock, kind, with_for_update=True)
    if row is None or row.lock_token != token:
        raise ReadModelPublishNotAuthorizedError(kind=kind, token=token)


def release_read_model_publish_lock(session: Session, *, kind: str, token: str) -> None:
    row = session.get(ReadModelPublishLock, kind)
    if row is None or row.lock_token != token:
        return
    row.lock_holder = None
    row.lock_token = None
    row.lock_acquired_at = None
    row.updated_at = utc_now()
    session.flush()


@contextmanager
def read_model_publish_guard(
    session: Session,
    *,
    kind: str,
    holder: str | None = None,
    stale_after_minutes: int = DEFAULT_PUBLISH_STALE_MINUTES,
):
    result = acquire_read_model_publish_lock(
        session,
        kind=kind,
        holder=holder,
        stale_after_minutes=stale_after_minutes,
    )
    if not result.acquired or result.token is None:
        raise ReadModelPublishBusyError(kind=kind, holder=result.holder, reason=result.reason)
    resolved_token = result.token
    try:
        yield result
    finally:
        release_read_model_publish_lock(session, kind=kind, token=resolved_token)
