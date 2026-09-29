"""Smoke tests for RadarCandidate dataset export (Stage 1.5)."""

from __future__ import annotations

import asyncio
import copy
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.youtube.client import VideoSearchModel
from app.models.orm import ExplosiveChannelSettings
from app.services.explosive_channels_service import (
    DEFAULT_MIN_VIEWS,
    DEFAULT_MIN_VIRAL_COEFF,
    ExplosiveChannelThresholds,
    ExplosiveChannelsService,
)
from app.services.radar_candidate import (
    DISCOVERY_SOURCE_INNERTUBE,
    QUALIFICATION_PARSE_ERROR,
    QUALIFICATION_PASSED,
    QUALIFICATION_REJECTED,
    RadarCandidate,
)
from app.services.radar_candidate_dataset import (
    build_dataset_metadata,
    count_candidate_states,
    export_candidate_dataset,
    export_candidates_jsonl,
    serialize_candidate,
    validate_dataset_invariants,
)
from app.services.radar_filter_metrics import FILTER_SKIP_MIN_VIEWS


def _candidate(
    *,
    video_id: str = "vid1",
    state: str = QUALIFICATION_REJECTED,
    reason: str | None = FILTER_SKIP_MIN_VIEWS,
    viral: float | None = None,
    vph: float | None = 100.0,
    age: float | None = 3.0,
    subscribers: int | None = 0,
) -> RadarCandidate:
    return RadarCandidate(
        video_id=video_id,
        channel_id="UC1234567890123456789012",
        keyword="gaming",
        discovery_source=DISCOVERY_SOURCE_INNERTUBE,
        discovered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        video_title="Test title",
        channel_title="Test channel",
        published_text="3 days ago",
        views=1000,
        subscribers=subscribers,
        qualification_state=state,
        first_failure_reason=reason,
        viral_coefficient=viral,
        vph=vph,
        video_age_days=age,
    )


def test_serialize_candidate_fields() -> None:
    record = serialize_candidate(_candidate())
    assert record["keyword"] == "gaming"
    assert record["video_id"] == "vid1"
    assert record["qualification_state"] == QUALIFICATION_REJECTED
    assert record["first_failure_reason"] == FILTER_SKIP_MIN_VIEWS
    assert record["viral_coefficient"] is None
    assert record["vph"] == 100.0
    assert record["discovered_at"].endswith("+00:00")


def test_null_signals_preserved() -> None:
    record = serialize_candidate(_candidate(viral=None, vph=None, age=None))
    assert record["viral_coefficient"] is None
    assert record["vph"] is None
    assert record["video_age_days"] is None


def test_passed_and_rejected_and_parse_error_export() -> None:
    candidates = [
        _candidate(video_id="pass", state=QUALIFICATION_PASSED, reason=None, viral=5.0),
        _candidate(video_id="reject", state=QUALIFICATION_REJECTED),
        _candidate(
            video_id="err",
            state=QUALIFICATION_PARSE_ERROR,
            reason="parse_error",
            vph=None,
            age=None,
        ),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        jsonl_path, meta_path = export_candidate_dataset(
            candidates,
            keywords=["gaming"],
            output_dir=Path(tmp),
            source="test",
        )
        lines = jsonl_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 3
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["total_candidates"] == 3
        assert meta["total_passed"] == 1
        assert meta["total_rejected"] == 1
        assert meta["total_parse_errors"] == 1


def test_dataset_invariants() -> None:
    candidates = [
        _candidate(video_id="a", state=QUALIFICATION_PASSED, reason=None),
        _candidate(video_id="b", state=QUALIFICATION_REJECTED),
    ]
    validate_dataset_invariants(candidates)
    counts = count_candidate_states(candidates)
    assert counts["passed"] + counts["rejected"] + counts["parse_errors"] == len(candidates)


def test_export_does_not_mutate_candidates() -> None:
    candidates = [_candidate(video_id="a"), _candidate(video_id="b")]
    before = [copy.deepcopy(candidate) for candidate in candidates]
    with tempfile.TemporaryDirectory() as tmp:
        export_candidates_jsonl(candidates, Path(tmp) / "out.jsonl")
    assert candidates == before


async def test_register_channels_disabled_skips_registration() -> None:
    service = ExplosiveChannelsService()
    db = MagicMock()
    video = VideoSearchModel(
        video_id="pass",
        channel_id="UC1234567890123456789012",
        channel_title="Channel",
        title="Video",
        views_count=100_000,
        subscribers_count=10_000,
        published_text="3 days ago",
    )
    settings = ExplosiveChannelSettings(
        id=1,
        max_age_days=180,
        min_views=DEFAULT_MIN_VIEWS,
        min_viral_coeff=DEFAULT_MIN_VIRAL_COEFF,
        upload_period="all",
    )
    thresholds = ExplosiveChannelThresholds(
        min_views=DEFAULT_MIN_VIEWS,
        min_viral_coeff=DEFAULT_MIN_VIRAL_COEFF,
    )

    with patch.object(service, "_get_or_create_settings", return_value=settings):
        with patch.object(service, "get_thresholds", return_value=thresholds):
            with patch.object(service, "_register_channel_video") as register:
                with patch(
                    "app.services.explosive_channels_service.fetch_channel_subscribers_from_homepage",
                    new_callable=AsyncMock,
                    return_value=None,
                ):
                    with patch(
                        "app.services.explosive_channels_service.asyncio.sleep",
                        new_callable=AsyncMock,
                    ):
                        with_register = await service.process_radar_videos(db, [video])
                        without_register = await service.process_radar_videos(
                            db,
                            [video],
                            register_channels=False,
                        )

    register.assert_called_once()
    assert with_register.passed_count == without_register.passed_count
    assert len(with_register.hits) == 1
    assert len(without_register.hits) == 0
    db.flush.assert_called_once()


def test_metadata_counts() -> None:
    candidates = [_candidate(video_id="a"), _candidate(video_id="b", state=QUALIFICATION_PASSED, reason=None)]
    meta = build_dataset_metadata(keywords=["gaming"], candidates=candidates, source="test")
    assert meta.total_candidates == 2
    assert meta.total_passed == 1
    assert meta.total_rejected == 1


async def main() -> None:
    sync_tests = [
        test_serialize_candidate_fields,
        test_null_signals_preserved,
        test_passed_and_rejected_and_parse_error_export,
        test_dataset_invariants,
        test_export_does_not_mutate_candidates,
        test_metadata_counts,
    ]
    async_tests = [test_register_channels_disabled_skips_registration]

    failed = 0
    for test in sync_tests:
        try:
            test()
            print(f"OK {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")

    for test in async_tests:
        try:
            await test()
            print(f"OK {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")

    if failed:
        raise SystemExit(f"{failed} test(s) failed")
    print("All radar candidate dataset tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
