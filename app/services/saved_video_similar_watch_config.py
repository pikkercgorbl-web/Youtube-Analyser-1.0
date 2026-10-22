"""Limits for SavedVideo similar-search watch (v1)."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SavedVideoSimilarWatchSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    min_queries_per_watch: int = Field(default=2, validation_alias="SAVED_VIDEO_SIMILAR_MIN_QUERIES")
    max_queries_per_watch: int = Field(default=5, validation_alias="SAVED_VIDEO_SIMILAR_MAX_QUERIES")
    max_active_watches: int = Field(default=50, validation_alias="SAVED_VIDEO_SIMILAR_MAX_ACTIVE_WATCHES")
    max_watches_per_cycle: int = Field(default=3, validation_alias="SAVED_VIDEO_SIMILAR_MAX_WATCHES_PER_CYCLE")
    max_query_searches_per_cycle: int = Field(
        default=9,
        validation_alias="SAVED_VIDEO_SIMILAR_MAX_QUERY_SEARCHES_PER_CYCLE",
    )
    max_pages_per_query: int = Field(default=2, validation_alias="SAVED_VIDEO_SIMILAR_MAX_PAGES_PER_QUERY")
    scan_interval_hours: int = Field(default=24, validation_alias="SAVED_VIDEO_SIMILAR_SCAN_INTERVAL_HOURS")
    scan_lease_minutes: int = Field(default=10, validation_alias="SAVED_VIDEO_SIMILAR_SCAN_LEASE_MINUTES")


saved_video_similar_watch_settings = SavedVideoSimilarWatchSettings()


def similar_watch_load_estimate() -> dict[str, str | int | float]:
    """Rough InnerTube load per discovery worker cycle (documentation / API)."""
    s = saved_video_similar_watch_settings
    per_query = s.max_pages_per_query
    max_searches = s.max_query_searches_per_cycle
    # Batch stops at max_query_searches_per_cycle (default 9), not watches×queries.
    # A due watch is skipped entirely when len(queries) > remaining query budget.
    max_pages = max_searches * per_query
    return {
        "max_watches_per_cycle": s.max_watches_per_cycle,
        "max_queries_per_watch": s.max_queries_per_watch,
        "min_queries_per_watch": s.min_queries_per_watch,
        "max_query_searches_per_discovery_cycle": max_searches,
        "max_pages_per_query": per_query,
        "max_innertube_search_pages_per_discovery_cycle": max_pages,
        "max_watches_scanned_per_discovery_cycle": s.max_watches_per_cycle,
        "scan_interval_hours_default": s.scan_interval_hours,
        "batch_selection_note": (
            "Up to max_watches_per_cycle due watches are considered; each executes "
            "len(confirmed_queries) InnerTube searches until the global "
            "max_query_searches_per_cycle cap. Watches needing more queries than "
            "the remaining budget are skipped (not split)."
        ),
        "note": (
            "SavedVideo similar watch and SavedFamily topic watch share this InnerTube budget "
            "(one fair queue per discovery cycle). No TargetKeyword queue writes, "
            "KeywordDiscoveryHit, Monitoring enrollment, or Attention refresh."
        ),
    }
