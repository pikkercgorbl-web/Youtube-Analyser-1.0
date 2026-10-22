"""Runtime-path tests for exploration evidence persistence and handoff (Stage 6)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.db.migrations import ensure_topic_exploration_evidence_tables
from app.integrations.youtube.client import LiveBroadcastStatus, VideoSearchModel
from app.models.orm import (
    Channel,
    KeywordExpansionEvent,
    TargetKeyword,
    TopicExplorationPass,
    TopicExplorationPhrasePassStat,
    TopicExplorationVideoObservation,
    Video,
    VideoFormat,
)
from app.services.discovery_cycle import DiscoveryCycleConfig, run_discovery_cycle
from app.services.discovery_keyword_selection import select_discovery_keywords
from app.services.discovery_keyword_scan import KeywordDiscoveryScanResult
from app.services.keyword_scheduling_policy import LIFECYCLE_PROBATION, SOURCE_EXPLORATION, SOURCE_SEED
from app.services.metrics import utc_now
from app.services.radar_enrichment_selection import RadarEnrichmentPassContext
from app.services.topic_exploration_admit import admit_topic_exploration_preview
from app.services.topic_exploration_cycle import TopicExplorationCyclePlan
from app.services.topic_exploration_discovery_pass import run_topic_exploration_discovery_pass
from app.services.topic_exploration_preview import build_topic_exploration_preview
from app.services.topic_exploration_queries import TopicExplorationQuery
from app.services.topic_exploration_types import TopicExplorationScanSummary, TopicExplorationTitleHit

UTC = timezone.utc


def _engine():
    engine = create_engine("sqlite:///:memory:")
    app.models.orm.Base.metadata.create_all(engine)
    ensure_topic_exploration_evidence_tables(engine)
    return engine


def _session():
    return sessionmaker(bind=_engine(), autoflush=False, expire_on_commit=False)()


def _video(vid: str, ch: str, title: str) -> VideoSearchModel:
    return VideoSearchModel(
        video_id=vid,
        title=title,
        channel_id=ch,
        channel_title="ch",
        views_count=1000,
        published_text="2 days ago",
        live_broadcast_status=LiveBroadcastStatus.NONE,
        is_short=False,
        is_live=False,
    )


def _exploration_plan() -> TopicExplorationCyclePlan:
    return TopicExplorationCyclePlan(
        enabled=True,
        batch_fraction=0.2,
        max_pages_per_query=3,
        queries=(
            TopicExplorationQuery(
                query_id="explore_test",
                query_text="broad horror rooms gameplay",
                direction="test",
                enabled=True,
                schedule="every_discovery_cycle",
            ),
        ),
    )


def test_exploration_cycle_persists_video_and_evidence() -> None:
    session = _session()
    session.add(
        TargetKeyword(
            keyword="seed one",
            lifecycle_status=LIFECYCLE_PROBATION,
            source_type=SOURCE_SEED,
            scan_interval_seconds=3600,
            next_scan_at=utc_now() - timedelta(minutes=1),
        ),
    )
    session.commit()

    async def fake_scan(_session, *, keyword, keyword_id=None, **_kw):
        if keyword_id is not None:
            return KeywordDiscoveryScanResult(keyword=keyword, keyword_id=keyword_id, unique_videos=[])
        return KeywordDiscoveryScanResult(
            keyword=keyword,
            keyword_id=None,
            unique_videos=[
                _video("ev_v1", "ev_ch_a", "Duckrooms gameplay"),
                _video("ev_v2", "ev_ch_b", "Duckrooms horror"),
            ],
        )

    with patch("app.services.discovery_cycle.scan_keyword_for_discovery", side_effect=fake_scan):
        outcome = run_discovery_cycle(
            session,
            config=DiscoveryCycleConfig(
                keyword_batch_size=2,
                topic_exploration_plan=_exploration_plan(),
            ),
            dry_run=False,
        )

    assert "ev_v1" in outcome.summary.cycle_video_ids
    passes = list(session.scalars(select(TopicExplorationPass)).all())
    assert len(passes) == 1
    assert passes[0].status == "ok"
    obs = list(session.scalars(select(TopicExplorationVideoObservation)).all())
    assert len(obs) == 2
    assert len({o.video_id for o in obs}) == 2


def test_enrichment_handoff_cycle_video_band() -> None:
    """cycle_video_ids boosts band=0 in format priority (same path enrichment pass uses)."""
    from app.models.orm import Video

    session = _session()
    video = Video(
        id="ev_v1",
        channel_id="ev_ch_a",
        title="Duckrooms",
        content_format=VideoFormat.MEDIUM,
        views_count=100,
    )
    ctx = RadarEnrichmentPassContext(
        discovery_run_id="discovery_test",
        cycle_video_ids=frozenset({"ev_v1"}),
    )
    from app.services.radar_enrichment_selection import _format_priority

    key = _format_priority(
        video,
        context=ctx,
        views_at_discovery=None,
        recent_video_ids=set(),
        pass_sequence=1,
    )
    assert key[0] == 0


def test_first_seen_survives_new_session() -> None:
    engine = _engine()
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def hits() -> tuple[TopicExplorationTitleHit, ...]:
        return (
            TopicExplorationTitleHit(
                video_id="v1",
                channel_id="c1",
                title="Duckrooms gameplay",
                exploration_query_id="explore_test",
                exploration_query_text="broad",
                discovery_run_id="run1:exploration:explore_test",
                discovered_at=datetime(2026, 10, 7, tzinfo=UTC),
            ),
            TopicExplorationTitleHit(
                video_id="v2",
                channel_id="c2",
                title="Duckrooms horror",
                exploration_query_id="explore_test",
                exploration_query_text="broad",
                discovery_run_id="run1:exploration:explore_test",
                discovered_at=datetime(2026, 10, 7, tzinfo=UTC),
            ),
        )

    s1 = factory()
    scan = TopicExplorationScanSummary(
        query_id="explore_test",
        query_text="broad",
        discovery_run_id="run1:exploration:explore_test",
        started_at=datetime(2026, 10, 7, tzinfo=UTC),
        finished_at=datetime(2026, 10, 7, 1, tzinfo=UTC),
        max_pages=3,
        title_hits=hits(),
        status="ok",
        pass_id=1,
        pass_fingerprint="fp_test_ok",
        settings_version="sv1",
        pages_requested=3,
        pages_scanned=3,
    )
    from app.models.orm import TopicExplorationPass

    s1.add(
        TopicExplorationPass(
            id=1,
            cycle_discovery_run_id="run1",
            pass_discovery_run_id=scan.discovery_run_id,
            exploration_query_id="explore_test",
            exploration_query_text="broad",
            observed_at=scan.started_at,
            finished_at=scan.finished_at,
            status="ok",
            pages_requested=3,
            pages_scanned=3,
            unique_videos_observed=2,
            settings_version="sv1",
            pass_fingerprint="fp_test_ok",
        ),
    )
    s1.commit()
    build_topic_exploration_preview(
        s1,
        discovery_run_id="run1",
        exploration_scans=(scan,),
        record_phrase_stats=True,
    )
    s1.commit()
    s1.close()

    s2 = factory()
    preview2 = build_topic_exploration_preview(
        s2,
        discovery_run_id="run2",
        exploration_scans=(scan,),
        record_phrase_stats=False,
    )
    duck = next((p for p in preview2.proposed if p.normalized_phrase == "duckrooms"), None)
    assert duck is not None
    assert "first_seen_exploration" not in duck.novelty_signals


def test_failed_scan_persisted_not_zero_observation() -> None:
    session = _session()
    scan = TopicExplorationScanSummary(
        query_id="q",
        query_text="broad",
        discovery_run_id="run:exploration:q",
        started_at=utc_now(),
        finished_at=utc_now(),
        max_pages=0,
        title_hits=(),
        status="failed",
        errors=("timeout",),
        pages_requested=3,
        pages_scanned=0,
        settings_version="sv1",
        pass_fingerprint="fp_failed",
    )
    from app.services.topic_exploration_evidence_storage import persist_exploration_pass_evidence

    persist_exploration_pass_evidence(
        session,
        cycle_discovery_run_id="run",
        scan_summary=scan,
        settings_version="sv1",
        pages_requested=3,
    )
    session.commit()
    stats = list(session.scalars(select(TopicExplorationPhrasePassStat)).all())
    assert stats == []
    row = session.scalar(select(TopicExplorationPass))
    assert row is not None
    assert row.status == "failed"


def test_admission_provenance_and_anchor_not_scheduled() -> None:
    session = _session()
    anchor = TargetKeyword(
        keyword="broad horror rooms gameplay",
        lifecycle_status=LIFECYCLE_PROBATION,
        source_type=SOURCE_EXPLORATION,
        parent_keyword_id=None,
        scan_interval_seconds=60,
        next_scan_at=utc_now() - timedelta(minutes=5),
    )
    session.add(anchor)
    session.add(
        TargetKeyword(
            keyword="seed kw",
            lifecycle_status=LIFECYCLE_PROBATION,
            source_type=SOURCE_SEED,
            scan_interval_seconds=60,
            next_scan_at=utc_now() - timedelta(minutes=5),
        ),
    )
    session.commit()

    selected = select_discovery_keywords(session, batch_size=5)
    assert all(k.id != anchor.id for k in selected)

    from app.services.topic_exploration_evidence_storage import persist_exploration_pass_evidence

    scan = TopicExplorationScanSummary(
        query_id="explore_test",
        query_text=anchor.keyword,
        discovery_run_id="run:exploration:explore_test",
        started_at=utc_now(),
        finished_at=utc_now(),
        max_pages=3,
        title_hits=(
            TopicExplorationTitleHit(
                video_id="v1",
                channel_id="c1",
                title="Duckrooms gameplay",
                exploration_query_id="explore_test",
                exploration_query_text=anchor.keyword,
                discovery_run_id="run:exploration:explore_test",
                discovered_at=utc_now(),
            ),
            TopicExplorationTitleHit(
                video_id="v2",
                channel_id="c2",
                title="Duckrooms horror",
                exploration_query_id="explore_test",
                exploration_query_text=anchor.keyword,
                discovery_run_id="run:exploration:explore_test",
                discovered_at=utc_now(),
            ),
        ),
        status="ok",
        pass_fingerprint="fp1",
        settings_version="sv1",
        pages_requested=3,
        pages_scanned=3,
    )
    pass_row = persist_exploration_pass_evidence(
        session,
        cycle_discovery_run_id="run",
        scan_summary=scan,
        settings_version="sv1",
        pages_requested=3,
    )
    from dataclasses import replace

    scan = replace(scan, pass_id=pass_row.id)
    preview = build_topic_exploration_preview(
        session,
        discovery_run_id="run",
        exploration_scans=(scan,),
        record_phrase_stats=True,
    )
    admitted, _ = admit_topic_exploration_preview(
        session,
        preview,
        exploration_parent_by_query_id={"explore_test": (anchor.id, anchor.keyword)},
        dry_run=False,
    )
    session.commit()
    assert admitted == 1
    stat = session.scalar(
        select(TopicExplorationPhrasePassStat).where(
            TopicExplorationPhrasePassStat.normalized_phrase == "duckrooms",
        ),
    )
    assert stat is not None
    assert stat.admitted_keyword_id is not None
    event = session.scalar(select(KeywordExpansionEvent))
    assert event is not None
    assert event.discovery_run_id == "run"


def test_disabled_exploration_no_evidence_tables_required_for_seeds() -> None:
    session = _session()
    session.add(
        TargetKeyword(
            keyword="seed",
            lifecycle_status=LIFECYCLE_PROBATION,
            source_type=SOURCE_SEED,
            scan_interval_seconds=60,
            next_scan_at=utc_now() - timedelta(minutes=1),
        ),
    )
    session.commit()

    async def fake_scan(*_a, **_k):
        return KeywordDiscoveryScanResult(keyword="seed", keyword_id=1, unique_videos=[])

    with patch("app.services.discovery_cycle.scan_keyword_for_discovery", side_effect=fake_scan):
        outcome = run_discovery_cycle(
            session,
            config=DiscoveryCycleConfig(keyword_batch_size=1),
            dry_run=True,
        )
    assert outcome.summary.exploration_query_count == 0
    assert session.scalar(select(TopicExplorationPass)) is None


def _run_all() -> None:
    tests = [
        test_exploration_cycle_persists_video_and_evidence,
        test_enrichment_handoff_cycle_video_band,
        test_first_seen_survives_new_session,
        test_failed_scan_persisted_not_zero_observation,
        test_admission_provenance_and_anchor_not_scheduled,
        test_disabled_exploration_no_evidence_tables_required_for_seeds,
    ]
    for fn in tests:
        fn()
        print(f"OK {fn.__name__}")


if __name__ == "__main__":
    _run_all()
