"""Age-aligned VPH from stored VideoSnapshot rows (Channel Momentum).

Horizon is measured from ``published_at``, not keyword ``discovered_at``.
Historical views are never inferred from the latest snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.models.orm import VideoSnapshot
from app.services.metrics import ensure_utc

# Default 24h horizon with ±6h tolerance:
# - Monitoring revisits for young regular videos are typically spaced a few hours apart;
#   6h is ~25% of 24h, comparable to the 72h keyword horizon using ±12h (~17%).
# - Tighter tolerance would exclude many real captures; wider would blur "same age" comparison.
DEFAULT_MOMENTUM_HORIZON_HOURS = 24
DEFAULT_MOMENTUM_HORIZON_TOLERANCE_HOURS = 6.0


@dataclass(frozen=True, slots=True)
class AgeAlignedVphMeasurement:
    video_id: str
    vph: float
    target_age_hours: float
    actual_age_hours: float
    snapshot_captured_at: datetime
    views: int


def select_age_aligned_measurement(
    *,
    video_id: str,
    published_at: datetime,
    snapshots: list[VideoSnapshot],
    horizon_hours: float = DEFAULT_MOMENTUM_HORIZON_HOURS,
    tolerance_hours: float = DEFAULT_MOMENTUM_HORIZON_TOLERANCE_HOURS,
) -> AgeAlignedVphMeasurement | None:
    """Pick the snapshot closest to ``published_at + horizon_hours`` within tolerance."""
    published = ensure_utc(published_at)
    target = published + timedelta(hours=horizon_hours)
    tolerance = timedelta(hours=tolerance_hours)
    best: tuple[timedelta, datetime, int, VideoSnapshot] | None = None
    for snap in snapshots:
        if snap.views is None:
            continue
        captured = ensure_utc(snap.captured_at)
        delta = abs(captured - target)
        if delta > tolerance:
            continue
        tie = (delta, captured, int(snap.id), snap)
        if best is None or tie[:3] < best[:3]:
            best = tie
    if best is None:
        return None
    snap = best[3]
    captured = ensure_utc(snap.captured_at)
    actual_age_hours = (captured - published).total_seconds() / 3600.0
    if actual_age_hours <= 0:
        return None
    views = int(snap.views)
    vph = round(views / actual_age_hours, 4)
    return AgeAlignedVphMeasurement(
        video_id=video_id,
        vph=vph,
        target_age_hours=float(horizon_hours),
        actual_age_hours=round(actual_age_hours, 4),
        snapshot_captured_at=captured,
        views=views,
    )
