"""Stage 1.23C.1B.3 — batch provenance / N+1 elimination tests."""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.models.orm  # noqa: F401
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.db import Base
from app.models.orm import (
    Channel,
    DailyIntelligenceReport,
    DailyIntelligenceReportWinnerFinding,
    DailyIntelligenceRunSnapshot,
    DailyIntelligenceRunWinnerAppearance,
    KeywordDiscoveryHit,
    TargetKeyword,
    Video,
    VideoSnapshot,
)
from app.services import daily_intelligence_outcome_followup as followup_mod
from app.services.daily_intelligence_outcome_followup import (
    get_report_outcome_coverage,
    get_winner_outcome_followup,
)
from app.services.video_snapshot_storage import get_latest_snapshots_for_videos

UTC = timezone.utc
REPORT_DATE = date(2026, 10, 10)
DISCOVERY = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
EDITION = datetime(2026, 10, 10, 18, 0, tzinfo=UTC)
REF = DISCOVERY + timedelta(days=30)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed_winner(
    session,
    *,
    video_id: str,
    rank: int,
    frozen_views: int,
    snapshots: list[tuple[datetime, int]],
) -> None:
    if rank == 1:
        session.add(
            DailyIntelligenceReport(
                report_date=REPORT_DATE,
                status="complete",
                source_run_id="run1",
                source_computed_at=EDITION,
                generated_at=EDITION,
                locked_at=EDITION + timedelta(hours=1),
                publish_attempt=1,
                summary_json="{}",
            ),
        )
        session.add(Channel(id="ch1", title="C", subscribers_count=1, created_at=DISCOVERY))
        session.add(TargetKeyword(id=1, keyword="kw", created_at=DISCOVERY))
        session.add(
            DailyIntelligenceRunSnapshot(
                source_run_id="run1",
                report_date=REPORT_DATE,
                source_computed_at=EDITION,
                captured_at=EDITION,
                winner_count=10,
                family_count=0,
            ),
        )
    session.add(Video(id=video_id, channel_id="ch1", title=f"T{rank}", published_at=DISCOVERY, views_count=999_999))
    prov = {
        "available": True,
        "discovered_at": DISCOVERY.isoformat(),
        "keyword_id": 1,
        "views_at_discovery": 1000,
    }
    session.add(
        DailyIntelligenceReportWinnerFinding(
            report_date=REPORT_DATE,
            video_id=video_id,
            rank=rank,
            title=f"V{rank}",
            channel_id="ch1",
            discovery_provenance_json=json.dumps(prov),
            payload_json=json.dumps({"video_id": video_id, "views": frozen_views}),
        ),
    )
    session.add(
        KeywordDiscoveryHit(
            keyword_id=1,
            video_id=video_id,
            channel_id="ch1",
            discovered_at=DISCOVERY,
            views_at_discovery=1000,
            discovery_run_id="d1",
        ),
    )
    session.add(
        DailyIntelligenceRunWinnerAppearance(
            source_run_id="run1",
            report_date=REPORT_DATE,
            source_computed_at=EDITION,
            video_id=video_id,
            rank=rank,
            title=f"V{rank}",
            channel_id="ch1",
            discovery_provenance_json="{}",
            payload_json="{}",
        ),
    )
    for cap, views in snapshots:
        session.add(
            VideoSnapshot(
                video_id=video_id,
                channel_id="ch1",
                captured_at=cap,
                views=views,
                source="monitoring",
                run_id="r",
                fetch_status="ok",
            ),
        )


def _legacy_row_attention_prov(session, video_id: str, payload: dict, edition_signal) -> dict:
    """Per-winner latest lookup (pre-1.23C.1B.3 semantics reference)."""
    from app.services.daily_intelligence_outcome_followup import _resolve_attention_views_provenance

    snap = None
    if edition_signal is not None:
        snap = get_latest_snapshots_for_videos(session, [video_id], compute_before=edition_signal).get(
            video_id,
        )
    return _resolve_attention_views_provenance(
        payload=payload,
        edition_signal=edition_signal,
        edition_latest_snapshot=snap,
    )


def test_batch_coverage_calls_get_latest_once_for_many_winners() -> None:
    session = _session()
    for i in range(1, 11):
        vid = f"v{i:02d}"
        match_at = EDITION - timedelta(hours=1)
        _seed_winner(session, video_id=vid, rank=i, frozen_views=1000 + i, snapshots=[(match_at, 1000 + i)])
    session.commit()

    calls: list[int] = []
    original = get_latest_snapshots_for_videos

    def spy(session_arg, video_ids, **kwargs):
        calls.append(len(list(video_ids)))
        return original(session_arg, video_ids, **kwargs)

    with patch.object(followup_mod, "get_latest_snapshots_for_videos", side_effect=spy):
        cov = get_report_outcome_coverage(session, REPORT_DATE, reference_now=REF)

    assert cov is not None
    assert cov["winner_count"] == 10
    assert len(calls) == 1
    assert calls[0] == 10


def test_multiple_snapshots_picks_latest_at_or_before_edition() -> None:
    session = _session()
    early = EDITION - timedelta(hours=5)
    mid = EDITION - timedelta(hours=2)
    late = EDITION - timedelta(minutes=30)
    _seed_winner(
        session,
        video_id="v1",
        rank=1,
        frozen_views=5000,
        snapshots=[
            (early, 1000),
            (mid, 4000),
            (late, 5000),
        ],
    )
    session.commit()
    row = get_winner_outcome_followup(session, REPORT_DATE, "v1", reference_now=REF)
    assert row["attention_views_provenance"]["candidate_baseline_snapshot_at"] == late.isoformat()


def test_provenance_matches_legacy_per_winner_lookup() -> None:
    session = _session()
    _seed_winner(
        session,
        video_id="v1",
        rank=1,
        frozen_views=5000,
        snapshots=[
            (EDITION - timedelta(hours=3), 5000,),
            (EDITION + timedelta(hours=1), 5000),
        ],
    )
    session.commit()
    row = get_winner_outcome_followup(session, REPORT_DATE, "v1", reference_now=REF)
    from sqlalchemy import select

    finding = session.scalars(
        select(DailyIntelligenceReportWinnerFinding).where(
            DailyIntelligenceReportWinnerFinding.report_date == REPORT_DATE,
            DailyIntelligenceReportWinnerFinding.video_id == "v1",
        ),
    ).one()
    payload = json.loads(finding.payload_json)
    legacy = _legacy_row_attention_prov(session, "v1", payload, EDITION)
    assert row["attention_views_provenance"] == legacy


def test_detail_and_batch_overview_same_provenance_for_winner() -> None:
    session = _session()
    for i in range(1, 4):
        vid = f"v{i}"
        _seed_winner(
            session,
            video_id=vid,
            rank=i,
            frozen_views=2000 * i,
            snapshots=[(EDITION - timedelta(hours=i), 2000 * i)],
        )
    session.commit()
    cov = get_report_outcome_coverage(session, REPORT_DATE, reference_now=REF)
    detail = get_winner_outcome_followup(session, REPORT_DATE, "v2", reference_now=REF)
    item = next(x for x in cov["items"] if x["video_id"] == "v2")
    batch_row = get_winner_outcome_followup(session, REPORT_DATE, "v2", reference_now=REF)
    assert batch_row["attention_views_provenance"] == detail["attention_views_provenance"]
    assert batch_row["coverage_category"] == item["coverage_category"]
