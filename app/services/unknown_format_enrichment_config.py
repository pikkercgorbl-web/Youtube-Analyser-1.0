"""Config for UNKNOWN content_format refinement via videos.list (Stage 2)."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# UTC calendar-day cap on distinct videos.list checks (persisted in video_format_enrichment_attempts).
DEFAULT_UNKNOWN_FORMAT_ENRICHMENT_DAILY_VIDEO_LIMIT = 1000
VIDEOS_LIST_BATCH_SIZE = 50


class UnknownFormatEnrichmentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    unknown_format_enrichment_daily_video_limit: int = Field(
        default=DEFAULT_UNKNOWN_FORMAT_ENRICHMENT_DAILY_VIDEO_LIMIT,
        ge=0,
        validation_alias="UNKNOWN_FORMAT_ENRICHMENT_DAILY_VIDEO_LIMIT",
    )


unknown_format_enrichment_settings = UnknownFormatEnrichmentSettings()
