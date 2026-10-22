"""Post-discovery keyword expansion pass (Stage 5 — separate session, optional)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import TargetKeyword
from app.services.discovery_cycle import DiscoveryCycleSummary
from app.services.keyword_expansion_config import KeywordExpansionConfig
from app.services.keyword_expansion_orchestrator import (
    KeywordExpansionOrchestratorConfig,
    seed_expansion_block_reason,
)
from app.services.keyword_expansion_service import run_keyword_expansion_batch
from app.services.keyword_expansion_types import KeywordExpansionSummary
from app.services.keyword_lifecycle_service import count_successful_scans_batch
from app.services.keyword_expansion_depth import batch_expansion_depths

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class KeywordExpansionDiscoveryPassContext:
    discovery_run_id: str
    seed_keyword_ids: tuple[int, ...] = ()


@dataclass
class KeywordExpansionDiscoveryPassReport:
    discovery_run_id: str
    expansion_run_id: str | None = None
    selected_seed_count: int = 0
    skipped_seed_count: int = 0
    skip_reasons: dict[str, int] = field(default_factory=dict)
    summary: KeywordExpansionSummary | None = None
    errors: tuple[str, ...] = ()


def select_expansion_seeds_from_cycle(
    session: Session,
    summary: DiscoveryCycleSummary,
    *,
    config: KeywordExpansionOrchestratorConfig | None = None,
) -> tuple[list[int], dict[str, int]]:
    """
    Seeds = keywords that completed discovery successfully in this cycle (status ok).
    Re-applies orchestrator seed gates (lifecycle, depth, probation scans) without calling sources.
    """
    cfg = config or KeywordExpansionOrchestratorConfig()
    candidate_ids: list[int] = []
    for row in summary.keyword_summaries:
        if row.status != "ok":
            continue
        candidate_ids.append(row.keyword_id)

    if not candidate_ids:
        return [], {}

    scan_counts = count_successful_scans_batch(session, candidate_ids)
    depths = batch_expansion_depths(session, candidate_ids)

    records = {
        r.id: r
        for r in session.scalars(select(TargetKeyword).where(TargetKeyword.id.in_(candidate_ids))).all()
    }

    eligible: list[int] = []
    skip_reasons: dict[str, int] = {}
    for kid in candidate_ids:
        record = records.get(kid)
        if record is None:
            skip_reasons["seed_not_found"] = skip_reasons.get("seed_not_found", 0) + 1
            continue
        block = seed_expansion_block_reason(
            record,
            expand_weak=cfg.expand_weak,
            successful_scan_count=scan_counts.get(kid, 0),
            expansion_depth=depths.get(kid),
            max_expansion_depth=cfg.max_expansion_depth,
        )
        if block is not None:
            skip_reasons[block] = skip_reasons.get(block, 0) + 1
            continue
        eligible.append(kid)

    return eligible, skip_reasons


async def run_keyword_expansion_discovery_pass_async(
    session: Session,
    *,
    cycle_summary: DiscoveryCycleSummary,
    config: KeywordExpansionConfig | None = None,
    dry_run: bool = False,
) -> KeywordExpansionDiscoveryPassReport:
    from app.services.keyword_expansion_service import _to_orchestrator_config

    orch_cfg = _to_orchestrator_config(config)

    eligible, skip_reasons = select_expansion_seeds_from_cycle(
        session,
        cycle_summary,
        config=orch_cfg,
    )
    report = KeywordExpansionDiscoveryPassReport(
        discovery_run_id=cycle_summary.run_id,
        selected_seed_count=len(eligible),
        skipped_seed_count=sum(skip_reasons.values()),
        skip_reasons=skip_reasons,
    )

    if not eligible:
        logger.info(
            "[KEYWORD_EXPANSION_PASS] discovery_run_id=%s seeds=0 skipped=%s",
            cycle_summary.run_id,
            report.skipped_seed_count,
        )
        return report

    expansion_summary = await run_keyword_expansion_batch(
        session,
        eligible,
        config=orch_cfg,
        dry_run=dry_run,
    )
    report.expansion_run_id = expansion_summary.discovery_run_id
    report.summary = expansion_summary
    report.errors = expansion_summary.errors

    logger.info(
        "[KEYWORD_EXPANSION_PASS] discovery_run_id=%s expansion_run_id=%s seeds=%s created=%s "
        "existing=%s deferred=%s rejected=%s status=%s",
        cycle_summary.run_id,
        expansion_summary.discovery_run_id,
        expansion_summary.seed_keyword_count,
        expansion_summary.created_keyword_count,
        expansion_summary.existing_keyword_count,
        expansion_summary.deferred_count,
        expansion_summary.rejected_count,
        expansion_summary.cycle_status,
    )
    return report


def run_keyword_expansion_discovery_pass(
    session: Session,
    *,
    cycle_summary: DiscoveryCycleSummary,
    config: KeywordExpansionConfig | None = None,
    dry_run: bool = False,
) -> KeywordExpansionDiscoveryPassReport:
    import asyncio

    return asyncio.run(
        run_keyword_expansion_discovery_pass_async(
            session,
            cycle_summary=cycle_summary,
            config=config,
            dry_run=dry_run,
        ),
    )
