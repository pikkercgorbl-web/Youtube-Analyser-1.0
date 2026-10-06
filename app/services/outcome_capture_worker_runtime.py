"""Continuous delayed outcome capture worker loop (Stage 1.20E.2)."""

from __future__ import annotations

import logging
import signal
import time
from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from app.services.delayed_outcome_capture_config import (
    DEFAULT_OUTCOME_CAPTURE_ERROR_BACKOFF_SECONDS,
    DEFAULT_OUTCOME_CAPTURE_INTERVAL_SECONDS,
)
from app.services.delayed_outcome_capture_cycle import (
    DelayedOutcomeCaptureCycleSummary,
    run_delayed_outcome_capture_cycle,
)
from app.services.metrics import utc_now
from app.services.outcome_capture_worker_lock import (
    acquire_outcome_capture_worker_lock,
    clear_outcome_capture_worker_stop,
    record_outcome_capture_cycle_finish,
    record_outcome_capture_worker_heartbeat,
    release_outcome_capture_worker_lock,
)
from app.services.revisit_executor import VideoBatchFetchClient

logger = logging.getLogger(__name__)


@dataclass
class OutcomeCaptureWorkerConfig:
    interval_seconds: int = DEFAULT_OUTCOME_CAPTURE_INTERVAL_SECONDS
    error_backoff_seconds: int = DEFAULT_OUTCOME_CAPTURE_ERROR_BACKOFF_SECONDS
    stale_lock_minutes: int = 90


def run_outcome_capture_worker_loop(
    session_factory: Callable[[], Session],
    youtube_client: VideoBatchFetchClient,
    *,
    config: OutcomeCaptureWorkerConfig | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    stop_check: Callable[[], bool] | None = None,
    lock_holder: str | None = None,
) -> None:
    cfg = config or OutcomeCaptureWorkerConfig()
    stop_requested = False

    def _handle_signal(signum, _frame) -> None:
        nonlocal stop_requested
        stop_requested = True
        logger.info("Outcome capture worker stop requested (signal=%s)", signum)

    try:
        signal.signal(signal.SIGINT, _handle_signal)
    except (ValueError, OSError):
        pass
    try:
        signal.signal(signal.SIGTERM, _handle_signal)
    except (ValueError, OSError):
        pass

    session = session_factory()
    try:
        clear_outcome_capture_worker_stop(session)
        session.commit()

        lock = acquire_outcome_capture_worker_lock(
            session,
            holder=lock_holder,
            stale_after_minutes=cfg.stale_lock_minutes,
        )
        session.commit()
        if not lock.acquired:
            logger.error(
                "Outcome capture worker could not acquire lock: reason=%s holder=%s",
                lock.reason,
                lock.holder,
            )
            return

        logger.info(
            "Outcome capture worker started interval=%ss holder=%s",
            cfg.interval_seconds,
            lock.holder,
        )

        while True:
            if stop_requested or (stop_check and stop_check()):
                break

            cycle_session = session_factory()
            summary: DelayedOutcomeCaptureCycleSummary | None = None
            cycle_error: str | None = None
            try:
                summary = run_delayed_outcome_capture_cycle(
                    cycle_session,
                    youtube_client=youtube_client,
                    dry_run=False,
                )
            except Exception as exc:
                cycle_session.rollback()
                cycle_error = str(exc)
                logger.exception("Outcome capture cycle failed")
            finally:
                cycle_session.close()

            heartbeat_session = session_factory()
            try:
                if summary is not None:
                    record_outcome_capture_cycle_finish(
                        heartbeat_session,
                        run_id=summary.run_id,
                        started_at=summary.started_at,
                        finished_at=summary.finished_at or utc_now(),
                        cycle_status=summary.cycle_status,
                        error=cycle_error,
                    )
                elif cycle_error:
                    record_outcome_capture_cycle_finish(
                        heartbeat_session,
                        run_id="",
                        started_at=utc_now(),
                        finished_at=utc_now(),
                        cycle_status="failed",
                        error=cycle_error,
                    )
                record_outcome_capture_worker_heartbeat(heartbeat_session)
                heartbeat_session.commit()
            finally:
                heartbeat_session.close()

            if cycle_error:
                sleep_fn(cfg.error_backoff_seconds)
            else:
                sleep_fn(cfg.interval_seconds)

    finally:
        try:
            release_outcome_capture_worker_lock(session, holder=lock_holder)
            session.commit()
        finally:
            session.close()
