"""Tests for monitoring tier and API budget policy (Stage 1.13A)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.monitoring_tier_budget_policy import (
    ApiBudgetPolicy,
    CaptureRequestBudgetContext,
    MonitoringTier,
    MonitoringTierPolicy,
    TierCandidateInput,
    allocate_capture_budget,
    apply_channel_active_cap,
    assign_monitoring_tiers,
    checkpoint_hours_for_tier,
    compute_vph_percentile_thresholds,
    snapshot_collection_policy_for_tier,
)
from app.services.snapshot_collection_policy import SnapshotCaptureRequest
from datetime import datetime, timezone


def _item(
    video_id: str,
    vph: float | None,
    *,
    age: float = 12.0,
    channel_id: str = "ch1",
    **kwargs: object,
) -> TierCandidateInput:
    return TierCandidateInput(
        video_id=video_id,
        channel_id=channel_id,
        raw_vph=vph,
        age_hours=age,
        **kwargs,  # type: ignore[arg-type]
    )


def test_percentile_pool_excludes_non_regular() -> None:
    items = [
        _item("a", 100.0),
        _item("s", 999.0, is_short=True),
    ]
    decisions = assign_monitoring_tiers(items)
    short = next(d for d in decisions if d.video_id == "s")
    assert short.tier == MonitoringTier.UNMONITORED
    regular = next(d for d in decisions if d.video_id == "a")
    assert regular.tier == MonitoringTier.A


def test_top_band_tier_a() -> None:
    items = [_item(f"v{i}", float(i)) for i in range(1, 21)]
    decisions = assign_monitoring_tiers(items)
    top = next(d for d in decisions if d.video_id == "v20")
    assert top.tier == MonitoringTier.A


def test_middle_band_tier_b() -> None:
    items = [_item(f"v{i}", float(i)) for i in range(1, 21)]
    decisions = assign_monitoring_tiers(items)
    mid = next(d for d in decisions if d.video_id == "v12")
    assert mid.tier == MonitoringTier.B


def test_lower_band_tier_c() -> None:
    items = [_item(f"v{i}", float(i)) for i in range(1, 21)]
    decisions = assign_monitoring_tiers(items)
    low = next(d for d in decisions if d.video_id == "v3")
    assert low.tier == MonitoringTier.C


def test_missing_vph_unmonitored() -> None:
    decisions = assign_monitoring_tiers([_item("x", None)])
    assert decisions[0].tier == MonitoringTier.UNMONITORED
    assert decisions[0].excluded_reason == "missing_vph"


def test_missing_baseline_no_downgrade() -> None:
    base = assign_monitoring_tiers([_item("v1", 50.0), _item("v2", 100.0)])
    with_base = assign_monitoring_tiers(
        [
            _item("v1", 50.0, channel_velocity_baseline_status=None),
            _item("v2", 100.0, channel_velocity_baseline_status="unavailable"),
        ],
    )
    assert base[0].tier == with_base[0].tier


def test_velocity_promotion_one_tier() -> None:
    items = [
        _item("c", 10.0, channel_velocity_baseline_status="ok", vph_vs_channel_median=4.0),
        _item("b", 60.0, channel_velocity_baseline_status="partial", vph_vs_channel_median=4.0),
    ]
    decisions = assign_monitoring_tiers(items)
    c = next(d for d in decisions if d.video_id == "c")
    b = next(d for d in decisions if d.video_id == "b")
    assert c.tier == MonitoringTier.B
    assert b.tier == MonitoringTier.A


def test_c_cannot_jump_to_a() -> None:
    decisions = assign_monitoring_tiers(
        [
            _item("c", 5.0, channel_velocity_baseline_status="ok", vph_vs_channel_median=10.0),
            _item("anchor", 100.0),
        ],
    )
    c = next(d for d in decisions if d.video_id == "c")
    assert c.tier != MonitoringTier.A


def test_stale_age_blocks_tier_a() -> None:
    items = [_item(f"v{i}", float(i)) for i in range(1, 21)]
    items.append(_item("old", 1000.0, age=30.0))
    decisions = assign_monitoring_tiers(items)
    old = next(d for d in decisions if d.video_id == "old")
    assert old.tier != MonitoringTier.A


def test_short_live_unmonitored() -> None:
    assert assign_monitoring_tiers([_item("s", 10.0, is_short=True)])[0].tier == MonitoringTier.UNMONITORED
    assert assign_monitoring_tiers([_item("l", 10.0, is_live=True)])[0].tier == MonitoringTier.UNMONITORED


def test_channel_cap_max_three() -> None:
    items = [_item(f"v{i}", float(i), channel_id="chX") for i in range(1, 6)]
    decisions = assign_monitoring_tiers(items)
    cap = apply_channel_active_cap(decisions, 3)
    assert len(cap.retained) == 3
    assert len(cap.excluded) >= 2


def test_channel_cap_deterministic() -> None:
    items = [_item(f"v{i}", float(i), channel_id="chX") for i in range(1, 6)]
    d1 = apply_channel_active_cap(assign_monitoring_tiers(items), 3)
    d2 = apply_channel_active_cap(assign_monitoring_tiers(list(reversed(items))), 3)
    assert [r.video_id for r in d1.retained] == [r.video_id for r in d2.retained]


def test_channel_cap_prefers_tier_a() -> None:
    policy = MonitoringTierPolicy(max_active_videos_per_channel=2)
    items = [
        _item("a", 100.0, channel_id="ch1"),
        _item("c", 1.0, channel_id="ch1"),
        _item("b", 50.0, channel_id="ch1"),
    ]
    cap = apply_channel_active_cap(assign_monitoring_tiers(items, policy), 2)
    retained_ids = {r.video_id for r in cap.retained}
    assert "a" in retained_ids
    assert "b" in retained_ids


def test_younger_preferred_same_tier() -> None:
    items = [
        _item("old", 90.0, age=20.0, channel_id="ch1"),
        _item("young", 90.0, age=10.0, channel_id="ch1"),
        _item("fill", 1.0, channel_id="ch1"),
    ]
    cap = apply_channel_active_cap(assign_monitoring_tiers(items), 2)
    retained_ids = {r.video_id for r in cap.retained}
    assert "young" in retained_ids


def test_higher_vph_preferred_same_tier_age() -> None:
    items = [
        _item("low", 80.0, age=10.0, channel_id="ch1"),
        _item("high", 95.0, age=10.0, channel_id="ch1"),
        _item("fill", 1.0, channel_id="ch1"),
    ]
    cap = apply_channel_active_cap(assign_monitoring_tiers(items), 2)
    retained_ids = {r.video_id for r in cap.retained}
    assert "high" in retained_ids


def test_global_budget_respected() -> None:
    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    contexts = [
        CaptureRequestBudgetContext(
            request=SnapshotCaptureRequest(
                video_id=f"v{i}",
                channel_id="ch",
                checkpoint_age_hours=24,
                reason="due",
                requested_at=now,
                current_age_hours=24.0,
                source="test",
                run_id=f"r{i}",
            ),
            tier=MonitoringTier.A,
            raw_vph=float(i),
            is_overdue=False,
            time_to_checkpoint_expiry_hours=10.0,
        )
        for i in range(20)
    ]
    result = allocate_capture_budget(contexts, ApiBudgetPolicy(max_capture_requests_per_cycle=5))
    assert result.selected_for_capture_count == 5
    assert result.deferred_count == 15


def test_overdue_near_expiry_first() -> None:
    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    contexts = [
        CaptureRequestBudgetContext(
            request=SnapshotCaptureRequest("v1", "ch", 24, "overdue", now, 30.0, "t", "a"),
            tier=MonitoringTier.B,
            raw_vph=10.0,
            is_overdue=True,
            time_to_checkpoint_expiry_hours=1.0,
        ),
        CaptureRequestBudgetContext(
            request=SnapshotCaptureRequest("v2", "ch", 24, "overdue", now, 30.0, "t", "b"),
            tier=MonitoringTier.A,
            raw_vph=100.0,
            is_overdue=True,
            time_to_checkpoint_expiry_hours=5.0,
        ),
    ]
    result = allocate_capture_budget(contexts, ApiBudgetPolicy(max_capture_requests_per_cycle=1))
    assert result.selected_requests[0].video_id == "v1"


def test_cp24_momentum_deadline_before_later_overdue_checkpoint() -> None:
    """Due cp24 inside Momentum window beats overdue checkpoint with later expiry."""
    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    contexts = [
        CaptureRequestBudgetContext(
            request=SnapshotCaptureRequest("cp24", "ch", 24, "due", now, 28.0, "t", "m"),
            tier=MonitoringTier.A,
            raw_vph=500.0,
            is_overdue=False,
            time_to_checkpoint_expiry_hours=2.0,
            time_to_momentum_vph_deadline_hours=1.0,
        ),
        CaptureRequestBudgetContext(
            request=SnapshotCaptureRequest("cp12_od", "ch2", 12, "overdue", now, 30.0, "t", "o"),
            tier=MonitoringTier.C,
            raw_vph=1.0,
            is_overdue=True,
            time_to_checkpoint_expiry_hours=5.0,
            time_to_momentum_vph_deadline_hours=None,
        ),
    ]
    result = allocate_capture_budget(contexts, ApiBudgetPolicy(max_capture_requests_per_cycle=1))
    assert result.selected_requests[0].video_id == "cp24"


def test_sooner_overdue_still_wins_over_later_cp24_momentum() -> None:
    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    contexts = [
        CaptureRequestBudgetContext(
            request=SnapshotCaptureRequest("cp24", "ch", 24, "due", now, 28.0, "t", "m"),
            tier=MonitoringTier.A,
            raw_vph=500.0,
            is_overdue=False,
            time_to_checkpoint_expiry_hours=2.0,
            time_to_momentum_vph_deadline_hours=2.0,
        ),
        CaptureRequestBudgetContext(
            request=SnapshotCaptureRequest("cp6_od", "ch2", 6, "overdue", now, 30.0, "t", "o"),
            tier=MonitoringTier.C,
            raw_vph=1.0,
            is_overdue=True,
            time_to_checkpoint_expiry_hours=0.5,
            time_to_momentum_vph_deadline_hours=None,
        ),
    ]
    result = allocate_capture_budget(contexts, ApiBudgetPolicy(max_capture_requests_per_cycle=1))
    assert result.selected_requests[0].video_id == "cp6_od"


def test_momentum_cp24_deadline_before_tier() -> None:
    """cp24 inside momentum VPH window outranks higher tier with loose checkpoint expiry."""
    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    contexts = [
        CaptureRequestBudgetContext(
            request=SnapshotCaptureRequest("tier_a", "ch", 24, "due", now, 28.0, "t", "a"),
            tier=MonitoringTier.A,
            raw_vph=500.0,
            is_overdue=False,
            time_to_checkpoint_expiry_hours=8.0,
            time_to_momentum_vph_deadline_hours=None,
        ),
        CaptureRequestBudgetContext(
            request=SnapshotCaptureRequest("urgent", "ch", 24, "due", now, 28.0, "t", "u"),
            tier=MonitoringTier.C,
            raw_vph=1.0,
            is_overdue=False,
            time_to_checkpoint_expiry_hours=8.0,
            time_to_momentum_vph_deadline_hours=2.0,
        ),
    ]
    result = allocate_capture_budget(contexts, ApiBudgetPolicy(max_capture_requests_per_cycle=1))
    assert result.selected_requests[0].video_id == "urgent"


def test_tier_a_before_b_in_budget() -> None:
    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    contexts = [
        CaptureRequestBudgetContext(
            request=SnapshotCaptureRequest("b", "ch", 24, "due", now, 24.0, "t", "b"),
            tier=MonitoringTier.B,
            raw_vph=50.0,
            is_overdue=False,
            time_to_checkpoint_expiry_hours=10.0,
        ),
        CaptureRequestBudgetContext(
            request=SnapshotCaptureRequest("a", "ch", 24, "due", now, 24.0, "t", "a"),
            tier=MonitoringTier.A,
            raw_vph=50.0,
            is_overdue=False,
            time_to_checkpoint_expiry_hours=10.0,
        ),
    ]
    result = allocate_capture_budget(contexts, ApiBudgetPolicy(max_capture_requests_per_cycle=1))
    assert result.selected_requests[0].video_id == "a"


def test_tier_b_before_c_in_budget() -> None:
    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    contexts = [
        CaptureRequestBudgetContext(
            request=SnapshotCaptureRequest("c", "ch", 24, "due", now, 24.0, "t", "c"),
            tier=MonitoringTier.C,
            raw_vph=50.0,
            is_overdue=False,
            time_to_checkpoint_expiry_hours=10.0,
        ),
        CaptureRequestBudgetContext(
            request=SnapshotCaptureRequest("b", "ch", 24, "due", now, 24.0, "t", "b"),
            tier=MonitoringTier.B,
            raw_vph=50.0,
            is_overdue=False,
            time_to_checkpoint_expiry_hours=10.0,
        ),
    ]
    result = allocate_capture_budget(contexts, ApiBudgetPolicy(max_capture_requests_per_cycle=1))
    assert result.selected_requests[0].video_id == "b"


def test_tier_c_fairness_reservation() -> None:
    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    contexts: list[CaptureRequestBudgetContext] = []
    for i in range(10):
        contexts.append(
            CaptureRequestBudgetContext(
                request=SnapshotCaptureRequest(f"a{i}", "ch", 24, "due", now, 24.0, "t", f"a{i}"),
                tier=MonitoringTier.A,
                raw_vph=100.0 + i,
                is_overdue=False,
                time_to_checkpoint_expiry_hours=10.0,
            ),
        )
    for i in range(5):
        contexts.append(
            CaptureRequestBudgetContext(
                request=SnapshotCaptureRequest(f"c{i}", "ch", 24, "due", now, 24.0, "t", f"c{i}"),
                tier=MonitoringTier.C,
                raw_vph=1.0 + i,
                is_overdue=False,
                time_to_checkpoint_expiry_hours=10.0,
            ),
        )
    result = allocate_capture_budget(
        contexts,
        ApiBudgetPolicy(max_capture_requests_per_cycle=10, tier_c_fair_share_fraction=0.2),
    )
    selected_ids = {r.video_id for r in result.selected_requests}
    assert any(vid.startswith("c") for vid in selected_ids)
    assert result.fairness_reserved_count >= 1


def test_tier_c_not_starved_in_repeated_batches() -> None:
    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    contexts = [
        CaptureRequestBudgetContext(
            request=SnapshotCaptureRequest(f"c{i}", "ch", 24, "due", now, 24.0, "t", f"c{i}"),
            tier=MonitoringTier.C,
            raw_vph=float(i),
            is_overdue=False,
            time_to_checkpoint_expiry_hours=5.0,
        )
        for i in range(8)
    ]
    r1 = allocate_capture_budget(contexts, ApiBudgetPolicy(max_capture_requests_per_cycle=3, tier_c_fair_share_fraction=0.34))
    r2 = allocate_capture_budget(contexts, ApiBudgetPolicy(max_capture_requests_per_cycle=3, tier_c_fair_share_fraction=0.34))
    assert r1.selected_for_capture_count == 3
    assert r2.selected_for_capture_count == 3


def test_tier_checkpoint_schedules() -> None:
    policy = MonitoringTierPolicy()
    assert checkpoint_hours_for_tier(MonitoringTier.A, policy) == (6, 12, 24, 48, 72)
    assert checkpoint_hours_for_tier(MonitoringTier.B, policy) == (12, 24, 48, 72)
    assert checkpoint_hours_for_tier(MonitoringTier.C, policy) == (24, 72)
    assert snapshot_collection_policy_for_tier(MonitoringTier.C, policy).checkpoint_hours == (24, 72)


def test_batch_assignment_deterministic() -> None:
    items = [_item(f"v{i}", float(i)) for i in range(10, 0, -1)]
    first = assign_monitoring_tiers(items)
    second = assign_monitoring_tiers(list(reversed(items)))
    assert [(d.video_id, d.tier) for d in first] == [(d.video_id, d.tier) for d in second]


def test_no_outcome_fields_on_input_type() -> None:
    fields = TierCandidateInput.__dataclass_fields__
    forbidden = {"t24_views", "t72_views", "future_growth", "winner_label"}
    assert forbidden.isdisjoint(set(fields.keys()))


def test_vph_thresholds_from_pool_only() -> None:
    pool = [float(i) for i in range(1, 11)]
    p50, p85 = compute_vph_percentile_thresholds(pool, MonitoringTierPolicy())
    assert p50 is not None and p85 is not None
    assert p85 > p50


def _run_regression(script: str) -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise AssertionError(f"{script} failed:\n{proc.stdout}\n{proc.stderr}")


def test_regressions_stage_111_112() -> None:
    _run_regression("test_snapshot_collection_policy.py")
    _run_regression("test_video_snapshot_storage.py")
    _run_regression("test_channel_velocity_baseline.py")


def main() -> None:
    tests = [
        test_percentile_pool_excludes_non_regular,
        test_top_band_tier_a,
        test_middle_band_tier_b,
        test_lower_band_tier_c,
        test_missing_vph_unmonitored,
        test_missing_baseline_no_downgrade,
        test_velocity_promotion_one_tier,
        test_c_cannot_jump_to_a,
        test_stale_age_blocks_tier_a,
        test_short_live_unmonitored,
        test_channel_cap_max_three,
        test_channel_cap_deterministic,
        test_channel_cap_prefers_tier_a,
        test_younger_preferred_same_tier,
        test_higher_vph_preferred_same_tier_age,
        test_global_budget_respected,
        test_overdue_near_expiry_first,
        test_cp24_momentum_deadline_before_later_overdue_checkpoint,
        test_sooner_overdue_still_wins_over_later_cp24_momentum,
        test_momentum_cp24_deadline_before_tier,
        test_tier_a_before_b_in_budget,
        test_tier_b_before_c_in_budget,
        test_tier_c_fairness_reservation,
        test_tier_c_not_starved_in_repeated_batches,
        test_tier_checkpoint_schedules,
        test_batch_assignment_deterministic,
        test_no_outcome_fields_on_input_type,
        test_vph_thresholds_from_pool_only,
        test_regressions_stage_111_112,
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
        raise SystemExit(f"{failed} test(s) failed")
    print("All monitoring tier budget policy tests passed.")


if __name__ == "__main__":
    main()
