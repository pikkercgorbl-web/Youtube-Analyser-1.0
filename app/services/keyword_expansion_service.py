"""Keyword expansion orchestration (Stage 1.16C)."""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.orm import KeywordExpansionEvent, TargetKeyword
from app.services.keyword_expansion_filter import filter_candidates
from app.services.keyword_expansion_persistence import persist_expansion_candidate, record_expansion_event
from app.services.keyword_expansion_sources import (
    ChannelTopicExpansionSource,
    RelatedQueryExpansionSource,
    SuggestionExpansionSource,
)
from app.services.keyword_expansion_types import (
    KeywordExpansionCandidate,
    KeywordExpansionSummary,
    SimpleExpansionContext,
)
from app.services.keyword_scheduling_policy import (
    LIFECYCLE_ACTIVE,
    LIFECYCLE_ARCHIVED,
    LIFECYCLE_PROBATION,
    LIFECYCLE_WEAK,
    SOURCE_CHANNEL,
    SOURCE_RELATED,
    SOURCE_SUGGESTION,
)
from app.services.metrics import ensure_utc, utc_now

logger = logging.getLogger(__name__)


@dataclass
class KeywordExpansionConfig:
    max_candidates_per_source_per_seed: int = 20
    max_new_keywords_per_seed_per_run: int = 10
    max_new_keywords_per_expansion_run: int = 50
    cooldown_days: float = 7.0
    expand_weak: bool = False
    max_seeds_per_batch: int = 10
    source_types: tuple[str, ...] = (SOURCE_SUGGESTION, SOURCE_RELATED, SOURCE_CHANNEL)


def generate_expansion_run_id(*, now: datetime | None = None) -> str:
    reference = now or utc_now()
    stamp = reference.strftime("%Y%m%dT%H%M%SZ")
    return f"expansion_{stamp}_{secrets.token_hex(4)}"


def is_seed_eligible(record: TargetKeyword, *, expand_weak: bool) -> bool:
    if record.lifecycle_status == LIFECYCLE_ARCHIVED:
        return False
    if record.lifecycle_status == LIFECYCLE_WEAK and not expand_weak:
        return False
    return record.lifecycle_status in (LIFECYCLE_ACTIVE, LIFECYCLE_PROBATION, LIFECYCLE_WEAK)


def is_source_on_cooldown(
    session: Session,
    *,
    parent_keyword_id: int,
    source_type: str,
    cooldown_days: float,
    now: datetime | None = None,
) -> bool:
    reference = now or utc_now()
    cutoff = reference - timedelta(days=cooldown_days)
    last_at = session.scalar(
        select(func.max(KeywordExpansionEvent.discovered_at)).where(
            KeywordExpansionEvent.parent_keyword_id == parent_keyword_id,
            KeywordExpansionEvent.source_type == source_type,
        ),
    )
    if last_at is None:
        return False
    return ensure_utc(last_at) > ensure_utc(cutoff)


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
    cfg = config or KeywordExpansionConfig()
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

    if not is_seed_eligible(seed, expand_weak=cfg.expand_weak):
        summary.errors = ("seed_ineligible",)
        summary.cycle_status = "failed"
        summary.runtime_seconds = round(time.perf_counter() - started, 3)
        return summary

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

        created_source = existing_source = rejected_local = 0
        for candidate in accepted:
            if global_counter["n"] >= cfg.max_new_keywords_per_expansion_run:
                break
            if per_seed_created >= cfg.max_new_keywords_per_seed_per_run:
                break

            outcome = persist_expansion_candidate(
                session,
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
                summary.created_keyword_count += 1
            elif outcome.outcome == "existing":
                existing_source += 1
                summary.existing_keyword_count += 1
            else:
                rejected_local += 1

        summary.rejected_count += rejected_local
        summary.per_source_counts[source_type] = summary.per_source_counts.get(source_type, 0) + created_source
        logger.info(
            "[KEYWORD_EXPANSION] seed=%s source=%s raw=%s created=%s existing=%s rejected=%s duration=%s",
            seed.keyword,
            source_type,
            len(raw_candidates),
            created_source,
            existing_source,
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


async def run_keyword_expansion_batch(
    session: Session,
    keyword_ids: list[int],
    *,
    config: KeywordExpansionConfig | None = None,
    dry_run: bool = False,
) -> KeywordExpansionSummary:
    cfg = config or KeywordExpansionConfig()
    started = time.perf_counter()
    run_id = generate_expansion_run_id()
    created_this_run: set[int] = set()
    global_counter = {"n": 0}
    aggregate = KeywordExpansionSummary(discovery_run_id=run_id)
    errors: list[str] = []

    limited_ids = keyword_ids[: max(1, cfg.max_seeds_per_batch)]
    aggregate.seed_keyword_count = len(limited_ids)

    for seed_id in limited_ids:
        partial = await run_keyword_expansion(
            session,
            seed_id,
            config=cfg,
            dry_run=dry_run,
            run_id=run_id,
            created_this_run=created_this_run,
            global_created_count=global_counter,
        )
        aggregate.raw_candidate_count += partial.raw_candidate_count
        aggregate.normalized_unique_count += partial.normalized_unique_count
        aggregate.existing_keyword_count += partial.existing_keyword_count
        aggregate.rejected_count += partial.rejected_count
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
        "[KEYWORD_EXPANSION_RUN] run_id=%s seeds=%s raw=%s created=%s existing=%s rejected=%s status=%s duration=%s",
        run_id,
        aggregate.seed_keyword_count,
        aggregate.raw_candidate_count,
        aggregate.created_keyword_count,
        aggregate.existing_keyword_count,
        aggregate.rejected_count,
        aggregate.cycle_status,
        aggregate.runtime_seconds,
    )
    return aggregate


def run_keyword_expansion_sync(session: Session, seed_keyword_id: int, **kwargs) -> KeywordExpansionSummary:
    return asyncio.run(run_keyword_expansion(session, seed_keyword_id, **kwargs))


def run_keyword_expansion_batch_sync(session: Session, keyword_ids: list[int], **kwargs) -> KeywordExpansionSummary:
    return asyncio.run(run_keyword_expansion_batch(session, keyword_ids, **kwargs))
