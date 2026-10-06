"""Tests for keyword expansion (Stage 1.16C)."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.models.orm import KeywordExpansionEvent, TargetKeyword
from app.services.keyword_expansion_filter import filter_candidates, reject_reason
from app.services.keyword_expansion_persistence import persist_expansion_candidate
from app.services.keyword_expansion_service import (
    KeywordExpansionConfig,
    is_seed_eligible,
    is_source_on_cooldown,
    run_keyword_expansion,
    run_keyword_expansion_batch,
)
from app.services.keyword_expansion_sources import SuggestionExpansionSource, _dedupe_suggestions
from app.services.keyword_expansion_types import KeywordExpansionCandidate, SimpleExpansionContext
from app.services.keyword_lifecycle_service import normalize_keyword_text
from app.services.keyword_scheduling_policy import LIFECYCLE_ACTIVE, LIFECYCLE_ARCHIVED, LIFECYCLE_PROBATION, LIFECYCLE_WEAK, SOURCE_SUGGESTION
from app.services.metrics import utc_now

UTC = timezone.utc


def _engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


def _session():
    return sessionmaker(bind=_engine())()


def _candidate(text: str, *, parent_id: int = 1, parent: str = "seed") -> KeywordExpansionCandidate:
    return KeywordExpansionCandidate(
        keyword=text,
        normalized_keyword=normalize_keyword_text(text),
        source_type=SOURCE_SUGGESTION,
        parent_keyword_id=parent_id,
        parent_keyword=parent,
        discovered_at=datetime.now(UTC),
    )


def test_suggestion_dedupe_and_parent_reject() -> None:
    parent = "gaming"
    merged = _dedupe_suggestions(["gaming", "Gaming", "fps tips"], parent_normalized=parent.casefold(), limit=20)
    assert merged == ["fps tips"]
    reason = reject_reason(_candidate("gaming"), parent_normalized=parent)
    assert reason == "same_as_parent"
    assert reject_reason(_candidate("123"), parent_normalized=parent) == "numeric_only"
    assert reject_reason(_candidate(""), parent_normalized=parent) == "empty"


def test_source_dedup_in_filter() -> None:
    items = [_candidate("alpha"), _candidate("alpha"), _candidate("beta")]
    accepted, rejected = filter_candidates(items, parent_keyword="seed")
    assert len(accepted) == 2
    assert any(reason == "duplicate_in_batch" for _, reason in rejected)


async def _run(coro):
    return await coro


def test_existing_not_duplicated_archived_unchanged() -> None:
    session = _session()
    archived = TargetKeyword(
        keyword="old term",
        lifecycle_status=LIFECYCLE_ARCHIVED,
        source_type="seed",
    )
    session.add(archived)
    session.commit()
    outcome = persist_expansion_candidate(
        session,
        _candidate("old term", parent_id=archived.id, parent="x"),
        parent_keyword="x",
        discovery_run_id="exp_test",
    )
    session.commit()
    session.refresh(archived)
    assert outcome.outcome == "existing"
    assert archived.lifecycle_status == LIFECYCLE_ARCHIVED
    assert session.scalar(select(func.count()).select_from(TargetKeyword)) == 1


def test_new_keyword_probation_provenance() -> None:
    session = _session()
    seed = TargetKeyword(keyword="seed", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    session.add(seed)
    session.commit()
    outcome = persist_expansion_candidate(
        session,
        _candidate("brand new query", parent_id=seed.id, parent=seed.keyword),
        parent_keyword=seed.keyword,
        discovery_run_id="exp_test2",
    )
    session.commit()
    row = session.scalar(select(TargetKeyword).where(TargetKeyword.keyword == "brand new query"))
    assert outcome.outcome == "created"
    assert row is not None
    assert row.lifecycle_status == LIFECYCLE_PROBATION
    assert row.source_type == SOURCE_SUGGESTION
    assert row.parent_keyword_id == seed.id
    assert row.next_scan_at is not None


def test_seed_eligibility() -> None:
    from app.services.keyword_expansion_orchestrator import is_seed_eligible_for_expansion

    assert is_seed_eligible(TargetKeyword(keyword="a", lifecycle_status=LIFECYCLE_ACTIVE), expand_weak=False)
    assert is_seed_eligible(TargetKeyword(keyword="a", lifecycle_status=LIFECYCLE_PROBATION), expand_weak=False)
    assert not is_seed_eligible(TargetKeyword(keyword="a", lifecycle_status=LIFECYCLE_ARCHIVED), expand_weak=False)
    assert not is_seed_eligible(TargetKeyword(keyword="a", lifecycle_status=LIFECYCLE_WEAK), expand_weak=False)
    assert is_seed_eligible(TargetKeyword(keyword="a", lifecycle_status=LIFECYCLE_WEAK), expand_weak=True)
    assert not is_seed_eligible_for_expansion(
        TargetKeyword(keyword="p", lifecycle_status=LIFECYCLE_PROBATION),
        expand_weak=False,
        successful_scan_count=0,
        expansion_depth=1,
        max_expansion_depth=2,
    )


def test_caps_and_no_recursive_same_run() -> None:
    session = _session()
    seed = TargetKeyword(keyword="seed", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    session.add(seed)
    session.commit()

    async def fake_expand(_self, seed_keyword, context):
        return [
            _candidate(f"kw{i}", parent_id=context.parent_keyword_id, parent=seed_keyword)
            for i in range(15)
        ]

    cfg = KeywordExpansionConfig(
        max_new_keywords_per_seed_per_run=2,
        max_new_keywords_per_expansion_run=3,
        cooldown_days=0,
        source_types=(SOURCE_SUGGESTION,),
    )
    with patch.object(SuggestionExpansionSource, "expand", fake_expand):
        summary = asyncio.run(
            run_keyword_expansion(session, seed.id, config=cfg, run_id="exp_caps"),
        )
    assert summary.created_keyword_count == 2
    assert session.scalar(select(func.count()).select_from(TargetKeyword)) == 3


def test_global_run_cap() -> None:
    session = _session()
    seeds = [
        TargetKeyword(keyword=f"s{i}", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
        for i in range(3)
    ]
    session.add_all(seeds)
    session.commit()

    async def fake_expand(_self, seed_keyword, context):
        return [_candidate(f"{seed_keyword}-new", parent_id=context.parent_keyword_id, parent=seed_keyword)]

    cfg = KeywordExpansionConfig(max_new_keywords_per_expansion_run=1, cooldown_days=0, source_types=(SOURCE_SUGGESTION,))
    with patch.object(SuggestionExpansionSource, "expand", fake_expand):
        summary = asyncio.run(
            run_keyword_expansion_batch(
                session,
                [s.id for s in seeds],
                config=cfg,
            ),
        )
    assert summary.created_keyword_count == 1


def test_dry_run_writes_nothing() -> None:
    session = _session()
    seed = TargetKeyword(keyword="seed", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    session.add(seed)
    session.commit()

    async def fake_expand(_self, seed_keyword, context):
        return [_candidate("dry only", parent_id=context.parent_keyword_id, parent=seed_keyword)]

    cfg = KeywordExpansionConfig(cooldown_days=0, source_types=(SOURCE_SUGGESTION,))
    with patch.object(SuggestionExpansionSource, "expand", fake_expand):
        summary = asyncio.run(run_keyword_expansion(session, seed.id, config=cfg, dry_run=True))
    assert summary.cycle_status == "dry_run"
    assert summary.created_keyword_count == 1
    assert session.scalar(select(func.count()).select_from(KeywordExpansionEvent)) == 0
    assert session.scalar(select(func.count()).select_from(TargetKeyword)) == 1


def test_cooldown_respected() -> None:
    session = _session()
    seed = TargetKeyword(keyword="seed", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    session.add(seed)
    session.commit()
    session.add(
        KeywordExpansionEvent(
            parent_keyword_id=seed.id,
            candidate_text="x",
            normalized_candidate="x",
            source_type=SOURCE_SUGGESTION,
            discovered_at=utc_now(),
            outcome="created",
        ),
    )
    session.commit()
    assert is_source_on_cooldown(
        session,
        parent_keyword_id=seed.id,
        source_type=SOURCE_SUGGESTION,
        cooldown_days=7,
    )


def test_expansion_event_on_create() -> None:
    session = _session()
    seed = TargetKeyword(keyword="seed", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    session.add(seed)
    session.commit()
    persist_expansion_candidate(
        session,
        _candidate("event test", parent_id=seed.id, parent=seed.keyword),
        parent_keyword=seed.keyword,
        discovery_run_id="exp_evt",
    )
    session.commit()
    events = session.scalars(select(KeywordExpansionEvent)).all()
    assert len(events) == 1
    assert events[0].outcome == "created"


def test_suggestion_source_mock() -> None:
    source = SuggestionExpansionSource(max_suggestions=5)
    ctx = SimpleExpansionContext(parent_keyword_id=1, parent_keyword="python")

    async def run():
        with patch(
            "app.services.keyword_expansion_sources.get_search_suggestions",
            new=AsyncMock(side_effect=[["python tutorial", "python"], ["python advanced"]]),
        ):
            return await source.expand("python", ctx)

    results = asyncio.run(run())
    assert results
    assert all(r.source_type == SOURCE_SUGGESTION for r in results)


def _run_script(name: str) -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / name)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)


def test_regressions() -> None:
    _run_script("test_discovery_cycle.py")
    _run_script("test_discovery_worker.py")


def main() -> None:
    tests = [
        test_suggestion_dedupe_and_parent_reject,
        test_source_dedup_in_filter,
        test_existing_not_duplicated_archived_unchanged,
        test_new_keyword_probation_provenance,
        test_seed_eligibility,
        test_caps_and_no_recursive_same_run,
        test_global_run_cap,
        test_dry_run_writes_nothing,
        test_cooldown_respected,
        test_expansion_event_on_create,
        test_suggestion_source_mock,
        test_regressions,
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
    print("All keyword expansion tests passed.")


if __name__ == "__main__":
    main()
