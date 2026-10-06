"""VPH acceleration from VideoSnapshot history (Stage 1.22A)."""

from __future__ import annotations

from typing import Sequence

from app.services.attention_engine_types import AccelerationState

MIN_ACCELERATION_SNAPSHOTS = 3
ACCELERATION_RATIO = 2.0


def classify_acceleration(
    vph_series: Sequence[float | None],
    *,
    min_points: int = MIN_ACCELERATION_SNAPSHOTS,
) -> AccelerationState:
    """
    Require ``min_points`` non-null VPH observations in capture order.

    accelerating: last >= first * 2 and mid >= first
    decelerating: last <= first / 2 and mid <= first
    otherwise stable
    """
    points = [float(v) for v in vph_series if v is not None]
    if len(points) < min_points:
        return "unavailable"
    first = points[0]
    last = points[-1]
    mid = points[len(points) // 2]
    if first <= 0:
        return "unavailable"
    if last >= first * ACCELERATION_RATIO and mid >= first:
        return "accelerating"
    if last <= first / ACCELERATION_RATIO and mid <= first:
        return "decelerating"
    return "stable"
