"""Continuous monitoring worker loop (Stage 1.13C)."""

from __future__ import annotations

import logging
import signal
import time
from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from app.services.metrics import utc_now
from app.services.monitoring_cycle import (
    DEFAULT_MONITORING_ERROR_BACKOFF_SECONDS,
    DEFAULT_MONITORING_WORKER_INTERVAL_SECONDS,
    MonitoringCycleSummary,
    run_monitoring_cycle,
)
from app.services.monitoring_worker_lock import (
    acquire_monitoring_worker_lock,
    clear_monitoring_worker_stop,
    record_monitoring_worker_heartbeat,
    release_monitoring_worker_lock,
)
from app.services.revisit_executor import VideoBatchFetchClient

logger = logging.getLogger(__name__)


@dataclass
class MonitoringWorkerConfig:
    interval_seconds: int = DEFAULT_MONITORING_WORKER_INTERVAL_SECONDS
    error_backoff_seconds: int = DEFAULT_MONITORING_ERROR_BACKOFF_SECONDS
    stale_lock_minutes: int = 90


class StopMonitoringWorker(Exception):
    """Raised when shutdown was requested."""


def _default_sleep(seconds: float) -> None:
    time.sleep(seconds)


def run_monitoring_worker_loop(
    session_factory: Callable[[], Session],
    youtube_client: VideoBatchFetchClient,
    *,
    config: MonitoringWorkerConfig | None = None,
    sleep_fn: Callable[[float], None] = _default_sleep,
    stop_check: Callable[[], bool] | None = None,
    lock_holder: str | None = None,
) -> None:
    """
    Acquire singleton lock, run monitoring cycles sequentially (no overlap), release on exit.
    """
    cfg = config or MonitoringWorkerConfig()
    stop_requested = False

    def _handle_signal(signum, _frame) -> None:
        nonlocal stop_requested
        stop_requested = True
        logger.info("Monitoring worker stop requested (signal=%s)", signum)

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
        clear_monitoring_worker_stop(session)
        session.commit()

        lock = acquire_monitoring_worker_lock(
            session,
            holder=lock_holder,
            stale_after_minutes=cfg.stale_lock_minutes,
        )
        session.commit()
        if not lock.acquired:
            logger.error(
                "Monitoring worker could not acquire lock: reason=%s holder=%s",
                lock.reason,
                lock.holder,
            )
            return

        logger.info(
            "Monitoring worker started interval=%ss holder=%s",
            cfg.interval_seconds,
            lock.holder,
        )

        while True:
            if stop_requested or (stop_check and stop_check()):
                break

            cycle_session = session_factory()
            summary: MonitoringCycleSummary | None = None
            try:
                summary = run_monitoring_cycle(
                    cycle_session,
                    youtube_client=youtube_client,
                    dry_run=False,
                )
                cycle_session.commit()
                record_monitoring_worker_heartbeat(
                    session,
                    at=summary.finished_at if summary is not None else None,
                )
                session.commit()
            except StopMonitoringWorker:
                cycle_session.rollback()
                break
            except Exception:
                cycle_session.rollback()
                logger.exception("Monitoring cycle failed with unexpected error")
                record_monitoring_worker_heartbeat(session)
                session.commit()
                sleep_fn(float(cfg.error_backoff_seconds))
                continue
            finally:
                cycle_session.close()

            if stop_requested or (stop_check and stop_check()):
                break

            sleep_fn(float(cfg.interval_seconds))

    finally:
        try:
            release_monitoring_worker_lock(session, holder=lock_holder)
            session.commit()
        except Exception:
            logger.exception("Failed to release monitoring worker lock")
            session.rollback()
        finally:
            session.close()
        logger.info("Monitoring worker stopped at %s", utc_now().isoformat())
