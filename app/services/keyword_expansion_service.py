"""Keyword expansion orchestration (Stage 1.16C + 1.20C admission)."""

from __future__ import annotations

import asyncio
from dataclasses import fields

from sqlalchemy.orm import Session

from app.models.orm import TargetKeyword
from app.services.keyword_expansion_config import (
    KeywordExpansionConfig,
    generate_expansion_run_id,
    is_source_on_cooldown,
)
from app.services.keyword_expansion_orchestrator import (
    KeywordExpansionOrchestratorConfig,
    is_seed_eligible_for_expansion,
    run_keyword_expansion_orchestrated,
    run_keyword_expansion_orchestrated_batch,
    seed_expansion_block_reason,
)
from app.services.keyword_expansion_types import KeywordExpansionSummary
from app.services.keyword_scheduling_policy import (
    LIFECYCLE_ACTIVE,
    LIFECYCLE_ARCHIVED,
    LIFECYCLE_PROBATION,
    LIFECYCLE_WEAK,
)
def _to_orchestrator_config(config: KeywordExpansionConfig | None) -> KeywordExpansionOrchestratorConfig:
    cfg = config or KeywordExpansionConfig()
    base = {f.name: getattr(cfg, f.name) for f in fields(KeywordExpansionConfig)}
    if isinstance(cfg, KeywordExpansionOrchestratorConfig):
        for f in fields(KeywordExpansionOrchestratorConfig):
            if f.name not in base:
                base[f.name] = getattr(cfg, f.name)
    return KeywordExpansionOrchestratorConfig(**base)


def is_seed_eligible(record: TargetKeyword, *, expand_weak: bool) -> bool:
    """Broad lifecycle check (legacy). Orchestrator applies scan/depth gates."""
    if record.lifecycle_status == LIFECYCLE_ARCHIVED:
        return False
    if record.lifecycle_status == LIFECYCLE_WEAK and not expand_weak:
        return False
    return record.lifecycle_status in (LIFECYCLE_ACTIVE, LIFECYCLE_PROBATION, LIFECYCLE_WEAK)


async def run_keyword_expansion(
    session: Session,
    seed_keyword_id: int,
    *,
    config: KeywordExpansionConfig | None = None,
    dry_run: bool = False,
    run_id: str | None = None,
    created_this_run: set[int] | None = None,
    global_created_count: dict[str, int] | None = None,
) -> KeywordExpansionSummary:
    return await run_keyword_expansion_orchestrated(
        session,
        seed_keyword_id,
        config=_to_orchestrator_config(config),
        dry_run=dry_run,
        run_id=run_id,
        created_this_run=created_this_run,
        global_created_count=global_created_count,
    )


async def run_keyword_expansion_batch(
    session: Session,
    keyword_ids: list[int],
    *,
    config: KeywordExpansionConfig | None = None,
    dry_run: bool = False,
) -> KeywordExpansionSummary:
    return await run_keyword_expansion_orchestrated_batch(
        session,
        keyword_ids,
        config=_to_orchestrator_config(config),
        dry_run=dry_run,
    )


def run_keyword_expansion_sync(session: Session, seed_keyword_id: int, **kwargs) -> KeywordExpansionSummary:
    return asyncio.run(run_keyword_expansion(session, seed_keyword_id, **kwargs))


def run_keyword_expansion_batch_sync(session: Session, keyword_ids: list[int], **kwargs) -> KeywordExpansionSummary:
    return asyncio.run(run_keyword_expansion_batch(session, keyword_ids, **kwargs))


__all__ = [
    "KeywordExpansionConfig",
    "generate_expansion_run_id",
    "is_seed_eligible",
    "is_seed_eligible_for_expansion",
    "is_source_on_cooldown",
    "run_keyword_expansion",
    "run_keyword_expansion_batch",
    "run_keyword_expansion_sync",
    "run_keyword_expansion_batch_sync",
    "seed_expansion_block_reason",
]
