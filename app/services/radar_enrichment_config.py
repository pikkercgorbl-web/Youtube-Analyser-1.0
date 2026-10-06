"""Configuration for Radar enrichment pass (Stage 2.5)."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.services.unknown_format_enrichment_config import VIDEOS_LIST_BATCH_SIZE

DEFAULT_CHANNEL_SUBSCRIBER_DAILY_LIMIT = 1000
DEFAULT_CHANNEL_SUBSCRIBER_PASS_LIMIT = 50
DEFAULT_VIDEO_FORMAT_PASS_LIMIT = 50
DEFAULT_SUBSCRIBER_HIDDEN_COOLDOWN_HOURS = 720
DEFAULT_SUBSCRIBER_RETRY_AFTER_HOURS = 6
DEFAULT_SUBSCRIBER_KNOWN_RECHECK_DAYS = 7
DEFAULT_FORMAT_RECENT_HIT_HOURS = 48
DEFAULT_FORMAT_ENRICHMENT_RETRY_AFTER_HOURS = 6
CHANNELS_LIST_BATCH_SIZE = 50


class RadarEnrichmentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    radar_enrichment_after_discovery: bool = Field(
        default=False,
        validation_alias="RADAR_ENRICHMENT_AFTER_DISCOVERY",
    )
    channel_subscriber_enrichment_daily_limit: int = Field(
        default=DEFAULT_CHANNEL_SUBSCRIBER_DAILY_LIMIT,
        ge=0,
        validation_alias="CHANNEL_SUBSCRIBER_ENRICHMENT_DAILY_LIMIT",
    )
    channel_subscriber_enrichment_pass_limit: int = Field(
        default=DEFAULT_CHANNEL_SUBSCRIBER_PASS_LIMIT,
        ge=0,
        validation_alias="CHANNEL_SUBSCRIBER_ENRICHMENT_PASS_LIMIT",
    )
    video_format_enrichment_pass_limit: int = Field(
        default=DEFAULT_VIDEO_FORMAT_PASS_LIMIT,
        ge=0,
        validation_alias="VIDEO_FORMAT_ENRICHMENT_PASS_LIMIT",
    )
    subscriber_hidden_cooldown_hours: int = Field(
        default=DEFAULT_SUBSCRIBER_HIDDEN_COOLDOWN_HOURS,
        ge=0,
        validation_alias="SUBSCRIBER_HIDDEN_COOLDOWN_HOURS",
    )
    subscriber_retry_after_hours: int = Field(
        default=DEFAULT_SUBSCRIBER_RETRY_AFTER_HOURS,
        ge=0,
        validation_alias="SUBSCRIBER_RETRY_AFTER_HOURS",
    )
    subscriber_known_recheck_days: int = Field(
        default=DEFAULT_SUBSCRIBER_KNOWN_RECHECK_DAYS,
        ge=0,
        validation_alias="SUBSCRIBER_KNOWN_RECHECK_DAYS",
    )
    format_recent_hit_hours: int = Field(
        default=DEFAULT_FORMAT_RECENT_HIT_HOURS,
        ge=0,
        validation_alias="FORMAT_RECENT_HIT_HOURS",
    )
    format_enrichment_retry_after_hours: int = Field(
        default=DEFAULT_FORMAT_ENRICHMENT_RETRY_AFTER_HOURS,
        ge=0,
        validation_alias="FORMAT_ENRICHMENT_RETRY_AFTER_HOURS",
    )


radar_enrichment_settings = RadarEnrichmentSettings()
