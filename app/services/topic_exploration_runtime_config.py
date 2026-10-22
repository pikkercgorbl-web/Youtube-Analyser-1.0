"""Topic exploration toggle and thresholds (Stage 6 — default off)."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TopicExplorationRuntimeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    topic_exploration_in_discovery: bool = Field(
        default=False,
        validation_alias="TOPIC_EXPLORATION_IN_DISCOVERY",
    )
    topic_exploration_queries_file: str | None = Field(
        default=None,
        validation_alias="TOPIC_EXPLORATION_QUERIES_FILE",
    )
    topic_exploration_batch_fraction: float = Field(
        default=0.2,
        validation_alias="TOPIC_EXPLORATION_BATCH_FRACTION",
    )
    topic_exploration_max_pages_per_query: int = Field(
        default=3,
        validation_alias="TOPIC_EXPLORATION_MAX_PAGES_PER_QUERY",
    )
    topic_exploration_auto_admit: bool = Field(
        default=False,
        validation_alias="TOPIC_EXPLORATION_AUTO_ADMIT",
    )
    topic_exploration_min_distinct_videos: int = Field(
        default=2,
        validation_alias="TOPIC_EXPLORATION_MIN_DISTINCT_VIDEOS",
    )
    topic_exploration_min_distinct_channels: int = Field(
        default=2,
        validation_alias="TOPIC_EXPLORATION_MIN_DISTINCT_CHANNELS",
    )
    topic_exploration_observation_window_hours: int = Field(
        default=168,
        validation_alias="TOPIC_EXPLORATION_OBSERVATION_WINDOW_HOURS",
    )


topic_exploration_runtime_settings = TopicExplorationRuntimeSettings()
