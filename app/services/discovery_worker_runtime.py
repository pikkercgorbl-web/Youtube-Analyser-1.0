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
from app.services.keyword_expansion_discovery_pass import run_keyword_expansion_discovery_pass
from app.services.keyword_expansion_runtime_config import keyword_expansion_runtime_settings
from app.services.topic_exploration_cycle import build_topic_exploration_cycle_plan
from app.services.topic_exploration_discovery_pass import run_topic_exploration_discovery_pass
from app.services.topic_exploration_runtime_config import topic_exploration_runtime_settings
from app.services.radar_enrichment_config import radar_enrichment_settings
from app.services.radar_enrichment_orchestrator import run_radar_enrichment_pass
from app.services.radar_enrichment_selection import RadarEnrichmentPassContext

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
    enrichment_pass_count = 0
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

        while True:
            if stop_requested or (stop_check and stop_check()):
                break

            exploration_plan = build_topic_exploration_cycle_plan(
                topic_exploration_runtime_settings,
                cycle_index=cycle_count,
            )
            cycle_config = DiscoveryCycleConfig(
                keyword_batch_size=max(1, cfg.keyword_batch_size),
                topic_exploration_plan=exploration_plan if exploration_plan.enabled else None,
            )

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

            if summary is not None and radar_enrichment_settings.radar_enrichment_after_discovery:
                enrichment_pass_count += 1
                enrich_session = session_factory()
                try:
                    enrich_report = run_radar_enrichment_pass(
                        enrich_session,
                        youtube_client,
                        context=RadarEnrichmentPassContext(
                            discovery_run_id=summary.run_id,
                            cycle_video_ids=frozenset(summary.cycle_video_ids),
                            cycle_channel_ids=frozenset(summary.cycle_channel_ids),
                            pass_sequence=enrichment_pass_count,
                        ),
                        dry_run=False,
                    )
                    enrich_session.commit()
                    logger.info(
                        "[RADAR_ENRICHMENT_PASS] discovery_run_id=%s channels=%s/%s videos=%s/%s errors=%s",
                        summary.run_id,
                        enrich_report.subscriber_channels_processed,
                        enrich_report.subscriber_channels_planned,
                        enrich_report.format_videos_processed,
                        enrich_report.format_videos_planned,
                        len(enrich_report.errors),
                    )
                except Exception:
                    enrich_session.rollback()
                    logger.exception(
                        "[RADAR_ENRICHMENT_PASS_ERROR] discovery_run_id=%s",
                        summary.run_id,
                    )
                finally:
                    enrich_session.close()

            if summary is not None and keyword_expansion_runtime_settings.keyword_expansion_after_discovery:
                expansion_session = session_factory()
                try:
                    expansion_report = run_keyword_expansion_discovery_pass(
                        expansion_session,
                        cycle_summary=summary,
                        dry_run=False,
                    )
                    if expansion_report.summary is not None and not (
                        expansion_report.summary.cycle_status == "dry_run"
                    ):
                        expansion_session.commit()
                    else:
                        expansion_session.rollback()
                    created = (
                        expansion_report.summary.created_keyword_count
                        if expansion_report.summary
                        else 0
                    )
                    logger.info(
                        "[KEYWORD_EXPANSION_PASS] discovery_run_id=%s expansion_run_id=%s seeds=%s created=%s errors=%s",
                        summary.run_id,
                        expansion_report.expansion_run_id,
                        expansion_report.selected_seed_count,
                        created,
                        len(expansion_report.errors),
                    )
                except Exception:
                    expansion_session.rollback()
                    logger.exception(
                        "[KEYWORD_EXPANSION_PASS_ERROR] discovery_run_id=%s",
                        summary.run_id,
                    )
                finally:
                    expansion_session.close()

            if summary is not None and topic_exploration_runtime_settings.topic_exploration_in_discovery:
                exploration_session = session_factory()
                try:
                    exploration_report = run_topic_exploration_discovery_pass(
                        exploration_session,
                        cycle_summary=summary,
                        dry_run=not topic_exploration_runtime_settings.topic_exploration_auto_admit,
                    )
                    if exploration_report.admitted_count > 0 and topic_exploration_runtime_settings.topic_exploration_auto_admit:
                        exploration_session.commit()
                    else:
                        exploration_session.rollback()
                    logger.info(
                        "[TOPIC_EXPLORATION_PASS] discovery_run_id=%s proposed=%s admitted=%s errors=%s",
                        summary.run_id,
                        len(exploration_report.preview.proposed) if exploration_report.preview else 0,
                        exploration_report.admitted_count,
                        len(exploration_report.errors),
                    )
                except Exception:
                    exploration_session.rollback()
                    logger.exception(
                        "[TOPIC_EXPLORATION_PASS_ERROR] discovery_run_id=%s",
                        summary.run_id,
                    )
                finally:
                    exploration_session.close()

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
