"""Continuous discovery worker loop (Stage 1.15B)."""

from __future__ import annotations

import logging
import signal
import time
from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from app.services.discovery_cycle import (
    DiscoveryCycleConfig,
    DiscoveryCycleSummary,
    run_discovery_cycle,
)
from app.services.discovery_worker_lock import (
    acquire_discovery_worker_lock,
    clear_discovery_worker_stop,
    record_discovery_worker_cycle,
    release_discovery_worker_lock,
)
from app.services.metrics import utc_now

logger = logging.getLogger(__name__)

DEFAULT_DISCOVERY_WORKER_INTERVAL_SECONDS = 300
DEFAULT_DISCOVERY_ERROR_BACKOFF_SECONDS = 300


@dataclass
class DiscoveryWorkerConfig:
    interval_seconds: int = DEFAULT_DISCOVERY_WORKER_INTERVAL_SECONDS
    error_backoff_seconds: int = DEFAULT_DISCOVERY_ERROR_BACKOFF_SECONDS
    stale_lock_minutes: int = 90
    keyword_batch_size: int = 5


def _default_sleep(seconds: float) -> None:
    time.sleep(seconds)


def run_discovery_worker(
    session_factory: Callable[[], Session],
    youtube_client,
    *,
    config: DiscoveryWorkerConfig | None = None,
    sleep_fn: Callable[[float], None] = _default_sleep,
    stop_check: Callable[[], bool] | None = None,
    lock_holder: str | None = None,
) -> None:
    """
    Acquire singleton lock, run discovery cycles sequentially (no overlap), release on exit.
    """
    cfg = config or DiscoveryWorkerConfig()
    stop_requested = False
    cycle_count = 0
    last_run_id: str | None = None
    last_status: str | None = None

    def _handle_signal(signum, _frame) -> None:
        nonlocal stop_requested
        stop_requested = True
        logger.info("Discovery worker stop requested (signal=%s)", signum)

    try:
        signal.signal(signal.SIGINT, _handle_signal)
    except (ValueError, OSError):
        pass
    try:
        signal.signal(signal.SIGTERM, _handle_signal)
    except (ValueError, OSError):
        pass

    session = session_factory()
    lock_holder_resolved: str | None = None
    try:
        clear_discovery_worker_stop(session)
        session.commit()

        lock = acquire_discovery_worker_lock(
            session,
            holder=lock_holder,
            stale_after_minutes=cfg.stale_lock_minutes,
        )
        session.commit()
        if not lock.acquired:
            logger.error(
                "Discovery worker could not acquire lock: reason=%s holder=%s",
                lock.reason,
                lock.holder,
            )
            return

        lock_holder_resolved = lock.holder
        logger.info(
            "[DISCOVERY_WORKER_START] worker_id=%s interval=%ss batch_size=%s",
            lock_holder_resolved,
            cfg.interval_seconds,
            cfg.keyword_batch_size,
        )

        cycle_config = DiscoveryCycleConfig(keyword_batch_size=max(1, cfg.keyword_batch_size))

        while True:
            if stop_requested or (stop_check and stop_check()):
                break

            cycle_session = session_factory()
            summary: DiscoveryCycleSummary | None = None
            cycle_started = utc_now()
            try:
                summary = run_discovery_cycle(
                    cycle_session,
                    youtube_client=youtube_client,
                    config=cycle_config,
                    dry_run=False,
                ).summary
                cycle_count += 1
                last_run_id = summary.run_id
                last_status = summary.cycle_status
                record_discovery_worker_cycle(
                    session,
                    started_at=summary.started_at,
                    finished_at=summary.finished_at or utc_now(),
                    run_id=summary.run_id,
                    cycle_status=summary.cycle_status,
                    last_error=None,
                )
                session.commit()
                if summary.selected_keyword_count == 0:
                    logger.info(
                        "[DISCOVERY_WORKER] no_keywords worker_id=%s cycle_count=%s",
                        lock_holder_resolved,
                        cycle_count,
                    )
            except Exception as exc:
                cycle_session.rollback()
                logger.exception(
                    "[DISCOVERY_WORKER_ERROR] worker_id=%s cycle_count=%s error=%s",
                    lock_holder_resolved,
                    cycle_count,
                    exc,
                )
                try:
                    record_discovery_worker_cycle(
                        session,
                        started_at=cycle_started,
                        finished_at=utc_now(),
                        run_id=last_run_id or "",
                        cycle_status="failed",
                        last_error=str(exc),
                    )
                    session.commit()
                except Exception:
                    session.rollback()
                sleep_fn(float(cfg.error_backoff_seconds))
                continue
            finally:
                cycle_session.close()

            if stop_requested or (stop_check and stop_check()):
                break

            sleep_fn(float(cfg.interval_seconds))

    finally:
        try:
            release_discovery_worker_lock(session, holder=lock_holder_resolved or lock_holder)
            session.commit()
        except Exception:
            logger.exception("Failed to release discovery worker lock")
            session.rollback()
        finally:
            session.close()
        logger.info(
            "[DISCOVERY_WORKER_STOP] worker_id=%s cycle_count=%s last_run_id=%s last_status=%s at=%s",
            lock_holder_resolved or lock_holder,
            cycle_count,
            last_run_id,
            last_status,
            utc_now().isoformat(),
        )
