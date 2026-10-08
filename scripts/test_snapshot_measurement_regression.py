"""Stage 1 — derived snapshot measurement regression (no network)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.orm import Base, Channel, KeywordDiscoveryHit, TargetKeyword, Video, VideoFormat, VideoSnapshot
from app.services.attention_acceleration import classify_acceleration
from app.services.monitoring_video_source import _state_from_video
from app.services.snapshot_measurement import (
    derive_measurement_at_snapshot,
    vph_series_from_snapshots,
)
from app.services.video_published_at import PUBLISHED_AT_SOURCE_API, PUBLISHED_AT_SOURCE_INNERTUBE

UTC = timezone.utc


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _video(session, vid: str, pub: datetime, *, source: str = PUBLISHED_AT_SOURCE_INNERTUBE):
    session.add(
        Channel(id="c1", title="c", subscribers_count=100, created_at=pub),
    )
    session.add(
        Video(
            id=vid,
            title="t",
            channel_id="c1",
            published_at=pub,
            published_at_source=source,
            content_format=VideoFormat.UNKNOWN,
            views_count=0,
        ),
    )


def test_stale_snapshot_vph_replaced_after_api_published_at_fix() -> None:
    session = _session()
    wrong_pub = datetime(2026, 10, 6, 0, 0, tzinfo=UTC)
    fixed_pub = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    captured = datetime(2026, 10, 3, 0, 0, tzinfo=UTC)
    _video(session, "v1", wrong_pub, source=PUBLISHED_AT_SOURCE_INNERTUBE)
    session.commit()
    video = session.get(Video, "v1")
    video.published_at = fixed_pub
    video.published_at_source = PUBLISHED_AT_SOURCE_API
    snap = VideoSnapshot(
        video_id="v1",
        channel_id="c1",
        captured_at=captured,
        published_at=wrong_pub,
        age_hours=48.0,
        views=4800,
        vph=100.0,
        source="t",
        run_id="r",
        fetch_status="ok",
    )
    m = derive_measurement_at_snapshot(video=video, snapshot=snap)
    assert snap.vph == 100.0
    assert m.average_vph == round(4800 / 48.0, 4)
    state = _state_from_video(video, now=datetime(2026, 10, 10, tzinfo=UTC), latest_snapshot=snap)
    assert state.raw_vph == m.average_vph


def test_vph_at_measurement_stable_when_now_moves() -> None:
    session = _session()
    pub = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    captured = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    _video(session, "v1", pub, source=PUBLISHED_AT_SOURCE_API)
    session.commit()
    video = session.get(Video, "v1")
    snap = VideoSnapshot(
        video_id="v1",
        channel_id="c1",
        captured_at=captured,
        published_at=pub,
        age_hours=48.0,
        views=9600,
        vph=50.0,
        source="t",
        run_id="r",
        fetch_status="ok",
    )
    now_a = datetime(2026, 9, 10, tzinfo=UTC)
    now_b = datetime(2026, 10, 10, tzinfo=UTC)
    state_a = _state_from_video(video, now=now_a, latest_snapshot=snap)
    state_b = _state_from_video(video, now=now_b, latest_snapshot=snap)
    assert state_a.raw_vph == state_b.raw_vph == 200.0
    assert state_a.age_hours != state_b.age_hours


def test_two_snapshots_same_views_different_measured_vph() -> None:
    session = _session()
    pub = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    _video(session, "v1", pub, source=PUBLISHED_AT_SOURCE_API)
    session.commit()
    video = session.get(Video, "v1")
    s1 = VideoSnapshot(
        video_id="v1",
        channel_id="c1",
        captured_at=pub + timedelta(hours=24),
        published_at=pub,
        age_hours=24.0,
        views=1000,
        vph=999.0,
        source="t",
        run_id="r",
        fetch_status="ok",
    )
    s2 = VideoSnapshot(
        video_id="v1",
        channel_id="c1",
        captured_at=pub + timedelta(hours=48),
        published_at=pub,
        age_hours=48.0,
        views=1000,
        vph=999.0,
        source="t",
        run_id="r",
        fetch_status="ok",
    )
    m1 = derive_measurement_at_snapshot(video=video, snapshot=s1)
    m2 = derive_measurement_at_snapshot(video=video, snapshot=s2)
    assert m1.average_vph == round(1000 / 24.0, 4)
    assert m2.average_vph == round(1000 / 48.0, 4)


def test_invalid_age_yields_unavailable() -> None:
    session = _session()
    pub = datetime(2026, 9, 5, 0, 0, tzinfo=UTC)
    _video(session, "v1", pub, source=PUBLISHED_AT_SOURCE_API)
    session.commit()
    video = session.get(Video, "v1")
    snap = VideoSnapshot(
        video_id="v1",
        channel_id="c1",
        captured_at=pub - timedelta(hours=1),
        published_at=pub,
        age_hours=0.0,
        views=100,
        vph=10.0,
        source="t",
        run_id="r",
        fetch_status="ok",
    )
    m = derive_measurement_at_snapshot(video=video, snapshot=snap)
    assert m.average_vph is None


def test_acceleration_uses_derived_series_and_excludes_future() -> None:
    session = _session()
    pub = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    _video(session, "v1", pub, source=PUBLISHED_AT_SOURCE_API)
    session.commit()
    video = session.get(Video, "v1")
    snaps = []
    for hours, views, stored_vph in ((24, 100, 1.0), (48, 400, 1.0), (72, 900, 1.0)):
        snaps.append(
            VideoSnapshot(
                video_id="v1",
                channel_id="c1",
                captured_at=pub + timedelta(hours=hours),
                published_at=pub,
                age_hours=float(hours),
                views=views,
                vph=stored_vph,
                source="t",
                run_id="r",
                fetch_status="ok",
            ),
        )
    future = VideoSnapshot(
        video_id="v1",
        channel_id="c1",
        captured_at=pub + timedelta(hours=200),
        published_at=pub,
        age_hours=200.0,
        views=99999,
        vph=99999.0,
        source="t",
        run_id="r",
        fetch_status="ok",
    )
    compute = pub + timedelta(hours=80)
    series = vph_series_from_snapshots(
        video=video,
        snapshots=[*snaps, future],
        compute_before=compute,
    )
    assert classify_acceleration(series) == "accelerating"
    assert all(v != 1.0 for v in series if v is not None)


def test_discovery_skips_invalid_early_hit() -> None:
    from app.services.snapshot_measurement import select_discovery_hit_for_measurement

    session = _session()
    pub = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    _video(session, "v1", pub, source=PUBLISHED_AT_SOURCE_API)
    discovered_bad = pub - timedelta(hours=1)
    discovered_good = pub + timedelta(hours=6)
    session.add(TargetKeyword(id=1, keyword="kw", lifecycle_status="active"))
    session.add(
        KeywordDiscoveryHit(
            keyword_id=1,
            video_id="v1",
            channel_id="c1",
            discovery_run_id="run1",
            discovered_at=discovered_bad,
            views_at_discovery=999,
        ),
    )
    session.add(
        KeywordDiscoveryHit(
            keyword_id=1,
            video_id="v1",
            channel_id="c1",
            discovery_run_id="run2",
            discovered_at=discovered_good,
            views_at_discovery=600,
        ),
    )
    session.commit()
    video = session.get(Video, "v1")
    hits = list(
        session.scalars(
            __import__("sqlalchemy").select(KeywordDiscoveryHit).where(KeywordDiscoveryHit.video_id == "v1"),
        ).all(),
    )
    picked = select_discovery_hit_for_measurement(video=video, hits=hits)
    assert picked is not None
    from app.services.metrics import ensure_utc

    assert ensure_utc(picked.discovered_at) == ensure_utc(discovered_good)


def test_discovery_measurement_uses_discovered_at_not_now() -> None:
    session = _session()
    pub = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    _video(session, "v1", pub, source=PUBLISHED_AT_SOURCE_API)
    discovered = datetime(2026, 9, 2, 0, 0, tzinfo=UTC)
    session.add(TargetKeyword(id=1, keyword="kw", lifecycle_status="active"))
    session.add(
        KeywordDiscoveryHit(
            keyword_id=1,
            video_id="v1",
            channel_id="c1",
            discovery_run_id="run1",
            discovered_at=discovered,
            views_at_discovery=2400,
        ),
    )
    session.commit()
    video = session.get(Video, "v1")
    hit = session.scalars(
        __import__("sqlalchemy").select(KeywordDiscoveryHit).where(KeywordDiscoveryHit.video_id == "v1"),
    ).first()
    state = _state_from_video(
        video,
        now=datetime(2026, 12, 1, tzinfo=UTC),
        latest_snapshot=None,
        discovery_hits=[hit] if hit else [],
    )
    assert state.raw_vph == round(2400 / 24.0, 4)


def main() -> int:
    test_stale_snapshot_vph_replaced_after_api_published_at_fix()
    test_vph_at_measurement_stable_when_now_moves()
    test_two_snapshots_same_views_different_measured_vph()
    test_invalid_age_yields_unavailable()
    test_acceleration_uses_derived_series_and_excludes_future()
    test_discovery_skips_invalid_early_hit()
    test_discovery_measurement_uses_discovered_at_not_now()
    print("OK snapshot measurement regression")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
