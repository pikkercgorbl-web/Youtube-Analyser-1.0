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
    outcome_capture_budget_for_cycle,
)

from app.services.delayed_outcome_capture_cycle import (

    DelayedOutcomeCaptureCycleSummary,

    run_delayed_outcome_capture_cycle,

)

from app.services.metrics import utc_now

from app.services.outcome_capture_worker_lock import (

    OutcomeCaptureLockResult,

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
    max_videos_per_cycle: int | None = None





def _commit_lock_session(session: Session, lock: OutcomeCaptureLockResult) -> bool:

    """Persist lock row; return False when lock was not granted."""

    if not lock.acquired:

        session.rollback()

        return False

    session.commit()

    return True





def _renew_worker_lock(

    session_factory: Callable[[], Session],

    *,

    holder: str,

    stale_after_minutes: int,

) -> OutcomeCaptureLockResult:

    session = session_factory()

    try:

        lock = acquire_outcome_capture_worker_lock(

            session,

            holder=holder,

            stale_after_minutes=stale_after_minutes,

        )

        if not _commit_lock_session(session, lock):

            return lock

        return lock

    except Exception:

        session.rollback()

        raise

    finally:

        session.close()





def _persist_cycle_status(

    session_factory: Callable[[], Session],

    *,

    summary: DelayedOutcomeCaptureCycleSummary | None,

    cycle_error: str | None,

) -> bool:

    """Write cycle finish + heartbeat. Returns False if persistence failed."""

    session = session_factory()

    try:

        if summary is not None:

            record_outcome_capture_cycle_finish(

                session,

                run_id=summary.run_id,

                started_at=summary.started_at,

                finished_at=summary.finished_at or utc_now(),

                cycle_status=summary.cycle_status,

                error=cycle_error,

            )

        elif cycle_error:

            record_outcome_capture_cycle_finish(

                session,

                run_id="",

                started_at=utc_now(),

                finished_at=utc_now(),

                cycle_status="failed",

                error=cycle_error,

            )

        record_outcome_capture_worker_heartbeat(session)

        session.commit()

        return True

    except Exception:

        session.rollback()

        raise

    finally:

        session.close()





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

    lock_holder_resolved: str | None = lock_holder



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



    bootstrap_session = session_factory()

    try:

        clear_outcome_capture_worker_stop(bootstrap_session)

        bootstrap_session.commit()



        lock = acquire_outcome_capture_worker_lock(

            bootstrap_session,

            holder=lock_holder,

            stale_after_minutes=cfg.stale_lock_minutes,

        )

        if not _commit_lock_session(bootstrap_session, lock):

            logger.error(

                "Outcome capture worker could not acquire lock: reason=%s holder=%s",

                lock.reason,

                lock.holder,

            )

            return



        lock_holder_resolved = lock.holder or lock_holder_resolved

        cycle_budget = outcome_capture_budget_for_cycle(
            max_videos_per_cycle=cfg.max_videos_per_cycle,
        )
        logger.info(
            "Outcome capture worker effective config: max_videos=%s batch_size=%s "
            "interval_seconds=%s di_winner_priority_enabled=%s holder=%s",
            cycle_budget.max_videos_per_cycle,
            cycle_budget.batch_size,
            cfg.interval_seconds,
            cycle_budget.di_winner_priority_enabled,
            lock_holder_resolved,
        )



        while True:

            if stop_requested or (stop_check and stop_check()):

                break



            try:

                lock = _renew_worker_lock(

                    session_factory,

                    holder=lock_holder_resolved or "",

                    stale_after_minutes=cfg.stale_lock_minutes,

                )

            except Exception:

                logger.exception(

                    "Outcome capture worker lock renewal failed (holder=%s)",

                    lock_holder_resolved,

                )

                sleep_fn(float(cfg.error_backoff_seconds))

                continue



            if not lock.acquired:

                if lock.reason == "lock_held":

                    logger.error(

                        "Outcome capture lock held by another worker (%s); stopping",

                        lock.holder,

                    )

                    break

                logger.error(

                    "Outcome capture worker could not renew lock: reason=%s",

                    lock.reason,

                )

                sleep_fn(float(cfg.error_backoff_seconds))

                continue



            lock_holder_resolved = lock.holder or lock_holder_resolved



            cycle_session = session_factory()

            summary: DelayedOutcomeCaptureCycleSummary | None = None

            cycle_error: str | None = None

            try:

                summary = run_delayed_outcome_capture_cycle(

                    cycle_session,

                    youtube_client=youtube_client,

                    dry_run=False,

                    budget=outcome_capture_budget_for_cycle(
                        max_videos_per_cycle=cfg.max_videos_per_cycle,
                    ),

                )

            except Exception as exc:

                cycle_session.rollback()

                cycle_error = str(exc)

                logger.exception("Outcome capture cycle failed")

            finally:

                cycle_session.close()



            persistence_failed = False

            try:

                _persist_cycle_status(

                    session_factory,

                    summary=summary,

                    cycle_error=cycle_error,

                )

            except Exception:

                persistence_failed = True

                logger.exception(

                    "Outcome capture worker failed to persist cycle status "

                    "(cycle_error=%s)",

                    cycle_error,

                )



            if cycle_error or persistence_failed:

                sleep_fn(float(cfg.error_backoff_seconds))

            else:

                sleep_fn(float(cfg.interval_seconds))



    finally:

        release_session = session_factory()

        try:

            release_outcome_capture_worker_lock(

                release_session,

                holder=lock_holder_resolved,

            )

            release_session.commit()

        except Exception:

            logger.exception("Failed to release outcome capture worker lock")

            try:

                release_session.rollback()

            except Exception:

                pass

        finally:

            release_session.close()

        try:

            bootstrap_session.close()

        except Exception:

            pass


