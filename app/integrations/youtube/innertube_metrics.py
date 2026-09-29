"""Aggregated InnerTube HTTP metrics for radar keyword scans (Stage 0)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def innertube_endpoint_key(url: str) -> str:
    """Map a full InnerTube URL to a stable metrics bucket key."""
    if "/youtubei/v1/search" in url:
        return "search"
    if "/youtubei/v1/player" in url:
        return "player"
    if "/youtubei/v1/browse" in url:
        return "browse"
    if "/navigation/resolve_url" in url:
        return "resolve_url"
    if "get_search_suggestions" in url:
        return "suggestions"
    return "other"


@dataclass
class InnerTubeEndpointMetrics:
    count: int = 0
    total_duration_ms: float = 0.0
    max_duration_ms: float = 0.0
    error_count: int = 0

    @classmethod
    def empty(cls) -> InnerTubeEndpointMetrics:
        return cls()

    def record(
        self,
        *,
        duration_ms: float,
        success: bool,
    ) -> None:
        self.count += 1
        self.total_duration_ms += duration_ms
        if duration_ms > self.max_duration_ms:
            self.max_duration_ms = duration_ms
        if not success:
            self.error_count += 1


@dataclass
class InnerTubeMetrics:
    request_count: int = 0
    total_duration_ms: float = 0.0
    max_duration_ms: float = 0.0
    error_count: int = 0
    by_endpoint: dict[str, InnerTubeEndpointMetrics] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> InnerTubeMetrics:
        return cls()

    def record_request(
        self,
        *,
        endpoint_key: str,
        duration_ms: float,
        success: bool,
        status_code: int | None = None,
        error_kind: str | None = None,
    ) -> None:
        del status_code, error_kind  # reserved for future structured logs; not stored in Stage 0

        self.request_count += 1
        self.total_duration_ms += duration_ms
        if duration_ms > self.max_duration_ms:
            self.max_duration_ms = duration_ms
        if not success:
            self.error_count += 1

        bucket = self.by_endpoint.get(endpoint_key)
        if bucket is None:
            bucket = InnerTubeEndpointMetrics.empty()
            self.by_endpoint[endpoint_key] = bucket
        bucket.record(duration_ms=duration_ms, success=success)

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "request_count": self.request_count,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "max_duration_ms": round(self.max_duration_ms, 2),
            "error_count": self.error_count,
            "by_endpoint": {
                key: {
                    "count": bucket.count,
                    "total_duration_ms": round(bucket.total_duration_ms, 2),
                    "max_duration_ms": round(bucket.max_duration_ms, 2),
                    "error_count": bucket.error_count,
                }
                for key, bucket in sorted(self.by_endpoint.items())
            },
        }


class _NullInnerTubeMetrics:
    """No-op collector for callers that do not pass metrics."""

    def record_request(self, **kwargs: object) -> None:
        return None


NULL_INNERTUBE_METRICS = _NullInnerTubeMetrics()
