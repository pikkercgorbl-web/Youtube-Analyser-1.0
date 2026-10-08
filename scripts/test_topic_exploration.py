"""Offline tests for topic exploration (Stage 6)."""

from __future__ import annotations

import json
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
from app.models.orm import KeywordExpansionEvent, TargetKeyword
from app.services.discovery_cycle import DiscoveryCycleConfig, run_discovery_cycle
from app.services.keyword_scheduling_policy import LIFECYCLE_PROBATION, SOURCE_EXPLORATION, SOURCE_SEED
from app.services.metrics import utc_now
from app.services.topic_exploration_admit import admit_topic_exploration_preview
from app.services.topic_exploration_batch_split import split_discovery_batch_slots
from app.services.topic_exploration_cycle import TopicExplorationCyclePlan, build_topic_exploration_cycle_plan
from app.services.topic_exploration_discovery_pass import run_topic_exploration_discovery_pass
from app.services.topic_exploration_mining_config import TopicExplorationMiningConfig
from app.services.topic_exploration_novelty import attach_novelty_signals, exploration_pass_fingerprint
from app.services.topic_exploration_observation_store import TopicExplorationObservationStore
from app.services.topic_exploration_preview import build_topic_exploration_preview
from app.services.topic_exploration_queries import TopicExplorationQuery, load_topic_exploration_queries
from app.services.topic_exploration_runtime_config import TopicExplorationRuntimeSettings
from app.services.topic_exploration_types import (
    TopicExplorationScanSummary,
    TopicExplorationTitleHit,
)

UTC = timezone.utc


def _session():
    engine = create_engine("sqlite:///:memory:")
    app.models.orm.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()


def _hit(
    video_id: str,
    channel_id: str,
    title: str,
    *,
    query_id: str = "explore_indie_horror_rooms",
    query_text: str = "indie horror game secret rooms gameplay",
    run_id: str = "discovery_x:exploration:explore_indie_horror_rooms",
) -> TopicExplorationTitleHit:
    return TopicExplorationTitleHit(
        video_id=video_id,
        channel_id=channel_id,
        title=title,
        exploration_query_id=query_id,
        exploration_query_text=query_text,
        discovery_run_id=run_id,
        discovered_at=datetime(2026, 10, 7, 12, 0, tzinfo=UTC),
    )


def _scan(*hits: TopicExplorationTitleHit) -> TopicExplorationScanSummary:
    return TopicExplorationScanSummary(
        query_id=hits[0].exploration_query_id if hits else "q",
        query_text=hits[0].exploration_query_text if hits else "q",
        discovery_run_id=hits[0].discovery_run_id if hits else "r",
        started_at=datetime(2026, 10, 7, 12, 0, tzinfo=UTC),
        finished_at=datetime(2026, 10, 7, 12, 1, tzinfo=UTC),
        max_pages=3,
        title_hits=hits,
    )


def test_batch_split_small_batch_preserves_seed_and_exploration() -> None:
    assert split_discovery_batch_slots(1, exploration_enabled=True, exploration_fraction=0.2) == (1, 0)
    assert split_discovery_batch_slots(2, exploration_enabled=True, exploration_fraction=0.2) == (1, 1)
    assert split_discovery_batch_slots(5, exploration_enabled=True, exploration_fraction=0.2) == (4, 1)
    assert split_discovery_batch_slots(5, exploration_enabled=False, exploration_fraction=0.2) == (5, 0)


def test_duckrooms_detected_without_seed() -> None:
    session = _session()
    hits = (
        _hit("v1", "ch_a", "Duckrooms is terrifying — full gameplay"),
        _hit("v2", "ch_b", "We found Duckrooms secret level"),
        _hit("v3", "ch_c", "Duckrooms co op horror"),
    )
    preview = build_topic_exploration_preview(
        session,
        discovery_run_id="discovery_synthetic",
        exploration_scans=(_scan(*hits),),
        mining_config=TopicExplorationMiningConfig(min_distinct_videos=2, min_distinct_channels=2),
    )
    phrases = {p.normalized_phrase for p in preview.proposed}
    assert "duckrooms" in phrases
    seeds = session.scalars(select(TargetKeyword).where(TargetKeyword.source_type == SOURCE_SEED)).all()
    assert len(list(seeds)) == 0


def test_repeat_video_hits_do_not_inflate_support() -> None:
    session = _session()
    base = _hit("v1", "ch_a", "Duckrooms gameplay")
    hits = (base, base, base, _hit("v2", "ch_b", "Duckrooms horror"))
    preview = build_topic_exploration_preview(
        session,
        discovery_run_id="discovery_synthetic",
        exploration_scans=(_scan(*hits),),
    )
    duck = next((p for p in preview.proposed if p.normalized_phrase == "duckrooms"), None)
    assert duck is not None
    assert duck.support_video_count == 2


def test_single_channel_does_not_inflate_support() -> None:
    session = _session()
    hits = tuple(_hit(f"v{i}", "ch_only", f"Duckrooms part {i}") for i in range(5))
    preview = build_topic_exploration_preview(
        session,
        discovery_run_id="discovery_synthetic",
        exploration_scans=(_scan(*hits),),
    )
    assert not preview.proposed
    assert any(r.reason_code == "insufficient_channel_support" for r in preview.rejected)


def test_generic_phrase_rejected() -> None:
    session = _session()
    hits = (
        _hit("v1", "ch_a", "How to play best settings guide"),
        _hit("v2", "ch_b", "How to play tips and tricks"),
    )
    preview = build_topic_exploration_preview(
        session,
        discovery_run_id="discovery_synthetic",
        exploration_scans=(_scan(*hits),),
    )
    assert not preview.proposed
    assert any(r.reason_code == "generic_phrase" for r in preview.rejected)


def test_existing_keyword_not_duplicated() -> None:
    session = _session()
    session.add(
        TargetKeyword(
            keyword="duckrooms",
            lifecycle_status=LIFECYCLE_PROBATION,
            source_type=SOURCE_SEED,
            scan_interval_seconds=3600,
            next_scan_at=utc_now(),
        ),
    )
    session.commit()
    hits = (
        _hit("v1", "ch_a", "Duckrooms gameplay"),
        _hit("v2", "ch_b", "Duckrooms horror"),
    )
    preview = build_topic_exploration_preview(
        session,
        discovery_run_id="discovery_synthetic",
        exploration_scans=(_scan(*hits),),
    )
    assert not preview.proposed
    assert any(r.reason_code == "existing_keyword" for r in preview.rejected)


def test_preview_does_not_create_keywords_or_events() -> None:
    session = _session()
    hits = (
        _hit("v1", "ch_a", "Duckrooms gameplay"),
        _hit("v2", "ch_b", "Duckrooms horror"),
    )
    build_topic_exploration_preview(
        session,
        discovery_run_id="discovery_synthetic",
        exploration_scans=(_scan(*hits),),
    )
    assert session.scalar(select(func.count()).select_from(TargetKeyword)) == 0
    assert session.scalar(select(func.count()).select_from(KeywordExpansionEvent)) == 0


def test_admission_creates_probation_with_provenance() -> None:
    session = _session()
    parent = TargetKeyword(
        keyword="explore anchor query",
        lifecycle_status=LIFECYCLE_PROBATION,
        source_type=SOURCE_EXPLORATION,
        scan_interval_seconds=3600,
        next_scan_at=utc_now(),
    )
    session.add(parent)
    session.commit()
    hits = (
        _hit("v1", "ch_a", "Duckrooms gameplay"),
        _hit("v2", "ch_b", "Duckrooms horror"),
    )
    preview = build_topic_exploration_preview(
        session,
        discovery_run_id="discovery_admit_test",
        exploration_scans=(_scan(*hits),),
    )
    admitted, _ = admit_topic_exploration_preview(
        session,
        preview,
        exploration_parent_by_query_id={
            "explore_indie_horror_rooms": (parent.id, parent.keyword),
        },
        dry_run=False,
    )
    session.commit()
    assert admitted == 1
    row = session.scalars(select(TargetKeyword).where(TargetKeyword.keyword == "duckrooms")).one()
    assert row.lifecycle_status == LIFECYCLE_PROBATION
    assert row.source_type == SOURCE_EXPLORATION
    assert row.parent_keyword_id == parent.id
    events = list(session.scalars(select(KeywordExpansionEvent)).all())
    assert len(events) == 1
    assert events[0].outcome == "created"


def test_no_history_is_not_frequency_growth() -> None:
    store = TopicExplorationObservationStore()
    from app.services.topic_exploration_types import TopicExplorationPhraseEvidence

    evidence = TopicExplorationPhraseEvidence(
        phrase="duckrooms",
        normalized_phrase="duckrooms",
        distinct_video_ids=("v1", "v2"),
        distinct_channel_ids=("ch_a", "ch_b"),
        source_titles=("t1", "t2"),
        exploration_query_ids=("q1",),
        discovery_run_ids=("r1",),
        observation_window_start=utc_now() - timedelta(hours=1),
        observation_window_end=utc_now(),
        support_video_count=2,
        support_channel_count=2,
    )
    fp = "exploration_pass:abc"
    enriched = attach_novelty_signals(evidence, store=store, pass_fingerprint=fp)
    assert "first_seen_exploration" in enriched.novelty_signals
    assert "insufficient_history" in enriched.novelty_signals
    assert "frequency_up_comparable_pass" not in enriched.novelty_signals


def test_scan_volume_change_blocks_trend() -> None:
    store = TopicExplorationObservationStore()
    from app.services.topic_exploration_types import TopicExplorationPhraseEvidence

    evidence = TopicExplorationPhraseEvidence(
        phrase="duckrooms",
        normalized_phrase="duckrooms",
        distinct_video_ids=("v1", "v2", "v3"),
        distinct_channel_ids=("ch_a", "ch_b"),
        source_titles=("t1", "t2", "t3"),
        exploration_query_ids=("q1",),
        discovery_run_ids=("r1",),
        observation_window_start=utc_now() - timedelta(hours=1),
        observation_window_end=utc_now(),
        support_video_count=3,
        support_channel_count=2,
    )
    fp_new = "exploration_pass:new"
    store.record_pass(
        "duckrooms",
        fingerprint="exploration_pass:old",
        distinct_video_count=1,
        distinct_channel_count=1,
        recorded_at=utc_now(),
    )
    enriched = attach_novelty_signals(
        evidence,
        store=store,
        pass_fingerprint=fp_new,
        cycle_fingerprint="exploration_pass:old",
    )
    assert "pass_not_comparable" in enriched.novelty_signals or "no_growth_signal" in enriched.novelty_signals
    assert "frequency_up_comparable_pass" not in enriched.novelty_signals


def test_disabled_mode_default_runtime_settings() -> None:
    settings = TopicExplorationRuntimeSettings()
    assert settings.topic_exploration_in_discovery is False
    assert settings.topic_exploration_auto_admit is False
    plan = build_topic_exploration_cycle_plan(settings)
    assert plan.enabled is False


def test_example_queries_file_loads_without_db_import() -> None:
    path = ROOT / "config" / "topic_exploration_queries.example.json"
    loaded = load_topic_exploration_queries(path)
    assert any(q.query_id == "explore_indie_horror_rooms" for q in loaded)
    assert all(q.kind == "exploration" for q in loaded)


def test_discovery_cycle_flag_off_unchanged_batch_selection() -> None:
    session = _session()
    for i in range(3):
        session.add(
            TargetKeyword(
                keyword=f"seed kw {i}",
                lifecycle_status=LIFECYCLE_PROBATION,
                source_type=SOURCE_SEED,
                scan_interval_seconds=60,
                next_scan_at=utc_now() - timedelta(minutes=5),
            ),
        )
    session.commit()
    selected: list[int] = []

    async def fake_scan(*_a, **_k):
        from app.services.discovery_keyword_scan import KeywordDiscoveryScanResult

        return KeywordDiscoveryScanResult(keyword=_k.get("keyword", ""), unique_videos=[])

    with patch("app.services.discovery_cycle.scan_keyword_for_discovery", side_effect=fake_scan):
        with patch("app.services.discovery_cycle.select_discovery_keywords") as mock_select:
            mock_select.side_effect = lambda _s, batch_size: list(
                session.scalars(select(TargetKeyword).limit(batch_size)).all(),
            )
            outcome = run_discovery_cycle(
                session,
                config=DiscoveryCycleConfig(keyword_batch_size=3),
                dry_run=True,
            )
    mock_select.assert_called_once()
    assert mock_select.call_args.kwargs["batch_size"] == 3
    assert outcome.summary.exploration_query_count == 0


def test_synthetic_preview_json_example() -> None:
    """Documented synthetic preview sample (not from production DB)."""
    session = _session()
    hits = (
        _hit("syn_v1", "syn_ch_a", "Duckrooms — backrooms duck horror"),
        _hit("syn_v2", "syn_ch_b", "Playing Duckrooms with friends"),
    )
    preview = build_topic_exploration_preview(
        session,
        discovery_run_id="SYNTHETIC_discovery_run_id",
        exploration_scans=(_scan(*hits),),
    )
    sample = {
        "synthetic": True,
        "discovery_run_id": preview.discovery_run_id,
        "proposed": [
            {
                "phrase": p.phrase,
                "videos": list(p.distinct_video_ids),
                "channels": list(p.distinct_channel_ids),
                "titles": list(p.source_titles),
                "novelty": list(p.novelty_signals),
            }
            for p in preview.proposed
        ],
    }
    text = json.dumps(sample, ensure_ascii=False, indent=2)
    assert "SYNTHETIC" in text
    assert "duckrooms" in text.lower()


def _run_all() -> None:
    tests = [
        test_batch_split_small_batch_preserves_seed_and_exploration,
        test_duckrooms_detected_without_seed,
        test_repeat_video_hits_do_not_inflate_support,
        test_single_channel_does_not_inflate_support,
        test_generic_phrase_rejected,
        test_existing_keyword_not_duplicated,
        test_preview_does_not_create_keywords_or_events,
        test_admission_creates_probation_with_provenance,
        test_no_history_is_not_frequency_growth,
        test_scan_volume_change_blocks_trend,
        test_disabled_mode_default_runtime_settings,
        test_example_queries_file_loads_without_db_import,
        test_discovery_cycle_flag_off_unchanged_batch_selection,
        test_synthetic_preview_json_example,
    ]
    for fn in tests:
        fn()
        print(f"OK {fn.__name__}")


if __name__ == "__main__":
    _run_all()
