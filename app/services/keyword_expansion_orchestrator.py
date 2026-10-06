"""Safe keyword expansion orchestration with admission policy (Stage 1.20C)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.orm import KeywordExpansionEvent, TargetKeyword
from app.services.keyword_admission_policy import AdmissionBudgetSnapshot, evaluate_keyword_admission
from app.services.keyword_expansion_depth import (
    DEFAULT_MAX_EXPANSION_DEPTH,
    batch_expansion_depths,
    seed_may_expand_at_depth,
)
from app.services.keyword_expansion_filter import filter_candidates
from app.services.keyword_expansion_persistence import persist_admission_decision, record_expansion_event
from app.services.keyword_expansion_config import KeywordExpansionConfig, generate_expansion_run_id, is_source_on_cooldown
from app.services.keyword_expansion_sources import (
    ChannelTopicExpansionSource,
    RelatedQueryExpansionSource,
    SuggestionExpansionSource,
)
from app.services.keyword_expansion_types import KeywordExpansionCandidate, KeywordExpansionSummary, SimpleExpansionContext
from app.services.keyword_scheduling_policy import SOURCE_CHANNEL, SOURCE_RELATED, SOURCE_SUGGESTION
from app.services.keyword_lifecycle_service import count_successful_scans_batch
from app.services.keyword_scheduling_policy import (
    LIFECYCLE_ACTIVE,
    LIFECYCLE_ARCHIVED,
    LIFECYCLE_PROBATION,
    LIFECYCLE_WEAK,
    PROBATION_READY_SCAN_COUNT,
)
from app.services.metrics import utc_now

logger = logging.getLogger(__name__)


def _build_sources(session: Session, config: KeywordExpansionConfig) -> dict[str, object]:
    cap = config.max_candidates_per_source_per_seed
    sources: dict[str, object] = {}
    if SOURCE_SUGGESTION in config.source_types:
        sources[SOURCE_SUGGESTION] = SuggestionExpansionSource(max_suggestions=cap)
    if SOURCE_RELATED in config.source_types:
        sources[SOURCE_RELATED] = RelatedQueryExpansionSource(max_suggestions=cap)
    if SOURCE_CHANNEL in config.source_types:
        sources[SOURCE_CHANNEL] = ChannelTopicExpansionSource(session, max_topics=cap)
    return sources


@dataclass
class KeywordExpansionOrchestratorConfig(KeywordExpansionConfig):
    max_non_archived_pool_size: int | None = None
    max_probation_pool_size: int | None = None
    max_expansion_depth: int = DEFAULT_MAX_EXPANSION_DEPTH


def _pool_counts(session: Session) -> tuple[int, int]:
    non_archived = (
        session.scalar(
            select(func.count())
            .select_from(TargetKeyword)
            .where(TargetKeyword.lifecycle_status != LIFECYCLE_ARCHIVED),
        )
        or 0
    )
    probation = (
        session.scalar(
            select(func.count())
            .select_from(TargetKeyword)
            .where(TargetKeyword.lifecycle_status == LIFECYCLE_PROBATION),
        )
        or 0
    )
    return int(non_archived), int(probation)


def seed_expansion_block_reason(
    record: TargetKeyword,
    *,
    expand_weak: bool,
    successful_scan_count: int,
    expansion_depth: int | None,
    max_expansion_depth: int,
) -> str | None:
    if record.lifecycle_status == LIFECYCLE_ARCHIVED:
        return "seed_archived"
    if record.lifecycle_status == LIFECYCLE_WEAK and not expand_weak:
        return "seed_weak_excluded"
    if not seed_may_expand_at_depth(expansion_depth, max_expansion_depth=max_expansion_depth):
        return "depth_limit"
    if record.lifecycle_status == LIFECYCLE_PROBATION and successful_scan_count < PROBATION_READY_SCAN_COUNT:
        return "seed_not_ready"
    if record.lifecycle_status not in (LIFECYCLE_ACTIVE, LIFECYCLE_PROBATION, LIFECYCLE_WEAK):
        return "seed_ineligible"
    return None


def is_seed_eligible_for_expansion(
    record: TargetKeyword,
    *,
    expand_weak: bool,
    successful_scan_count: int,
    expansion_depth: int | None,
    max_expansion_depth: int,
) -> bool:
    return (
        seed_expansion_block_reason(
            record,
            expand_weak=expand_weak,
            successful_scan_count=successful_scan_count,
            expansion_depth=expansion_depth,
            max_expansion_depth=max_expansion_depth,
        )
        is None
    )


@dataclass(slots=True)
class _RunBudgetState:
    global_accepted: int
    per_parent_accepted: dict[int, int]
    simulated_non_archived: int
    simulated_probation: int


def _budget_snapshot(
    cfg: KeywordExpansionOrchestratorConfig,
    state: _RunBudgetState,
    parent_keyword_id: int,
) -> AdmissionBudgetSnapshot:
    return AdmissionBudgetSnapshot(
        global_accepted_this_run=state.global_accepted,
        global_run_cap=cfg.max_new_keywords_per_expansion_run,
        parent_accepted_this_run=state.per_parent_accepted.get(parent_keyword_id, 0),
        parent_run_cap=cfg.max_new_keywords_per_seed_per_run,
        non_archived_pool_count=state.simulated_non_archived,
        max_non_archived_pool_size=cfg.max_non_archived_pool_size,
        probation_pool_count=state.simulated_probation,
        max_probation_pool_size=cfg.max_probation_pool_size,
    )


async def run_keyword_expansion_orchestrated(
    session: Session,
    seed_keyword_id: int,
    *,
    config: KeywordExpansionOrchestratorConfig | None = None,
    dry_run: bool = False,
    run_id: str | None = None,
    created_this_run: set[int] | None = None,
    global_created_count: dict[str, int] | None = None,
    run_budget_state: _RunBudgetState | None = None,
) -> KeywordExpansionSummary:
    cfg = config or KeywordExpansionOrchestratorConfig()
    started = time.perf_counter()
    reference = utc_now()
    discovery_run_id = run_id or generate_expansion_run_id(now=reference)
    created_ids = created_this_run if created_this_run is not None else set()
    global_counter = global_created_count if global_created_count is not None else {"n": 0}

    seed = session.get(TargetKeyword, seed_keyword_id)
    summary = KeywordExpansionSummary(discovery_run_id=discovery_run_id)
    if seed is None:
        summary.errors = ("seed_not_found",)
        summary.cycle_status = "failed"
        summary.runtime_seconds = round(time.perf_counter() - started, 3)
        return summary

    if seed.id in created_ids:
        summary.errors = ("seed_created_same_run",)
        summary.cycle_status = "failed"
        summary.runtime_seconds = round(time.perf_counter() - started, 3)
        return summary

    scan_counts = count_successful_scans_batch(session, [seed.id])
    depths = batch_expansion_depths(session, [seed.id])
    block = seed_expansion_block_reason(
        seed,
        expand_weak=cfg.expand_weak,
        successful_scan_count=scan_counts.get(seed.id, 0),
        expansion_depth=depths.get(seed.id),
        max_expansion_depth=cfg.max_expansion_depth,
    )
    if block is not None:
        summary.errors = (block,)
        summary.cycle_status = "failed"
        summary.runtime_seconds = round(time.perf_counter() - started, 3)
        return summary

    if run_budget_state is None:
        non_arch, prob = _pool_counts(session)
        run_budget_state = _RunBudgetState(
            global_accepted=global_counter["n"],
            per_parent_accepted={},
            simulated_non_archived=non_arch,
            simulated_probation=prob,
        )

    summary.seed_keyword_count = 1
    context = SimpleExpansionContext(parent_keyword_id=seed.id, parent_keyword=seed.keyword)
    sources = _build_sources(session, cfg)
    summary.source_count = len(sources)

    per_seed_created = 0
    errors: list[str] = []

    for source_type, source in sources.items():
        if is_source_on_cooldown(
            session,
            parent_keyword_id=seed.id,
            source_type=source_type,
            cooldown_days=cfg.cooldown_days,
            now=reference,
        ):
            logger.info(
                "[KEYWORD_EXPANSION] seed=%s source=%s skipped=cooldown",
                seed.keyword,
                source_type,
            )
            continue

        source_started = time.perf_counter()
        try:
            raw_candidates: list[KeywordExpansionCandidate] = await source.expand(seed.keyword, context)
        except Exception as exc:
            errors.append(f"{source_type}:{exc}")
            logger.exception("[KEYWORD_EXPANSION] seed=%s source=%s error", seed.keyword, source_type)
            continue

        summary.raw_candidate_count += len(raw_candidates)
        accepted, rejected = filter_candidates(raw_candidates, parent_keyword=seed.keyword)
        summary.rejected_count += len(rejected)
        if not dry_run:
            for candidate, reason in rejected:
                record_expansion_event(
                    session,
                    parent_keyword_id=seed.id,
                    candidate=candidate,
                    outcome="rejected",
                    rejection_reason=reason,
                    discovery_run_id=discovery_run_id,
                )

        unique_keys: set[str] = set()
        for candidate in accepted:
            key = candidate.normalized_keyword.casefold()
            if key not in unique_keys:
                unique_keys.add(key)
        summary.normalized_unique_count += len(unique_keys)

        created_source = existing_source = deferred_source = rejected_local = 0
        for candidate in accepted:
            budgets = _budget_snapshot(cfg, run_budget_state, seed.id)
            decision = evaluate_keyword_admission(
                session,
                candidate,
                parent_keyword=seed.keyword,
                budgets=budgets,
            )
            outcome = persist_admission_decision(
                session,
                decision,
                candidate,
                parent_keyword=seed.keyword,
                discovery_run_id=discovery_run_id,
                dry_run=dry_run,
            )

            if outcome.outcome == "created":
                if not dry_run and outcome.keyword_id is not None and outcome.keyword_id in created_ids:
                    continue
                if not dry_run and outcome.keyword_id is not None:
                    created_ids.add(outcome.keyword_id)
                created_source += 1
                per_seed_created += 1
                global_counter["n"] += 1
                run_budget_state.global_accepted += 1
                run_budget_state.per_parent_accepted[seed.id] = (
                    run_budget_state.per_parent_accepted.get(seed.id, 0) + 1
                )
                run_budget_state.simulated_non_archived += 1
                run_budget_state.simulated_probation += 1
                summary.created_keyword_count += 1
            elif outcome.outcome == "existing":
                existing_source += 1
                summary.existing_keyword_count += 1
            elif outcome.outcome == "deferred":
                deferred_source += 1
                summary.deferred_count += 1
            else:
                rejected_local += 1
                summary.rejected_count += 1

        summary.per_source_counts[source_type] = summary.per_source_counts.get(source_type, 0) + created_source
        logger.info(
            "[KEYWORD_EXPANSION] seed=%s source=%s raw=%s created=%s existing=%s deferred=%s rejected=%s duration=%s",
            seed.keyword,
            source_type,
            len(raw_candidates),
            created_source,
            existing_source,
            deferred_source,
            len(rejected) + rejected_local,
            round(time.perf_counter() - source_started, 3),
        )

    summary.per_seed_counts[seed.id] = per_seed_created
    summary.errors = tuple(errors)
    summary.runtime_seconds = round(time.perf_counter() - started, 3)
    summary.cycle_status = "failed" if errors and summary.created_keyword_count == 0 else "ok"
    if dry_run:
        summary.cycle_status = "dry_run"
    return summary


async def run_keyword_expansion_orchestrated_batch(
    session: Session,
    keyword_ids: list[int],
    *,
    config: KeywordExpansionOrchestratorConfig | None = None,
    dry_run: bool = False,
) -> KeywordExpansionSummary:
    cfg = config or KeywordExpansionOrchestratorConfig()
    started = time.perf_counter()
    run_id = generate_expansion_run_id()
    created_this_run: set[int] = set()
    global_counter = {"n": 0}
    non_arch, prob = _pool_counts(session)
    run_budget_state = _RunBudgetState(
        global_accepted=0,
        per_parent_accepted={},
        simulated_non_archived=non_arch,
        simulated_probation=prob,
    )
    aggregate = KeywordExpansionSummary(discovery_run_id=run_id)
    errors: list[str] = []

    frozen_seed_ids = keyword_ids[: max(1, cfg.max_seeds_per_batch)]
    aggregate.seed_keyword_count = len(frozen_seed_ids)

    for seed_id in frozen_seed_ids:
        partial = await run_keyword_expansion_orchestrated(
            session,
            seed_id,
            config=cfg,
            dry_run=dry_run,
            run_id=run_id,
            created_this_run=created_this_run,
            global_created_count=global_counter,
            run_budget_state=run_budget_state,
        )
        aggregate.raw_candidate_count += partial.raw_candidate_count
        aggregate.normalized_unique_count += partial.normalized_unique_count
        aggregate.existing_keyword_count += partial.existing_keyword_count
        aggregate.rejected_count += partial.rejected_count
        aggregate.deferred_count += partial.deferred_count
        aggregate.created_keyword_count += partial.created_keyword_count
        aggregate.source_count = max(aggregate.source_count, partial.source_count)
        errors.extend(partial.errors)
        for key, value in partial.per_source_counts.items():
            aggregate.per_source_counts[key] = aggregate.per_source_counts.get(key, 0) + value
        aggregate.per_seed_counts.update(partial.per_seed_counts)

    aggregate.errors = tuple(errors)
    aggregate.runtime_seconds = round(time.perf_counter() - started, 3)
    aggregate.cycle_status = "dry_run" if dry_run else ("partial" if errors else "ok")
    logger.info(
        "[KEYWORD_EXPANSION_RUN] run_id=%s seeds=%s raw=%s created=%s existing=%s deferred=%s rejected=%s status=%s duration=%s",
        run_id,
        aggregate.seed_keyword_count,
        aggregate.raw_candidate_count,
        aggregate.created_keyword_count,
        aggregate.existing_keyword_count,
        aggregate.deferred_count,
        aggregate.rejected_count,
        aggregate.cycle_status,
        aggregate.runtime_seconds,
    )
    return aggregate
