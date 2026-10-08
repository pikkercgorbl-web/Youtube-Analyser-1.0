"""Tests for post-discovery keyword expansion pass (Stage 5)."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.models.orm import KeywordExpansionEvent, TargetKeyword, Video, KeywordDiscoveryHit
from app.services.discovery_cycle import DiscoveryCycleSummary, DiscoveryKeywordSummary
from app.services.keyword_expansion_config import KeywordExpansionConfig, is_source_on_cooldown
from app.services.keyword_expansion_discovery_pass import run_keyword_expansion_discovery_pass
from app.services.keyword_expansion_orchestrator import KeywordExpansionOrchestratorConfig
from app.services.keyword_expansion_sources import (
    ChannelTopicExpansionSource,
    RelatedQueryExpansionSource,
    SuggestionExpansionSource,
)
from app.services.keyword_expansion_types import KeywordExpansionCandidate, SimpleExpansionContext
from app.services.keyword_scheduling_policy import (
    LIFECYCLE_ACTIVE,
    LIFECYCLE_PROBATION,
    SOURCE_CHANNEL,
    SOURCE_RELATED,
    SOURCE_SUGGESTION,
)
from app.services.metrics import utc_now


def _session():
    engine = create_engine("sqlite:///:memory:")
    app.models.orm.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()


def _cycle_summary(*rows: DiscoveryKeywordSummary) -> DiscoveryCycleSummary:
    return DiscoveryCycleSummary(
        run_id="discovery_test_run",
        started_at=utc_now(),
        finished_at=utc_now(),
        keyword_summaries=rows,
    )


def _ok_summary(keyword_id: int, keyword: str) -> DiscoveryKeywordSummary:
    now = utc_now()
    return DiscoveryKeywordSummary(
        keyword_id=keyword_id,
        keyword=keyword,
        started_at=now,
        finished_at=now,
        runtime_seconds=0.1,
        raw_candidates=1,
        unique_candidates=1,
        persisted_videos=0,
        updated_videos=0,
        qualification_passed=0,
        qualification_rejected=0,
        duplicate_candidates=0,
        explosive_hits=0,
        status="ok",
    )


def _candidate(text: str, *, parent_id: int, parent: str, source: str) -> KeywordExpansionCandidate:
    return KeywordExpansionCandidate(
        keyword=text,
        normalized_keyword=text,
        source_type=source,
        parent_keyword_id=parent_id,
        parent_keyword=parent,
        discovered_at=utc_now(),
    )


def test_same_candidate_two_sources_existing() -> None:
    session = _session()
    seed = TargetKeyword(keyword="seed", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    session.add(seed)
    session.commit()

    async def sug(_self, seed_keyword, context):
        return [_candidate("overlap kw", parent_id=context.parent_keyword_id, parent=seed_keyword, source=SOURCE_SUGGESTION)]

    async def rel(_self, seed_keyword, context):
        return [_candidate("overlap kw", parent_id=context.parent_keyword_id, parent=seed_keyword, source=SOURCE_RELATED)]

    cfg = KeywordExpansionConfig(cooldown_days=0, source_types=(SOURCE_SUGGESTION, SOURCE_RELATED))
    summary = _cycle_summary(_ok_summary(seed.id, seed.keyword))
    with patch.object(SuggestionExpansionSource, "expand", sug), patch.object(RelatedQueryExpansionSource, "expand", rel):
        report = run_keyword_expansion_discovery_pass(session, cycle_summary=summary, config=cfg)
    session.commit()
    assert report.summary is not None
    assert report.summary.created_keyword_count == 1
    assert report.summary.existing_keyword_count == 1
    assert session.scalar(select(func.count()).select_from(TargetKeyword)) == 2


def test_existing_pool_keyword() -> None:
    session = _session()
    seed = TargetKeyword(keyword="seed", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    existing = TargetKeyword(
        keyword="already",
        lifecycle_status=LIFECYCLE_PROBATION,
        source_type=SOURCE_SUGGESTION,
        parent_keyword_id=None,
    )
    session.add_all([seed, existing])
    session.commit()

    async def sug(_self, seed_keyword, context):
        return [_candidate("already", parent_id=context.parent_keyword_id, parent=seed_keyword, source=SOURCE_SUGGESTION)]

    cfg = KeywordExpansionConfig(cooldown_days=0, source_types=(SOURCE_SUGGESTION,))
    with patch.object(SuggestionExpansionSource, "expand", sug):
        report = run_keyword_expansion_discovery_pass(
            session,
            cycle_summary=_cycle_summary(_ok_summary(seed.id, seed.keyword)),
            config=cfg,
        )
    session.commit()
    assert report.summary is not None
    assert report.summary.created_keyword_count == 0
    assert report.summary.existing_keyword_count == 1


def test_cooldown_skips_source_on_second_pass() -> None:
    session = _session()
    seed = TargetKeyword(keyword="seed", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    session.add(seed)
    session.commit()

    calls = {"n": 0}

    async def sug(_self, seed_keyword, context):
        calls["n"] += 1
        return [_candidate(f"child-{calls['n']}", parent_id=context.parent_keyword_id, parent=seed_keyword, source=SOURCE_SUGGESTION)]

    cfg = KeywordExpansionConfig(cooldown_days=7, source_types=(SOURCE_SUGGESTION,))
    cycle = _cycle_summary(_ok_summary(seed.id, seed.keyword))
    with patch.object(SuggestionExpansionSource, "expand", sug):
        first = run_keyword_expansion_discovery_pass(session, cycle_summary=cycle, config=cfg)
        session.commit()
        assert first.summary is not None
        assert first.summary.created_keyword_count == 1
        assert is_source_on_cooldown(session, parent_keyword_id=seed.id, source_type=SOURCE_SUGGESTION, cooldown_days=7)
        second = run_keyword_expansion_discovery_pass(session, cycle_summary=cycle, config=cfg)
    assert second.summary is not None
    assert second.summary.created_keyword_count == 0
    assert calls["n"] == 1


def test_depth_limit_in_pass() -> None:
    session = _session()
    root = TargetKeyword(keyword="root", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    session.add(root)
    session.flush()
    child = TargetKeyword(
        keyword="child",
        lifecycle_status=LIFECYCLE_ACTIVE,
        source_type=SOURCE_SUGGESTION,
        parent_keyword_id=root.id,
    )
    session.add(child)
    session.flush()
    grand = TargetKeyword(
        keyword="grand",
        lifecycle_status=LIFECYCLE_ACTIVE,
        source_type=SOURCE_SUGGESTION,
        parent_keyword_id=child.id,
    )
    session.add(grand)
    session.commit()

    async def sug(_self, seed_keyword, context):
        return [_candidate("deep", parent_id=context.parent_keyword_id, parent=seed_keyword, source=SOURCE_SUGGESTION)]

    cfg = KeywordExpansionOrchestratorConfig(cooldown_days=0, source_types=(SOURCE_SUGGESTION,), max_expansion_depth=2)
    cycle = _cycle_summary(_ok_summary(grand.id, grand.keyword))
    with patch.object(SuggestionExpansionSource, "expand", sug):
        report = run_keyword_expansion_discovery_pass(session, cycle_summary=cycle, config=cfg)
    assert report.selected_seed_count == 0
    assert report.skip_reasons.get("depth_limit") == 1


def test_one_source_error_other_succeeds() -> None:
    session = _session()
    seed = TargetKeyword(keyword="seed", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    session.add(seed)
    session.commit()

    async def sug(_self, seed_keyword, context):
        raise RuntimeError("autocomplete down")

    async def topic(_self, seed_keyword, context):
        return [_candidate("topic phrase", parent_id=context.parent_keyword_id, parent=seed_keyword, source=SOURCE_CHANNEL)]

    cfg = KeywordExpansionConfig(cooldown_days=0, source_types=(SOURCE_SUGGESTION, SOURCE_CHANNEL))
    with patch.object(SuggestionExpansionSource, "expand", sug), patch.object(ChannelTopicExpansionSource, "expand", topic):
        report = run_keyword_expansion_discovery_pass(
            session,
            cycle_summary=_cycle_summary(_ok_summary(seed.id, seed.keyword)),
            config=cfg,
        )
    session.commit()
    assert report.summary is not None
    assert report.summary.created_keyword_count == 1
    assert any("suggestion:" in e for e in report.errors)


def test_probation_and_provenance() -> None:
    session = _session()
    seed = TargetKeyword(keyword="seed", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    session.add(seed)
    session.commit()

    async def sug(_self, seed_keyword, context):
        return [_candidate("fresh topic", parent_id=context.parent_keyword_id, parent=seed_keyword, source=SOURCE_SUGGESTION)]

    cfg = KeywordExpansionConfig(cooldown_days=0, source_types=(SOURCE_SUGGESTION,))
    with patch.object(SuggestionExpansionSource, "expand", sug):
        run_keyword_expansion_discovery_pass(
            session,
            cycle_summary=_cycle_summary(_ok_summary(seed.id, seed.keyword)),
            config=cfg,
        )
    session.commit()
    row = session.scalar(select(TargetKeyword).where(TargetKeyword.keyword == "fresh topic"))
    assert row is not None
    assert row.lifecycle_status == LIFECYCLE_PROBATION
    assert row.parent_keyword_id == seed.id
    assert row.source_type == SOURCE_SUGGESTION
    ev = session.scalars(select(KeywordExpansionEvent).where(KeywordExpansionEvent.outcome == "created")).all()
    assert len(ev) == 1


def test_dry_run_no_side_effects() -> None:
    session = _session()
    seed = TargetKeyword(keyword="seed", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    session.add(seed)
    session.commit()

    async def sug(_self, seed_keyword, context):
        return [_candidate("ghost", parent_id=context.parent_keyword_id, parent=seed_keyword, source=SOURCE_SUGGESTION)]

    cfg = KeywordExpansionConfig(cooldown_days=0, source_types=(SOURCE_SUGGESTION,))
    with patch.object(SuggestionExpansionSource, "expand", sug):
        report = run_keyword_expansion_discovery_pass(
            session,
            cycle_summary=_cycle_summary(_ok_summary(seed.id, seed.keyword)),
            config=cfg,
            dry_run=True,
        )
    session.rollback()
    assert report.summary is not None
    assert report.summary.cycle_status == "dry_run"
    assert session.scalar(select(func.count()).select_from(TargetKeyword)) == 1
    assert session.scalar(select(func.count()).select_from(KeywordExpansionEvent)) == 0
    with patch.object(SuggestionExpansionSource, "expand", sug):
        live = run_keyword_expansion_discovery_pass(
            session,
            cycle_summary=_cycle_summary(_ok_summary(seed.id, seed.keyword)),
            config=cfg,
            dry_run=False,
        )
    session.commit()
    assert live.summary is not None
    assert live.summary.created_keyword_count == 1


def test_new_keywords_not_in_same_cycle_seed_list() -> None:
    """Discovery pass only expands keywords from the cycle summary (not same-run creates)."""
    session = _session()
    seed = TargetKeyword(keyword="seed", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    session.add(seed)
    session.commit()

    async def sug(_self, seed_keyword, context):
        return [_candidate("only-child", parent_id=context.parent_keyword_id, parent=seed_keyword, source=SOURCE_SUGGESTION)]

    cfg = KeywordExpansionConfig(cooldown_days=0, source_types=(SOURCE_SUGGESTION,))
    cycle = _cycle_summary(_ok_summary(seed.id, seed.keyword))
    with patch.object(SuggestionExpansionSource, "expand", sug):
        report = run_keyword_expansion_discovery_pass(session, cycle_summary=cycle, config=cfg)
    session.commit()
    assert report.summary is not None
    assert report.summary.created_keyword_count == 1
    assert report.selected_seed_count == 1
    child = session.scalar(select(TargetKeyword).where(TargetKeyword.keyword == "only-child"))
    assert child is not None
    cycle_child_only = _cycle_summary(_ok_summary(child.id, child.keyword))
    with patch.object(SuggestionExpansionSource, "expand", sug):
        second = run_keyword_expansion_discovery_pass(session, cycle_summary=cycle_child_only, config=cfg)
    assert second.selected_seed_count == 0
    assert second.skip_reasons.get("seed_not_ready") == 1


def test_channel_topic_source_from_hits() -> None:
    session = _session()
    seed = TargetKeyword(keyword="seed", lifecycle_status=LIFECYCLE_ACTIVE, source_type="seed")
    session.add(seed)
    session.flush()
    now = utc_now()
    video = Video(
        id="vid1",
        title="t",
        channel_id="ch1",
        topic="Cooking tips",
        published_at=now,
    )
    hit = KeywordDiscoveryHit(keyword_id=seed.id, video_id=video.id, discovery_run_id="d1", discovered_at=utc_now())
    session.add_all([video, hit])
    session.commit()

    cfg = KeywordExpansionConfig(cooldown_days=0, source_types=(SOURCE_CHANNEL,))
    report = run_keyword_expansion_discovery_pass(
        session,
        cycle_summary=_cycle_summary(_ok_summary(seed.id, seed.keyword)),
        config=cfg,
    )
    session.commit()
    assert report.summary is not None
    assert report.summary.created_keyword_count == 1
    row = session.scalar(select(TargetKeyword).where(TargetKeyword.keyword == "Cooking tips"))
    assert row is not None
    assert row.source_type == SOURCE_CHANNEL


def main() -> None:
    tests = [
        test_same_candidate_two_sources_existing,
        test_existing_pool_keyword,
        test_cooldown_skips_source_on_second_pass,
        test_depth_limit_in_pass,
        test_one_source_error_other_succeeds,
        test_probation_and_provenance,
        test_dry_run_no_side_effects,
        test_new_keywords_not_in_same_cycle_seed_list,
        test_channel_topic_source_from_hits,
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
    print("All keyword expansion discovery pass tests passed.")


if __name__ == "__main__":
    main()
