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
