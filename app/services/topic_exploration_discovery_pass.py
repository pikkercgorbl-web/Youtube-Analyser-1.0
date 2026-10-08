"""Post-discovery topic exploration pass (Stage 6 — separate session, optional)."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.services.discovery_cycle import DiscoveryCycleSummary
from app.services.topic_exploration_admit import admit_topic_exploration_preview
from app.services.topic_exploration_mining_config import TopicExplorationMiningConfig
from app.services.topic_exploration_preview import build_topic_exploration_preview
from app.services.topic_exploration_runtime_config import topic_exploration_runtime_settings
from app.services.topic_exploration_types import TopicExplorationPassReport

logger = logging.getLogger(__name__)


def run_topic_exploration_discovery_pass(
    session: Session,
    *,
    cycle_summary: DiscoveryCycleSummary,
    mining_config: TopicExplorationMiningConfig | None = None,
    exploration_parent_by_query_id: dict[str, tuple[int, str]] | None = None,
    dry_run: bool = False,
    auto_admit: bool | None = None,
) -> TopicExplorationPassReport:
    scans = getattr(cycle_summary, "exploration_summaries", ()) or ()
    report = TopicExplorationPassReport(discovery_run_id=cycle_summary.run_id)
    if not scans:
        return report

    cfg = mining_config
    if cfg is None:
        settings = topic_exploration_runtime_settings
        cfg = TopicExplorationMiningConfig(
            min_distinct_videos=settings.topic_exploration_min_distinct_videos,
            min_distinct_channels=settings.topic_exploration_min_distinct_channels,
            observation_window_hours=settings.topic_exploration_observation_window_hours,
        )

    try:
        preview = build_topic_exploration_preview(
            session,
            discovery_run_id=cycle_summary.run_id,
            exploration_scans=scans,
            mining_config=cfg,
            record_phrase_stats=not dry_run,
        )
        report.preview = preview
    except Exception as exc:
        logger.exception("[TOPIC_EXPLORATION_PASS] preview_failed discovery_run_id=%s", cycle_summary.run_id)
        report.errors = (str(exc),)
        return report

    admit_flag = auto_admit if auto_admit is not None else topic_exploration_runtime_settings.topic_exploration_auto_admit
    if admit_flag and preview.proposed and exploration_parent_by_query_id:
        try:
            admitted, admit_errors = admit_topic_exploration_preview(
                session,
                preview,
                exploration_parent_by_query_id=exploration_parent_by_query_id,
                dry_run=dry_run,
            )
            report.admitted_count = admitted
            if admit_errors:
                report.errors = tuple(admit_errors)
        except Exception as exc:
            logger.exception("[TOPIC_EXPLORATION_PASS] admit_failed discovery_run_id=%s", cycle_summary.run_id)
            report.errors = report.errors + (str(exc),)

    logger.info(
        "[TOPIC_EXPLORATION_PASS] discovery_run_id=%s proposed=%s rejected=%s admitted=%s",
        cycle_summary.run_id,
        len(preview.proposed) if report.preview else 0,
        len(preview.rejected) if report.preview else 0,
        report.admitted_count,
    )
    return report
