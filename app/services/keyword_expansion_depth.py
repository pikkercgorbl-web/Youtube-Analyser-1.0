"""Expansion depth derived from parent_keyword_id chain (Stage 1.20C). No DB column."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import TargetKeyword

MAX_PARENT_WALK_HOPS = 32
DEFAULT_MAX_EXPANSION_DEPTH = 2


def compute_expansion_depth_for_record(
    record: TargetKeyword,
    *,
    parent_by_id: dict[int, TargetKeyword],
) -> int | None:
    """
    Root seed/manual (no parent) → 0; each child → parent depth + 1.
    Returns None if parent chain is broken or a cycle is detected.
    """
    if record.parent_keyword_id is None:
        return 0
    depth = 0
    visited: set[int] = set()
    node = record
    while node.parent_keyword_id is not None:
        pid = node.parent_keyword_id
        if pid in visited:
            return None
        visited.add(pid)
        depth += 1
        parent = parent_by_id.get(pid)
        if parent is None:
            return None
        node = parent
        if depth > MAX_PARENT_WALK_HOPS:
            return None
    return depth


def load_parent_map(session: Session, keyword_ids: list[int]) -> dict[int, TargetKeyword]:
    """Batch-load keywords and their ancestors for depth computation."""
    if not keyword_ids:
        return {}
    loaded: dict[int, TargetKeyword] = {}
    frontier = set(keyword_ids)
    hops = 0
    while frontier and hops <= MAX_PARENT_WALK_HOPS:
        rows = session.scalars(select(TargetKeyword).where(TargetKeyword.id.in_(frontier))).all()
        next_frontier: set[int] = set()
        for row in rows:
            loaded[row.id] = row
            if row.parent_keyword_id is not None and row.parent_keyword_id not in loaded:
                next_frontier.add(row.parent_keyword_id)
        frontier = next_frontier
        hops += 1
    return loaded


def batch_expansion_depths(
    session: Session,
    keyword_ids: list[int],
) -> dict[int, int | None]:
    parent_map = load_parent_map(session, keyword_ids)
    out: dict[int, int | None] = {}
    for kid in keyword_ids:
        record = parent_map.get(kid)
        if record is None:
            out[kid] = None
        else:
            out[kid] = compute_expansion_depth_for_record(record, parent_by_id=parent_map)
    return out


def seed_may_expand_at_depth(depth: int | None, *, max_expansion_depth: int) -> bool:
    """
    Policy: only keywords with depth strictly less than max_expansion_depth may expand.
    max_expansion_depth=2 → depths 0 and 1 may expand; depth 2 may not.
    """
    if depth is None:
        return False
    return depth < max_expansion_depth
