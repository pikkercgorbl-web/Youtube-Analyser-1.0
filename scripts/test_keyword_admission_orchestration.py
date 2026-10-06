"""Tests for keyword admission + safe expansion orchestration (Stage 1.20C)."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.models.orm import KeywordExpansionEvent, KeywordScanRun, TargetKeyword
from app.services.keyword_admission_policy import AdmissionBudgetSnapshot, evaluate_keyword_admission
from app.services.keyword_expansion_depth import batch_expansion_depths
from app.services.keyword_expansion_orchestrator import (
    KeywordExpansionOrchestratorConfig,
    is_seed_eligible_for_expansion,
    run_keyword_expansion_orchestrated,
    run_keyword_expansion_orchestrated_batch,
    seed_expansion_block_reason,
)
from app.services.keyword_expansion_persistence import persist_admission_decision
from app.services.keyword_expansion_sources import SuggestionExpansionSource
from app.services.keyword_expansion_types import KeywordExpansionCandidate
from app.services.keyword_lifecycle_service import count_successful_scans_batch, normalize_keyword_text
from app.services.keyword_scheduling_policy import (
    LIFECYCLE_ACTIVE,
    LIFECYCLE_ARCHIVED,
    LIFECYCLE_PROBATION,
    LIFECYCLE_WEAK,
    PROBATION_READY_SCAN_COUNT,
    SOURCE_SUGGESTION,
)

UTC = timezone.utc


def _engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


def _session():
    return sessionmaker(bind=_engine())()


def _candidate(text: str, *, parent_id: int, parent: str) -> KeywordExpansionCandidate:
    return KeywordExpansionCandidate(
        keyword=text,
        normalized_keyword=normalize_keyword_text(text),
        source_type=SOURCE_SUGGESTION,
        parent_keyword_id=parent_id,
        parent_keyword=parent,
        discovered_at=datetime.now(UTC),
    )


def _add_ok_scans(session, keyword_id: int, n: int) -> None:
    for i in range(n):
        session.add(
            KeywordScanRun(
                keyword_id=keyword_id,
                discovery_run_id=f"scan_{keyword_id}_{i}",
                status="ok",
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
            ),
        )


async def _fake_one(_self, seed_keyword, context):
    return [_candidate(f"{seed_keyword}-child", parent_id=context.parent_keyword_id, parent=seed_keyword)]


def test_archived_seed_cannot_expand() -> None:
    session = _session()
    archived = TargetKeyword(keyword="arch", lifecycle_status=LIFECYCLE_ARCHIVED, source_type="seed")
    session.add(archived)
    session.commit()
    reason = seed_expansion_block_reason(
        archived,
        expand_weak=False,
        successful_scan_count=10,
        expansion_depth=0,
        max_expansion_depth=2,
    )
    assert reason == "seed_archived"


def test_weak_seed_excluded_by_default() -> None:
    session = _session()
    weak = TargetKeyword(keyword="weak", lifecycle_status=LIFECYCLE_WEAK, source_type="seed")
    session.add(weak)
    session.commit()
    assert seed_expansion_block_reason(weak, expand_weak=False, successful_scan_count=5, expansion_depth=0, max_expansion_depth=2)
    assert (
        seed_expansion_block_reason(weak, expand_weak=True, successful_scan_count=5, expansion_depth=0, max_expansion_depth=2)
        is None
    )


def test_fresh_probation_not_ready() -> None:
    prob = TargetKeyword(keyword="prob", lifecycle_status=LIFECYCLE_PROBATION, source_type="suggestion")
    assert (
        seed_expansion_block_reason(
            prob,
            expand_weak=False,
            successful_scan_count=0,
            expansion_depth=1,
            max_expansion_depth=2,
        )
        == "seed_not_ready"
    )


def test_probation_with_scans_eligible() -> None:
    session = _session()
    prob = TargetKeyword(keyword="prob", lifecycle_status=LIFECYCLE_PROBATION, source_type="suggestion")
    session.add(prob)
    session.commit()
    _add_ok_scans(session, prob.id, PROBATION_READY_SCAN_COUNT)
    session.commit()
    counts = count_successful_scans_batch(session, [prob.id])
    assert counts[prob.id] >= PROBATION_READY_SCAN_COUNT
    assert (
        seed_expansion_block_reason(
            prob,
            expand_weak=False,
            successful_scan_count=counts[prob.id],
            expansion_depth=1,
            max_expansion_depth=2,
        )
        is None
    )


def test_active_seed_eligible() -> None:
    active = TargetKeyword(keyword="act", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    assert (
        seed_expansion_block_reason(active, expand_weak=False, successful_scan_count=0, expansion_depth=0, max_expansion_depth=2)
        is None
    )


def test_depth_limit_blocks() -> None:
    session = _session()
    root = TargetKeyword(keyword="root", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    session.add(root)
    session.flush()
    child = TargetKeyword(
        keyword="child",
        lifecycle_status=LIFECYCLE_ACTIVE,
        source_type="suggestion",
        parent_keyword_id=root.id,
    )
    session.add(child)
    session.flush()
    grand = TargetKeyword(
        keyword="grand",
        lifecycle_status=LIFECYCLE_ACTIVE,
        source_type="suggestion",
        parent_keyword_id=child.id,
    )
    session.add(grand)
    session.commit()
    depths = batch_expansion_depths(session, [grand.id])
    assert depths[grand.id] == 2
    assert seed_expansion_block_reason(grand, expand_weak=False, successful_scan_count=0, expansion_depth=2, max_expansion_depth=2)


def test_same_as_parent_rejected() -> None:
    session = _session()
    seed = TargetKeyword(keyword="gaming", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    session.add(seed)
    session.commit()
    decision = evaluate_keyword_admission(
        session,
        _candidate("gaming", parent_id=seed.id, parent=seed.keyword),
        parent_keyword=seed.keyword,
    )
    assert decision.decision == "reject"
    assert decision.reason_code == "same_as_parent"


def test_existing_keyword() -> None:
    session = _session()
    seed = TargetKeyword(keyword="seed", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    existing = TargetKeyword(keyword="known", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    session.add_all([seed, existing])
    session.commit()
    decision = evaluate_keyword_admission(
        session,
        _candidate("known", parent_id=seed.id, parent=seed.keyword),
        parent_keyword=seed.keyword,
    )
    assert decision.decision == "existing"
    assert decision.reason_code == "existing_keyword"


def test_existing_archived() -> None:
    session = _session()
    seed = TargetKeyword(keyword="seed", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    archived = TargetKeyword(keyword="old", lifecycle_status=LIFECYCLE_ARCHIVED, source_type="seed")
    session.add_all([seed, archived])
    session.commit()
    decision = evaluate_keyword_admission(
        session,
        _candidate("old", parent_id=seed.id, parent=seed.keyword),
        parent_keyword=seed.keyword,
    )
    assert decision.decision == "existing"
    assert decision.reason_code == "existing_archived"
    assert decision.admission_context.existing_lifecycle_status == LIFECYCLE_ARCHIVED


def test_pool_budget_deferred() -> None:
    session = _session()
    seed = TargetKeyword(keyword="seed", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    session.add(seed)
    session.commit()
    budgets = AdmissionBudgetSnapshot(
        global_accepted_this_run=0,
        global_run_cap=50,
        parent_accepted_this_run=0,
        parent_run_cap=10,
        non_archived_pool_count=100,
        max_non_archived_pool_size=100,
        probation_pool_count=0,
        max_probation_pool_size=None,
    )
    decision = evaluate_keyword_admission(
        session,
        _candidate("new term", parent_id=seed.id, parent=seed.keyword),
        parent_keyword=seed.keyword,
        budgets=budgets,
    )
    assert decision.decision == "defer"
    assert decision.reason_code == "pool_budget_exhausted"


def test_parent_budget_deferred() -> None:
    session = _session()
    seed = TargetKeyword(keyword="seed", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    session.add(seed)
    session.commit()
    budgets = AdmissionBudgetSnapshot(
        global_accepted_this_run=0,
        global_run_cap=50,
        parent_accepted_this_run=10,
        parent_run_cap=10,
        non_archived_pool_count=1,
        max_non_archived_pool_size=None,
        probation_pool_count=0,
        max_probation_pool_size=None,
    )
    decision = evaluate_keyword_admission(
        session,
        _candidate("another", parent_id=seed.id, parent=seed.keyword),
        parent_keyword=seed.keyword,
        budgets=budgets,
    )
    assert decision.decision == "defer"
    assert decision.reason_code == "parent_budget_exhausted"


def test_global_budget_deferred() -> None:
    session = _session()
    seed = TargetKeyword(keyword="seed", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    session.add(seed)
    session.commit()
    budgets = AdmissionBudgetSnapshot(
        global_accepted_this_run=50,
        global_run_cap=50,
        parent_accepted_this_run=0,
        parent_run_cap=10,
        non_archived_pool_count=1,
        max_non_archived_pool_size=None,
        probation_pool_count=0,
        max_probation_pool_size=None,
    )
    decision = evaluate_keyword_admission(
        session,
        _candidate("global cap term", parent_id=seed.id, parent=seed.keyword),
        parent_keyword=seed.keyword,
        budgets=budgets,
    )
    assert decision.decision == "defer"
    assert decision.reason_code == "global_budget_exhausted"


def test_filter_rejection() -> None:
    session = _session()
    seed = TargetKeyword(keyword="seed", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    session.add(seed)
    session.commit()
    decision = evaluate_keyword_admission(
        session,
        _candidate("12", parent_id=seed.id, parent=seed.keyword),
        parent_keyword=seed.keyword,
    )
    assert decision.decision == "reject"
    assert decision.reason_code == "filtered_noise"


def test_created_probation_provenance() -> None:
    session = _session()
    seed = TargetKeyword(keyword="seed", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    session.add(seed)
    session.commit()
    decision = evaluate_keyword_admission(
        session,
        _candidate("brand child", parent_id=seed.id, parent=seed.keyword),
        parent_keyword=seed.keyword,
    )
    outcome = persist_admission_decision(
        session,
        decision,
        _candidate("brand child", parent_id=seed.id, parent=seed.keyword),
        parent_keyword=seed.keyword,
        discovery_run_id="adm_test",
    )
    session.commit()
    row = session.scalar(select(TargetKeyword).where(TargetKeyword.keyword == "brand child"))
    assert outcome.outcome == "created"
    assert row.lifecycle_status == LIFECYCLE_PROBATION
    assert row.parent_keyword_id == seed.id
    assert row.source_type == SOURCE_SUGGESTION


def test_no_same_run_recursion() -> None:
    session = _session()
    seed = TargetKeyword(keyword="seed", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    session.add(seed)
    session.commit()
    created_ids: set[int] = set()
    cfg = KeywordExpansionOrchestratorConfig(cooldown_days=0, source_types=(SOURCE_SUGGESTION,))
    with patch.object(SuggestionExpansionSource, "expand", _fake_one):
        summary = asyncio.run(
            run_keyword_expansion_orchestrated(session, seed.id, config=cfg, run_id="same_run"),
        )
    assert summary.created_keyword_count == 1
    new_id = session.scalar(select(TargetKeyword.id).where(TargetKeyword.keyword == "seed-child"))
    created_ids.add(new_id)
    with patch.object(SuggestionExpansionSource, "expand", _fake_one):
        blocked = asyncio.run(
            run_keyword_expansion_orchestrated(
                session,
                new_id,
                config=cfg,
                run_id="same_run",
                created_this_run=created_ids,
            ),
        )
    assert blocked.errors == ("seed_created_same_run",)


def test_dry_run_writes_nothing() -> None:
    session = _session()
    seed = TargetKeyword(keyword="seed", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    session.add(seed)
    session.commit()
    cfg = KeywordExpansionOrchestratorConfig(cooldown_days=0, source_types=(SOURCE_SUGGESTION,))
    with patch.object(SuggestionExpansionSource, "expand", _fake_one):
        summary = asyncio.run(run_keyword_expansion_orchestrated(session, seed.id, config=cfg, dry_run=True))
    assert summary.cycle_status == "dry_run"
    assert session.scalar(select(func.count()).select_from(KeywordExpansionEvent)) == 0
    assert session.scalar(select(func.count()).select_from(TargetKeyword)) == 1


def test_no_lifecycle_auto_change() -> None:
    session = _session()
    archived = TargetKeyword(keyword="old", lifecycle_status=LIFECYCLE_ARCHIVED, source_type="seed")
    seed = TargetKeyword(keyword="seed", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    session.add_all([archived, seed])
    session.commit()
    decision = evaluate_keyword_admission(
        session,
        _candidate("old", parent_id=seed.id, parent=seed.keyword),
        parent_keyword=seed.keyword,
    )
    persist_admission_decision(
        session,
        decision,
        _candidate("old", parent_id=seed.id, parent=seed.keyword),
        parent_keyword=seed.keyword,
        discovery_run_id="lc",
    )
    session.commit()
    session.refresh(archived)
    assert archived.lifecycle_status == LIFECYCLE_ARCHIVED


def test_batch_seed_eligibility_query_budget() -> None:
    session = _session()
    seeds = [
        TargetKeyword(keyword=f"s{i}", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed") for i in range(8)
    ]
    session.add_all(seeds)
    session.commit()
    counts: list[int] = []

    def before_cursor_execute(_conn, _cursor, _statement, _parameters, _context, _executemany):
        counts.append(1)

    event.listen(session.bind, "before_cursor_execute", before_cursor_execute)
    try:
        ids = [s.id for s in seeds]
        count_successful_scans_batch(session, ids)
        batch_expansion_depths(session, ids)
    finally:
        event.remove(session.bind, "before_cursor_execute", before_cursor_execute)
    assert len(counts) < 30


def test_orchestrator_deferred_events() -> None:
    session = _session()
    seed = TargetKeyword(keyword="seed", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    session.add(seed)
    session.commit()

    async def many(_self, seed_keyword, context):
        return [
            _candidate(f"kw{i}", parent_id=context.parent_keyword_id, parent=seed_keyword) for i in range(5)
        ]

    cfg = KeywordExpansionOrchestratorConfig(
        max_new_keywords_per_seed_per_run=1,
        max_new_keywords_per_expansion_run=50,
        cooldown_days=0,
        source_types=(SOURCE_SUGGESTION,),
    )
    with patch.object(SuggestionExpansionSource, "expand", many):
        summary = asyncio.run(run_keyword_expansion_orchestrated(session, seed.id, config=cfg))
    session.commit()
    assert summary.created_keyword_count == 1
    assert summary.deferred_count >= 1
    deferred = session.scalars(select(KeywordExpansionEvent).where(KeywordExpansionEvent.outcome == "deferred")).all()
    assert deferred
    assert deferred[0].rejection_reason == "parent_budget_exhausted"


def main() -> None:
    tests = [
        test_archived_seed_cannot_expand,
        test_weak_seed_excluded_by_default,
        test_fresh_probation_not_ready,
        test_probation_with_scans_eligible,
        test_active_seed_eligible,
        test_depth_limit_blocks,
        test_same_as_parent_rejected,
        test_existing_keyword,
        test_existing_archived,
        test_pool_budget_deferred,
        test_parent_budget_deferred,
        test_global_budget_deferred,
        test_filter_rejection,
        test_created_probation_provenance,
        test_no_same_run_recursion,
        test_dry_run_writes_nothing,
        test_no_lifecycle_auto_change,
        test_batch_seed_eligibility_query_budget,
        test_orchestrator_deferred_events,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"OK {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")
    if failed:
        raise SystemExit(f"{failed} failed")
    print("All keyword admission orchestration tests passed.")


if __name__ == "__main__":
    main()
