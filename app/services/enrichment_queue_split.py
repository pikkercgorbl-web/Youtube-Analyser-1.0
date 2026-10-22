"""Pass-level backlog vs recent slot split for enrichment queues (Stage 2)."""

from __future__ import annotations


def backlog_and_recent_slot_counts(*, pass_limit: int, backlog_fraction: float) -> tuple[int, int]:
    """Return (recent_slots, backlog_slots) that sum to pass_limit."""
    if pass_limit <= 0:
        return 0, 0
    fraction = min(1.0, max(0.0, float(backlog_fraction)))
    backlog_slots = int(pass_limit * fraction)
    if backlog_slots > pass_limit:
        backlog_slots = pass_limit
    recent_slots = pass_limit - backlog_slots
    return recent_slots, backlog_slots


def pick_with_backlog_quota(
    candidates: list[tuple[tuple, str]],
    *,
    limit: int,
    backlog_fraction: float,
    backlog_band: int = 2,
    band_index: int = 0,
) -> list[str]:
    """
    candidates: sorted list of (priority_key, id); priority_key[band_index] is recency band
    (0=cycle, 1=recent, 2=backlog). Empty backlog or recent pool yields its slots to the other pool.
    """
    if limit <= 0 or not candidates:
        return []

    recent_pool: list[str] = []
    backlog_pool: list[str] = []
    for key, cid in candidates:
        band = key[band_index] if key and len(key) > band_index else backlog_band
        if band >= backlog_band:
            backlog_pool.append(cid)
        else:
            recent_pool.append(cid)

    recent_cap, backlog_cap = backlog_and_recent_slot_counts(
        pass_limit=limit,
        backlog_fraction=backlog_fraction,
    )
    taken_recent = recent_pool[:recent_cap]
    taken_backlog = backlog_pool[:backlog_cap]
    out = taken_recent + taken_backlog
    remaining = limit - len(out)
    if remaining > 0:
        spill_recent = recent_pool[len(taken_recent) :]
        spill_backlog = backlog_pool[len(taken_backlog) :]
        for cid in spill_recent + spill_backlog:
            if remaining <= 0:
                break
            if cid in out:
                continue
            out.append(cid)
            remaining -= 1
    return out[:limit]
