"""Validation-only content format filters for Stage 1.8 breakout experiment."""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

from app.integrations.youtube.client import RadarContentFormatFilters
from app.services.explosive_channels_radar_worker import (
    get_radar_content_filters,
    set_radar_content_filters,
)

VALIDATION_CONTENT_FILTERS = RadarContentFormatFilters(
    exclude_streams=True,
    exclude_shorts=True,
    exclude_videos=False,
)


@contextmanager
def validation_content_filters() -> Iterator[RadarContentFormatFilters]:
    """
    Temporarily apply validation format filters for the current process.

    Restores the previous global filter state on exit so production Radar
    behavior is unchanged.
    """
    previous = get_radar_content_filters()
    set_radar_content_filters(
        exclude_streams=VALIDATION_CONTENT_FILTERS.exclude_streams,
        exclude_shorts=VALIDATION_CONTENT_FILTERS.exclude_shorts,
        exclude_videos=VALIDATION_CONTENT_FILTERS.exclude_videos,
    )
    try:
        yield VALIDATION_CONTENT_FILTERS
    finally:
        set_radar_content_filters(
            exclude_streams=previous.exclude_streams,
            exclude_shorts=previous.exclude_shorts,
            exclude_videos=previous.exclude_videos,
        )
