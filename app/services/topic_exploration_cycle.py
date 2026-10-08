"""Wire exploration queries into discovery cycle config (Stage 6)."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.topic_exploration_queries import (
    TopicExplorationQuery,
    default_example_queries_path,
    load_topic_exploration_queries,
    select_exploration_queries_for_cycle,
)
from app.services.topic_exploration_runtime_config import TopicExplorationRuntimeSettings


@dataclass(frozen=True, slots=True)
class TopicExplorationCyclePlan:
    enabled: bool
    batch_fraction: float
    max_pages_per_query: int
    queries: tuple[TopicExplorationQuery, ...] = ()
    cycle_index: int = 0


def build_topic_exploration_cycle_plan(
    settings: TopicExplorationRuntimeSettings | None = None,
    *,
    cycle_index: int = 0,
) -> TopicExplorationCyclePlan:
    cfg = settings or TopicExplorationRuntimeSettings()
    if not cfg.topic_exploration_in_discovery:
        return TopicExplorationCyclePlan(
            enabled=False,
            batch_fraction=cfg.topic_exploration_batch_fraction,
            max_pages_per_query=cfg.topic_exploration_max_pages_per_query,
        )

    path = cfg.topic_exploration_queries_file
    if not path:
        path = str(default_example_queries_path())
    try:
        queries = load_topic_exploration_queries(path)
    except OSError:
        queries = ()

    return TopicExplorationCyclePlan(
        enabled=True,
        batch_fraction=cfg.topic_exploration_batch_fraction,
        max_pages_per_query=max(1, cfg.topic_exploration_max_pages_per_query),
        queries=queries,
        cycle_index=cycle_index,
    )


def queries_for_exploration_slots(
    plan: TopicExplorationCyclePlan,
    exploration_slots: int,
) -> tuple[TopicExplorationQuery, ...]:
    if not plan.enabled or exploration_slots <= 0:
        return ()
    return select_exploration_queries_for_cycle(
        plan.queries,
        slot_count=exploration_slots,
        cycle_index=plan.cycle_index,
    )
