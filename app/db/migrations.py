"""Lightweight SQLite schema patches applied at application startup."""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def ensure_target_keywords_last_checked(engine: Engine) -> None:
    """Add target_keywords.last_checked when missing (SQLite-safe)."""
    inspector = inspect(engine)
    if "target_keywords" not in inspector.get_table_names():
        return

    column_names = {column["name"] for column in inspector.get_columns("target_keywords")}
    if "last_checked" in column_names:
        return

    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE target_keywords "
                "ADD COLUMN last_checked TIMESTAMP DEFAULT NULL",
            ),
        )
    logger.info("Added target_keywords.last_checked column")


def run_startup_migrations(engine: Engine) -> None:
    """Apply idempotent schema updates before serving traffic."""
    ensure_target_keywords_last_checked(engine)
    ensure_explosive_channel_settings_upload_period(engine)
    ensure_explosive_channels_video_id(engine)
    ensure_explosive_channels_vph(engine)
    ensure_radar_worker_state_status(engine)
    ensure_video_snapshots_table(engine)
    ensure_monitoring_worker_state_table(engine)
    ensure_monitoring_cycle_runs_table(engine)
    ensure_monitoring_video_queue_table(engine)
    ensure_discovery_worker_state_table(engine)
    ensure_keyword_performance_tables(engine)
    ensure_keyword_performance_read_model_tables(engine)
    ensure_target_keywords_lifecycle_columns(engine)
    ensure_keyword_lifecycle_events_table(engine)
    ensure_keyword_expansion_events_table(engine)
    ensure_outcome_capture_tables(engine)
    ensure_attention_engine_tables(engine)
    ensure_video_format_enrichment_attempts_table(engine)
    ensure_channels_subscribers_api_columns(engine)
    ensure_radar_api_budget_daily_table(engine)
    ensure_channel_subscriber_enrichment_attempts_table(engine)
    ensure_videos_published_at_source_column(engine)
    ensure_saved_topics_tables(engine)
    ensure_saved_topics_1_22d_tables(engine)
    ensure_read_model_publish_locks_table(engine)
    ensure_read_model_publish_lock_token_column(engine)
    ensure_topic_exploration_evidence_tables(engine)


def ensure_videos_published_at_source_column(engine: Engine) -> None:
    inspector = inspect(engine)
    if "videos" not in inspector.get_table_names():
        return
    column_names = {column["name"] for column in inspector.get_columns("videos")}
    if "published_at_source" in column_names:
        return
    dialect = engine.dialect.name
    col_type = "VARCHAR(32)" if dialect == "postgresql" else "VARCHAR(32)"
    with engine.begin() as connection:
        connection.execute(
            text(f"ALTER TABLE videos ADD COLUMN published_at_source {col_type}"),
        )
    logger.info("Added videos.published_at_source column")


def ensure_channels_subscribers_api_columns(engine: Engine) -> None:
    """Add channels.subscribers_api_* columns when missing (Stage 2.3)."""
    inspector = inspect(engine)
    if "channels" not in inspector.get_table_names():
        return
    column_names = {column["name"] for column in inspector.get_columns("channels")}
    with engine.begin() as connection:
        if "subscribers_api_status" not in column_names:
            connection.execute(
                text(
                    "ALTER TABLE channels "
                    "ADD COLUMN subscribers_api_status VARCHAR(16)",
                ),
            )
            logger.info("Added channels.subscribers_api_status column")
        if "subscribers_api_checked_at" not in column_names:
            connection.execute(
                text(
                    "ALTER TABLE channels "
                    "ADD COLUMN subscribers_api_checked_at TIMESTAMPTZ",
                ),
            )
            logger.info("Added channels.subscribers_api_checked_at column")


def ensure_channel_subscriber_enrichment_attempts_table(engine: Engine) -> None:
    inspector = inspect(engine)
    if "channel_subscriber_enrichment_attempts" in inspector.get_table_names():
        return
    from app.models.orm import ChannelSubscriberEnrichmentAttempt

    ChannelSubscriberEnrichmentAttempt.__table__.create(bind=engine, checkfirst=True)
    logger.info("Created channel_subscriber_enrichment_attempts table")


def ensure_radar_api_budget_daily_table(engine: Engine) -> None:
    """Create radar_api_budget_daily when missing (Stage 2.5)."""
    inspector = inspect(engine)
    if "radar_api_budget_daily" in inspector.get_table_names():
        return
    from app.models.orm import RadarApiBudgetDay

    RadarApiBudgetDay.__table__.create(bind=engine, checkfirst=True)
    logger.info("Created radar_api_budget_daily table")


def ensure_video_format_enrichment_attempts_table(engine: Engine) -> None:
    """Create video_format_enrichment_attempts when missing (Stage 2.1)."""
    inspector = inspect(engine)
    if "video_format_enrichment_attempts" in inspector.get_table_names():
        return
    from app.models.orm import VideoFormatEnrichmentAttempt

    VideoFormatEnrichmentAttempt.__table__.create(bind=engine, checkfirst=True)
    logger.info("Created video_format_enrichment_attempts table")


def ensure_saved_topics_tables(engine: Engine) -> None:
    """Create Saved Topics / Watchlist tables when missing (Stage 1.22C)."""
    inspector = inspect(engine)
    names = set(inspector.get_table_names())
    from app.models.orm import SavedTopic, SavedTopicObservation

    if "saved_topics" not in names:
        SavedTopic.__table__.create(bind=engine, checkfirst=True)
        logger.info("Created saved_topics table")
    if "saved_topic_observations" not in names:
        SavedTopicObservation.__table__.create(bind=engine, checkfirst=True)
        logger.info("Created saved_topic_observations table")


def ensure_saved_topics_1_22d_tables(engine: Engine) -> None:
    """Create Saved Topic events and feedback tables (Stage 1.22D)."""
    inspector = inspect(engine)
    names = set(inspector.get_table_names())
    from app.models.orm import SavedTopicEvent, SavedTopicFeedback

    if "saved_topic_events" not in names:
        SavedTopicEvent.__table__.create(bind=engine, checkfirst=True)
        logger.info("Created saved_topic_events table")
    if "saved_topic_feedback" not in names:
        SavedTopicFeedback.__table__.create(bind=engine, checkfirst=True)
        logger.info("Created saved_topic_feedback table")


def ensure_attention_engine_tables(engine: Engine) -> None:
    """Create Attention Engine snapshot tables when missing (Stage 1.22A)."""
    inspector = inspect(engine)
    names = set(inspector.get_table_names())
    from app.models.orm import (
        AttentionChannelMomentumRow,
        AttentionFamilyIdentity,
        AttentionPatternFamilyMemberRow,
        AttentionPatternFamilyRow,
        AttentionPatternFamilyVideoRow,
        AttentionPatternRow,
        AttentionPatternVideoRow,
        AttentionRun,
        AttentionVideoWinnerRow,
    )

    mapping = {
        "attention_runs": AttentionRun,
        "attention_video_winners": AttentionVideoWinnerRow,
        "attention_patterns": AttentionPatternRow,
        "attention_pattern_videos": AttentionPatternVideoRow,
        "attention_pattern_families": AttentionPatternFamilyRow,
        "attention_pattern_family_members": AttentionPatternFamilyMemberRow,
        "attention_pattern_family_videos": AttentionPatternFamilyVideoRow,
        "attention_family_identity": AttentionFamilyIdentity,
        "attention_channel_momentum": AttentionChannelMomentumRow,
    }
    for table_name, model in mapping.items():
        if table_name not in names:
            model.__table__.create(bind=engine, checkfirst=True)
            logger.info("Created %s table", table_name)


def ensure_outcome_capture_tables(engine: Engine) -> None:
    """Create outcome capture worker/cycle tables when missing (Stage 1.20E.2)."""
    inspector = inspect(engine)
    names = set(inspector.get_table_names())
    from app.models.orm import OutcomeCaptureCycleRun, OutcomeCaptureWorkerState

    if "outcome_capture_cycle_runs" not in names:
        OutcomeCaptureCycleRun.__table__.create(bind=engine, checkfirst=True)
        logger.info("Created outcome_capture_cycle_runs table")
    if "outcome_capture_worker_state" not in names:
        OutcomeCaptureWorkerState.__table__.create(bind=engine, checkfirst=True)
        logger.info("Created outcome_capture_worker_state table")


def ensure_monitoring_cycle_runs_table(engine: Engine) -> None:
    """Create monitoring_cycle_runs table when missing (Stage 1.14A)."""
    inspector = inspect(engine)
    if "monitoring_cycle_runs" in inspector.get_table_names():
        return

    from app.models.orm import MonitoringCycleRun

    MonitoringCycleRun.__table__.create(bind=engine, checkfirst=True)
    logger.info("Created monitoring_cycle_runs table")


def ensure_monitoring_video_queue_table(engine: Engine) -> None:
    """Create monitoring_video_queue table when missing (Stage 1.20E.3)."""
    inspector = inspect(engine)
    if "monitoring_video_queue" in inspector.get_table_names():
        return

    from app.models.orm import MonitoringVideoQueueEntry

    MonitoringVideoQueueEntry.__table__.create(bind=engine, checkfirst=True)
    logger.info("Created monitoring_video_queue table")


def ensure_monitoring_worker_state_table(engine: Engine) -> None:
    """Create monitoring_worker_state table when missing (Stage 1.13C)."""
    inspector = inspect(engine)
    if "monitoring_worker_state" in inspector.get_table_names():
        return

    from app.models.orm import MonitoringWorkerState

    MonitoringWorkerState.__table__.create(bind=engine, checkfirst=True)
    logger.info("Created monitoring_worker_state table")


def ensure_target_keywords_lifecycle_columns(engine: Engine) -> None:
    """Add lifecycle/scheduling columns and backfill (Stage 1.16B)."""
    inspector = inspect(engine)
    if "target_keywords" not in inspector.get_table_names():
        return

    column_names = {column["name"] for column in inspector.get_columns("target_keywords")}
    alters: list[str] = []
    if "lifecycle_status" not in column_names:
        alters.append("ALTER TABLE target_keywords ADD COLUMN lifecycle_status VARCHAR(16) NOT NULL DEFAULT 'active'")
    if "scan_interval_seconds" not in column_names:
        alters.append("ALTER TABLE target_keywords ADD COLUMN scan_interval_seconds INTEGER DEFAULT NULL")
    if "next_scan_at" not in column_names:
        alters.append("ALTER TABLE target_keywords ADD COLUMN next_scan_at TIMESTAMP DEFAULT NULL")
    if "status_changed_at" not in column_names:
        alters.append("ALTER TABLE target_keywords ADD COLUMN status_changed_at TIMESTAMP DEFAULT NULL")
    if "status_reason" not in column_names:
        alters.append("ALTER TABLE target_keywords ADD COLUMN status_reason VARCHAR(256) DEFAULT NULL")
    if "source_type" not in column_names:
        alters.append("ALTER TABLE target_keywords ADD COLUMN source_type VARCHAR(16) NOT NULL DEFAULT 'seed'")
    if "parent_keyword_id" not in column_names:
        alters.append("ALTER TABLE target_keywords ADD COLUMN parent_keyword_id INTEGER DEFAULT NULL")

    if alters:
        with engine.begin() as connection:
            for statement in alters:
                connection.execute(text(statement))
        logger.info("Added target_keywords lifecycle columns")

    _backfill_target_keyword_scheduling(engine)


def _backfill_target_keyword_scheduling(engine: Engine) -> None:
    from datetime import timedelta

    from sqlalchemy.orm import Session

    from app.models.db import SessionLocal
    from app.models.orm import TargetKeyword
    from app.services.keyword_scheduling_policy import DEFAULT_SCHEDULING_POLICY
    from app.services.metrics import utc_now

    session = Session(engine)
    try:
        now = utc_now()
        policy = DEFAULT_SCHEDULING_POLICY
        from sqlalchemy import select

        rows = session.scalars(select(TargetKeyword)).all()
        changed = False
        for row in rows:
            if not row.lifecycle_status:
                row.lifecycle_status = "active"
                changed = True
            if not row.source_type:
                row.source_type = "seed"
                changed = True
            interval = policy.interval_seconds_for(row.lifecycle_status)
            if row.scan_interval_seconds is None and interval is not None:
                row.scan_interval_seconds = interval
                changed = True
            if row.next_scan_at is None and row.lifecycle_status != "archived":
                if row.last_checked is not None:
                    row.next_scan_at = row.last_checked + timedelta(
                        hours=policy.active_interval_hours,
                    )
                else:
                    row.next_scan_at = now
                changed = True
            if row.status_changed_at is None:
                row.status_changed_at = row.created_at or now
                changed = True
        if changed:
            session.commit()
    finally:
        session.close()


def ensure_keyword_expansion_events_table(engine: Engine) -> None:
    inspector = inspect(engine)
    if "keyword_expansion_events" in inspector.get_table_names():
        return
    from app.models.orm import KeywordExpansionEvent

    KeywordExpansionEvent.__table__.create(bind=engine, checkfirst=True)
    logger.info("Created keyword_expansion_events table")


def ensure_keyword_lifecycle_events_table(engine: Engine) -> None:
    inspector = inspect(engine)
    if "keyword_lifecycle_events" in inspector.get_table_names():
        return
    from app.models.orm import KeywordLifecycleEvent

    KeywordLifecycleEvent.__table__.create(bind=engine, checkfirst=True)
    logger.info("Created keyword_lifecycle_events table")


def ensure_keyword_performance_tables(engine: Engine) -> None:
    """Create keyword scan/hit tables when missing (Stage 1.16A)."""
    inspector = inspect(engine)
    from app.models.orm import KeywordDiscoveryHit, KeywordScanRun

    if "keyword_scan_runs" not in inspector.get_table_names():
        KeywordScanRun.__table__.create(bind=engine, checkfirst=True)
        logger.info("Created keyword_scan_runs table")
    if "keyword_discovery_hits" not in inspector.get_table_names():
        KeywordDiscoveryHit.__table__.create(bind=engine, checkfirst=True)
        logger.info("Created keyword_discovery_hits table")


def ensure_keyword_performance_read_model_tables(engine: Engine) -> None:
    """Create keyword performance snapshot tables when missing (Stage 1.20E.4)."""
    inspector = inspect(engine)
    names = set(inspector.get_table_names())
    from app.models.orm import KeywordPerformanceGlobalSnapshot, KeywordPerformanceKeywordSnapshot

    if "keyword_performance_global_snapshots" not in names:
        KeywordPerformanceGlobalSnapshot.__table__.create(bind=engine, checkfirst=True)
        logger.info("Created keyword_performance_global_snapshots table")
    if "keyword_performance_keyword_snapshots" not in names:
        KeywordPerformanceKeywordSnapshot.__table__.create(bind=engine, checkfirst=True)
        logger.info("Created keyword_performance_keyword_snapshots table")


def ensure_discovery_worker_state_table(engine: Engine) -> None:
    """Create discovery_worker_state table when missing (Stage 1.15B)."""
    inspector = inspect(engine)
    if "discovery_worker_state" in inspector.get_table_names():
        return

    from app.models.orm import DiscoveryWorkerState

    DiscoveryWorkerState.__table__.create(bind=engine, checkfirst=True)
    logger.info("Created discovery_worker_state table")


def ensure_video_snapshots_table(engine: Engine) -> None:
    """Create video_snapshots table when missing (Stage 1.11)."""
    inspector = inspect(engine)
    if "video_snapshots" in inspector.get_table_names():
        return

    from app.models.orm import VideoSnapshot

    VideoSnapshot.__table__.create(bind=engine, checkfirst=True)
    logger.info("Created video_snapshots table")


def ensure_radar_worker_state_status(engine: Engine) -> None:
    """Add radar_worker_state.status when missing (SQLite-safe)."""
    inspector = inspect(engine)
    if "radar_worker_state" not in inspector.get_table_names():
        return

    column_names = {column["name"] for column in inspector.get_columns("radar_worker_state")}
    if "status" in column_names:
        return

    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE radar_worker_state "
                "ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'idle'",
            ),
        )
    logger.info("Added radar_worker_state.status column")


def ensure_explosive_channels_vph(engine: Engine) -> None:
    """Add explosive_channels.vph when missing (SQLite-safe)."""
    inspector = inspect(engine)
    if "explosive_channels" not in inspector.get_table_names():
        return

    column_names = {column["name"] for column in inspector.get_columns("explosive_channels")}
    if "vph" in column_names:
        return

    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE explosive_channels ADD COLUMN vph FLOAT DEFAULT NULL"),
        )
    logger.info("Added explosive_channels.vph column")


def ensure_explosive_channel_settings_upload_period(engine: Engine) -> None:
    """Add explosive_channel_settings.upload_period when missing (SQLite-safe)."""
    inspector = inspect(engine)
    if "explosive_channel_settings" not in inspector.get_table_names():
        return

    column_names = {column["name"] for column in inspector.get_columns("explosive_channel_settings")}
    if "upload_period" in column_names:
        return

    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE explosive_channel_settings "
                "ADD COLUMN upload_period VARCHAR(32) NOT NULL DEFAULT 'all'",
            ),
        )
    logger.info("Added explosive_channel_settings.upload_period column")


def ensure_explosive_channels_video_id(engine: Engine) -> None:
    """Add explosive_channels.representative_video_id when missing (SQLite-safe)."""
    inspector = inspect(engine)
    if "explosive_channels" not in inspector.get_table_names():
        return

    column_names = {column["name"] for column in inspector.get_columns("explosive_channels")}
    if "representative_video_id" in column_names:
        return

    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE explosive_channels "
                "ADD COLUMN representative_video_id VARCHAR(32) NOT NULL DEFAULT ''",
            ),
        )
    logger.info("Added explosive_channels.representative_video_id column")


def ensure_read_model_publish_locks_table(engine: Engine) -> None:
    """Create read_model_publish_locks when missing (Stage 3)."""
    inspector = inspect(engine)
    if "read_model_publish_locks" in inspector.get_table_names():
        return

    from app.models.orm import ReadModelPublishLock

    ReadModelPublishLock.__table__.create(bind=engine, checkfirst=True)
    logger.info("Created read_model_publish_locks table")


def ensure_read_model_publish_lock_token_column(engine: Engine) -> None:
    inspector = inspect(engine)
    if "read_model_publish_locks" not in inspector.get_table_names():
        return
    column_names = {column["name"] for column in inspector.get_columns("read_model_publish_locks")}
    if "lock_token" in column_names:
        return
    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE read_model_publish_locks ADD COLUMN lock_token VARCHAR(64)"),
        )
    logger.info("Added read_model_publish_locks.lock_token column")


def ensure_topic_exploration_evidence_tables(engine: Engine) -> None:
    """Create topic exploration evidence tables when missing (Stage 6)."""
    inspector = inspect(engine)
    names = set(inspector.get_table_names())
    from app.models.orm import (
        TopicExplorationPass,
        TopicExplorationPhrasePassStat,
        TopicExplorationVideoObservation,
    )

    if "topic_exploration_passes" not in names:
        TopicExplorationPass.__table__.create(bind=engine, checkfirst=True)
        logger.info("Created topic_exploration_passes table")
    if "topic_exploration_video_observations" not in names:
        TopicExplorationVideoObservation.__table__.create(bind=engine, checkfirst=True)
        logger.info("Created topic_exploration_video_observations table")
    if "topic_exploration_phrase_pass_stats" not in names:
        TopicExplorationPhrasePassStat.__table__.create(bind=engine, checkfirst=True)
        logger.info("Created topic_exploration_phrase_pass_stats table")
