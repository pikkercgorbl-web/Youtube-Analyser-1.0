"""Aggregated radar qualification/filter metrics for one keyword scan (Stage 0)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# First-failure reason keys matching process_radar_videos check order.
FILTER_SKIP_DATE = "date"
FILTER_SKIP_MIN_VIEWS = "min_views"
FILTER_SKIP_MISSING_CHANNEL_ID = "missing_channel_id"
FILTER_SKIP_LANGUAGE = "language"
FILTER_SKIP_BLACKLIST = "blacklist"
FILTER_SKIP_MIN_SUBSCRIBERS = "min_subscribers"
FILTER_SKIP_MIN_VIRAL_COEFF = "min_viral_coeff"
FILTER_SKIP_PARSE_ERROR = "parse_error"


@dataclass
class RadarFilterMetrics:
    discovered_videos: int = 0
    format_skips: int = 0
    filter_skips: int = 0
    passed_videos: int = 0
    parse_errors: int = 0
    html_fallback_count: int = 0
    filter_skip_reasons: dict[str, int] = field(default_factory=dict)
    _unique_channel_ids: set[str] = field(default_factory=set, repr=False)

    @classmethod
    def empty(cls) -> RadarFilterMetrics:
        return cls()

    def record_discovered(self, count: int) -> None:
        if count > 0:
            self.discovered_videos += count

    def record_format_skip(self, count: int) -> None:
        if count > 0:
            self.format_skips += count

    def record_html_fallback(self) -> None:
        self.html_fallback_count += 1

    def record_skip(self, reason: str) -> None:
        self.filter_skips += 1
        self.filter_skip_reasons[reason] = self.filter_skip_reasons.get(reason, 0) + 1

    def record_pass(self, channel_id: str) -> None:
        self.passed_videos += 1
        normalized = channel_id.strip()
        if normalized:
            self._unique_channel_ids.add(normalized)

    def record_parse_error(self) -> None:
        self.parse_errors += 1
        self.filter_skip_reasons[FILTER_SKIP_PARSE_ERROR] = (
            self.filter_skip_reasons.get(FILTER_SKIP_PARSE_ERROR, 0) + 1
        )

    @property
    def unique_channels(self) -> int:
        return len(self._unique_channel_ids)

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "discovered_videos": self.discovered_videos,
            "format_skips": self.format_skips,
            "filter_skips": self.filter_skips,
            "passed_videos": self.passed_videos,
            "parse_errors": self.parse_errors,
            "unique_channels": self.unique_channels,
            "html_fallback_count": self.html_fallback_count,
            "filter_skip_reasons": dict(sorted(self.filter_skip_reasons.items())),
        }


class _NullRadarFilterMetrics:
    """No-op collector for callers that do not pass filter metrics."""

    def record_discovered(self, count: int) -> None:
        return None

    def record_format_skip(self, count: int) -> None:
        return None

    def record_html_fallback(self) -> None:
        return None

    def record_skip(self, reason: str) -> None:
        return None

    def record_pass(self, channel_id: str) -> None:
        return None

    def record_parse_error(self) -> None:
        return None


NULL_RADAR_FILTER_METRICS = _NullRadarFilterMetrics()
