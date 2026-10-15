"""Honest views measurement status for pattern member hydration (Fix 2C)."""

from __future__ import annotations


def views_measurement_status(
    *,
    in_winner_snapshot: bool,
    views: int | None,
    has_snapshot: bool,
) -> str:
    if in_winner_snapshot:
        if views is None:
            return "unknown_in_winner_snapshot"
        if views == 0:
            return "zero_in_winner_snapshot"
        return "from_winner_snapshot"
    if not has_snapshot:
        return "missing_snapshot"
    if views is None:
        return "unknown_in_snapshot"
    if views == 0:
        return "zero_in_snapshot"
    return "from_snapshot"
