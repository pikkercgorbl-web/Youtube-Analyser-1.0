"""Deterministic snapshot revisit planning (Stage 1.12B — policy only, no scheduler)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Sequence

from sqlalchemy.orm import Session

from app.models.orm import VideoSnapshot
from app.services.metrics import ensure_utc
from app.services.video_snapshot_storage import get_snapshots_for_videos

CheckpointStatus = Literal["pending", "due", "completed", "overdue", "expired"]
MonitoringStatus = Literal["active", "stopped", "ineligible"]
RecommendedAction = Literal["none", "capture_now", "wait"]
CaptureReason = Literal["due", "overdue"]

DEFAULT_SNAPSHOT_CHECKPOINT_HOURS: tuple[int, ...] = (6, 12, 24, 48, 72)


@dataclass(frozen=True, slots=True)
class SnapshotCollectionPolicy:
    checkpoint_hours: tuple[int, ...] = DEFAULT_SNAPSHOT_CHECKPOINT_HOURS
    min_absolute_match_tolerance_hours: float = 1.0
    relative_match_tolerance_fraction: float = 0.15
    min_absolute_recovery_hours: float = 6.0
    relative_recovery_fraction: float = 0.50


@dataclass(frozen=True, slots=True)
class ExistingSnapshot:
    """Minimal snapshot view for checkpoint matching."""

    age_hours: float | None
    snapshot_id: int | None = None
    captured_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class VideoRevisitInput:
    video_id: str
    published_at: datetime | None
    channel_id: str | None = None
    content_format: str | None = None
    is_short: bool | None = None
    is_live: bool | None = None
    unavailable: bool = False


@dataclass(frozen=True, slots=True)
class CheckpointPlan:
    target_age_hours: int
    status: CheckpointStatus
    matched_snapshot_id: int | None
    matched_snapshot_age_hours: float | None
    min_match_age_hours: float
    max_match_age_hours: float
    expires_at_age_hours: float
    due_since_hours: float | None
    recommended_action: RecommendedAction


@dataclass(frozen=True, slots=True)
class VideoRevisitPlan:
    video_id: str
    channel_id: str | None
    current_age_hours: float | None
    monitoring_status: MonitoringStatus
    checkpoints: tuple[CheckpointPlan, ...]
    due_checkpoints: tuple[CheckpointPlan, ...]
    next_checkpoint_hours: int | None
    stop_reason: str | None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SnapshotCaptureRequest:
    video_id: str
    channel_id: str | None
    checkpoint_age_hours: int
    reason: CaptureReason
    requested_at: datetime
    current_age_hours: float
    source: str
    run_id: str
    outcome_target_at: datetime | None = None


def checkpoint_match_tolerance_hours(
    checkpoint_hours: int,
    policy: SnapshotCollectionPolicy,
) -> float:
    return max(
        policy.min_absolute_match_tolerance_hours,
        policy.relative_match_tolerance_fraction * float(checkpoint_hours),
    )


def checkpoint_match_window(
    checkpoint_hours: int,
    policy: SnapshotCollectionPolicy,
) -> tuple[float, float]:
    """Inclusive age_hours window that completes a checkpoint."""
    tolerance = checkpoint_match_tolerance_hours(checkpoint_hours, policy)
    lower = float(checkpoint_hours) - tolerance
    upper = float(checkpoint_hours) + tolerance
    return lower, upper


def checkpoint_expires_at_age_hours(
    checkpoint_hours: int,
    policy: SnapshotCollectionPolicy,
) -> float:
    recovery = max(
        policy.min_absolute_recovery_hours,
        policy.relative_recovery_fraction * float(checkpoint_hours),
    )
    return float(checkpoint_hours) + recovery


MONITORING_PLANNER_MAX_SNAPSHOT_AGE_HOURS: float = max(
    checkpoint_expires_at_age_hours(h, SnapshotCollectionPolicy())
    for h in DEFAULT_SNAPSHOT_CHECKPOINT_HOURS
)


def compute_video_age_hours(
    published_at: datetime,
    current_time: datetime,
) -> float | None:
    published = ensure_utc(published_at)
    current = ensure_utc(current_time)
    if current <= published:
        return None
    return round((current - published).total_seconds() / 3600.0, 4)


def snapshot_matches_checkpoint(
    snapshot_age_hours: float,
    checkpoint_hours: int,
    policy: SnapshotCollectionPolicy,
) -> bool:
    lower, upper = checkpoint_match_window(checkpoint_hours, policy)
    return lower <= snapshot_age_hours <= upper


def find_matching_snapshot(
    snapshots: Sequence[ExistingSnapshot],
    checkpoint_hours: int,
    policy: SnapshotCollectionPolicy,
) -> ExistingSnapshot | None:
    matches = [
        row
        for row in snapshots
        if row.age_hours is not None
        and snapshot_matches_checkpoint(float(row.age_hours), checkpoint_hours, policy)
    ]
    if not matches:
        return None
    return min(
        matches,
        key=lambda row: (
            abs(float(row.age_hours) - checkpoint_hours),  # type: ignore[arg-type]
            row.captured_at.timestamp() if row.captured_at is not None else 0.0,
        ),
    )


def evaluate_monitoring_eligibility(
    item: VideoRevisitInput,
) -> tuple[bool, str | None]:
    if not (item.video_id or "").strip():
        return False, "missing_video_id"
    if item.unavailable:
        return False, "video_unavailable"
    if item.is_short is True:
        return False, "short_format"
    if item.is_live is True:
        return False, "live_format"
    if item.content_format == "short":
        return False, "short_format"
    if item.content_format == "live":
        return False, "live_format"
    if item.published_at is None:
        return False, "missing_published_at"
    return True, None


def _checkpoint_status(
    *,
    checkpoint_hours: int,
    current_age_hours: float,
    matched: ExistingSnapshot | None,
    policy: SnapshotCollectionPolicy,
) -> tuple[CheckpointStatus, RecommendedAction, float | None]:
    if matched is not None:
        return "completed", "none", None

    expires_at = checkpoint_expires_at_age_hours(checkpoint_hours, policy)
    _, upper_match = checkpoint_match_window(checkpoint_hours, policy)

    if current_age_hours < float(checkpoint_hours):
        return "pending", "none", None

    if current_age_hours > expires_at:
        return "expired", "none", None

    due_since = round(max(0.0, current_age_hours - float(checkpoint_hours)), 4)
    if current_age_hours > upper_match:
        return "overdue", "capture_now", due_since
    return "due", "capture_now", due_since


def _monitoring_stop_reason(
    checkpoints: Sequence[CheckpointPlan],
    *,
    ineligible_reason: str | None,
) -> tuple[MonitoringStatus, str | None]:
    if ineligible_reason is not None:
        return "ineligible", ineligible_reason

    final_checkpoint = checkpoints[-1] if checkpoints else None
    if final_checkpoint is None:
        return "stopped", "no_checkpoints_configured"

    if final_checkpoint.status == "completed":
        return "stopped", "final_checkpoint_completed"

    if final_checkpoint.status == "expired":
        return "stopped", "final_checkpoint_expired"

    return "active", None


def plan_video_revisits(
    *,
    video_id: str,
    published_at: datetime | None,
    existing_snapshots: Sequence[ExistingSnapshot],
    current_time: datetime,
    channel_id: str | None = None,
    content_format: str | None = None,
    is_short: bool | None = None,
    is_live: bool | None = None,
    unavailable: bool = False,
    policy: SnapshotCollectionPolicy | None = None,
) -> VideoRevisitPlan:
    cfg = policy or SnapshotCollectionPolicy()
    item = VideoRevisitInput(
        video_id=video_id,
        published_at=published_at,
        channel_id=channel_id,
        content_format=content_format,
        is_short=is_short,
        is_live=is_live,
        unavailable=unavailable,
    )
    eligible, ineligible_reason = evaluate_monitoring_eligibility(item)
    notes: list[str] = []

    current_age: float | None = None
    if eligible and published_at is not None:
        current_age = compute_video_age_hours(published_at, current_time)
        if current_age is None:
            eligible = False
            ineligible_reason = "invalid_age_non_positive"

    checkpoint_plans: list[CheckpointPlan] = []
    if eligible and current_age is not None:
        for checkpoint in cfg.checkpoint_hours:
            lower, upper = checkpoint_match_window(checkpoint, cfg)
            matched = find_matching_snapshot(existing_snapshots, checkpoint, cfg)
            status, action, due_since = _checkpoint_status(
                checkpoint_hours=checkpoint,
                current_age_hours=current_age,
                matched=matched,
                policy=cfg,
            )
            checkpoint_plans.append(
                CheckpointPlan(
                    target_age_hours=checkpoint,
                    status=status,
                    matched_snapshot_id=matched.snapshot_id if matched else None,
                    matched_snapshot_age_hours=(
                        float(matched.age_hours) if matched and matched.age_hours is not None else None
                    ),
                    min_match_age_hours=round(lower, 4),
                    max_match_age_hours=round(upper, 4),
                    expires_at_age_hours=round(checkpoint_expires_at_age_hours(checkpoint, cfg), 4),
                    due_since_hours=due_since,
                    recommended_action=action,
                ),
            )
    elif not eligible:
        notes.append(f"monitoring ineligible: {ineligible_reason}")

    monitoring_status, stop_reason = _monitoring_stop_reason(
        checkpoint_plans,
        ineligible_reason=ineligible_reason if not eligible else None,
    )

    due_checkpoints = tuple(
        cp for cp in checkpoint_plans if cp.status in ("due", "overdue")
    )
    next_pending = next((cp.target_age_hours for cp in checkpoint_plans if cp.status == "pending"), None)

    return VideoRevisitPlan(
        video_id=video_id,
        channel_id=channel_id,
        current_age_hours=current_age,
        monitoring_status=monitoring_status,
        checkpoints=tuple(checkpoint_plans),
        due_checkpoints=due_checkpoints,
        next_checkpoint_hours=next_pending,
        stop_reason=stop_reason,
        notes=tuple(notes),
    )


def checkpoint_priority_key(plan: VideoRevisitPlan, checkpoint: CheckpointPlan) -> tuple:
    """Lower sort key = higher priority."""
    assert plan.current_age_hours is not None
    time_to_expiry = checkpoint.expires_at_age_hours - plan.current_age_hours
    status_rank = 0 if checkpoint.status == "overdue" else 1
    return (status_rank, time_to_expiry, checkpoint.target_age_hours)


def build_capture_requests(
    plan: VideoRevisitPlan,
    *,
    requested_at: datetime,
    source: str,
    run_id_prefix: str = "",
) -> list[SnapshotCaptureRequest]:
    """Create capture requests for due/overdue checkpoints (does not fetch YouTube)."""
    if plan.current_age_hours is None:
        return []

    ordered = sorted(
        [cp for cp in plan.due_checkpoints],
        key=lambda cp: checkpoint_priority_key(plan, cp),
    )
    requests: list[SnapshotCaptureRequest] = []
    for checkpoint in ordered:
        reason: CaptureReason = "overdue" if checkpoint.status == "overdue" else "due"
        run_id = f"{run_id_prefix}{plan.video_id}:cp{checkpoint.target_age_hours}"
        requests.append(
            SnapshotCaptureRequest(
                video_id=plan.video_id,
                channel_id=plan.channel_id,
                checkpoint_age_hours=checkpoint.target_age_hours,
                reason=reason,
                requested_at=ensure_utc(requested_at),
                current_age_hours=float(plan.current_age_hours),
                source=source,
                run_id=run_id,
            ),
        )
    return requests


def plan_revisits_for_videos(
    items: Sequence[VideoRevisitInput],
    *,
    snapshots_by_video_id: dict[str, list[ExistingSnapshot]],
    current_time: datetime,
    policy: SnapshotCollectionPolicy | None = None,
    due_and_overdue_only: bool = False,
) -> list[VideoRevisitPlan]:
    cfg = policy or SnapshotCollectionPolicy()
    plans: list[VideoRevisitPlan] = []
    for item in sorted(items, key=lambda row: row.video_id):
        plan = plan_video_revisits(
            video_id=item.video_id,
            published_at=item.published_at,
            existing_snapshots=snapshots_by_video_id.get(item.video_id, []),
            current_time=current_time,
            channel_id=item.channel_id,
            content_format=item.content_format,
            is_short=item.is_short,
            is_live=item.is_live,
            unavailable=item.unavailable,
            policy=cfg,
        )
        if due_and_overdue_only and not plan.due_checkpoints:
            continue
        plans.append(plan)
    return plans


def existing_snapshot_from_orm(row: VideoSnapshot) -> ExistingSnapshot:
    return ExistingSnapshot(
        snapshot_id=row.id,
        age_hours=row.age_hours,
        captured_at=row.captured_at,
    )


def load_snapshots_by_video_id(
    session: Session,
    video_ids: Sequence[str],
    *,
    max_age_hours: float | None = MONITORING_PLANNER_MAX_SNAPSHOT_AGE_HOURS,
) -> dict[str, list[ExistingSnapshot]]:
    from app.services.video_snapshot_storage import get_snapshots_for_videos_planner

    rows = (
        get_snapshots_for_videos_planner(session, video_ids, max_age_hours=max_age_hours)
        if max_age_hours is not None
        else get_snapshots_for_videos(session, video_ids)
    )
    grouped: dict[str, list[ExistingSnapshot]] = {}
    for row in rows:
        grouped.setdefault(row.video_id, []).append(existing_snapshot_from_orm(row))
    return grouped


def plan_to_dict(plan: VideoRevisitPlan) -> dict[str, Any]:
    return {
        "video_id": plan.video_id,
        "channel_id": plan.channel_id,
        "current_age_hours": plan.current_age_hours,
        "monitoring_status": plan.monitoring_status,
        "next_checkpoint_hours": plan.next_checkpoint_hours,
        "stop_reason": plan.stop_reason,
        "notes": list(plan.notes),
        "due_checkpoints": [cp.target_age_hours for cp in plan.due_checkpoints],
        "checkpoints": [
            {
                "target_age_hours": cp.target_age_hours,
                "status": cp.status,
                "matched_snapshot_id": cp.matched_snapshot_id,
                "matched_snapshot_age_hours": cp.matched_snapshot_age_hours,
                "min_match_age_hours": cp.min_match_age_hours,
                "max_match_age_hours": cp.max_match_age_hours,
                "expires_at_age_hours": cp.expires_at_age_hours,
                "due_since_hours": cp.due_since_hours,
                "recommended_action": cp.recommended_action,
            }
            for cp in plan.checkpoints
        ],
    }
