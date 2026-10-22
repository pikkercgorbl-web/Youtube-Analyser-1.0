"""Load editable exploration query definitions (JSON file — not auto-imported to DB)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


EXPLORATION_QUERY_KIND = "exploration"
DEFAULT_EXPLORATION_SCHEDULE = "every_discovery_cycle"


@dataclass(frozen=True, slots=True)
class TopicExplorationQuery:
    query_id: str
    query_text: str
    direction: str
    enabled: bool
    schedule: str
    kind: str = EXPLORATION_QUERY_KIND


def load_topic_exploration_queries(path: str | Path) -> tuple[TopicExplorationQuery, ...]:
    file_path = Path(path)
    raw = json.loads(file_path.read_text(encoding="utf-8"))
    defaults = raw.get("defaults") or {}
    default_kind = str(defaults.get("kind", EXPLORATION_QUERY_KIND))
    default_schedule = str(defaults.get("schedule", DEFAULT_EXPLORATION_SCHEDULE))
    default_enabled = bool(defaults.get("enabled", False))

    queries: list[TopicExplorationQuery] = []
    for row in raw.get("queries") or []:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("kind", default_kind))
        if kind != EXPLORATION_QUERY_KIND:
            continue
        query_id = str(row.get("id", "")).strip()
        query_text = str(row.get("query", "")).strip()
        if not query_id or not query_text:
            continue
        enabled = bool(row.get("enabled", default_enabled))
        queries.append(
            TopicExplorationQuery(
                query_id=query_id,
                query_text=query_text,
                direction=str(row.get("direction", "")).strip(),
                enabled=enabled,
                schedule=str(row.get("schedule", default_schedule)).strip(),
                kind=kind,
            ),
        )
    return tuple(queries)


def select_exploration_queries_for_cycle(
    queries: tuple[TopicExplorationQuery, ...],
    *,
    slot_count: int,
    cycle_index: int = 0,
) -> tuple[TopicExplorationQuery, ...]:
    """Round-robin enabled queries across exploration slots."""
    enabled = [q for q in queries if q.enabled]
    if slot_count <= 0 or not enabled:
        return ()
    picked: list[TopicExplorationQuery] = []
    start = cycle_index % len(enabled)
    for i in range(slot_count):
        picked.append(enabled[(start + i) % len(enabled)])
    return tuple(picked)


def default_example_queries_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "topic_exploration_queries.example.json"
