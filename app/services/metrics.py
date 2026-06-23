"""Pure metric calculation helpers for competitor analytics."""

from __future__ import annotations

from datetime import datetime, timezone
from statistics import median


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def calc_vph(views_count: int, published_at: datetime, *, now: datetime | None = None) -> float:
    """
    Views Per Hour: views / hours since publish.

    Uses a minimum of 1 hour to avoid division spikes on brand-new uploads.
    """
    reference = ensure_utc(now or utc_now())
    published = ensure_utc(published_at)
    hours_live = max((reference - published).total_seconds() / 3600.0, 1.0)
    return views_count / hours_live


def calc_growth_rate(current: int, previous: int) -> float:
    """Relative growth in percent: ((current - previous) / max(previous, 1)) × 100."""
    return ((current - previous) / max(previous, 1)) * 100.0


def calc_growth_score(
    subscribers_growth_pct: float,
    views_growth_pct: float,
    *,
    subscribers_weight: float = 0.4,
    views_weight: float = 0.6,
) -> float:
    """Weighted composite score for trend ranking."""
    return subscribers_weight * subscribers_growth_pct + views_weight * views_growth_pct


def safe_median(values: list[float]) -> float:
    return float(median(values)) if values else 0.0
