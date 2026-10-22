"""Defer repeat YouTube API capture after a prior missing (no-item) outcome."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import MonitoringCaptureOutcome
from app.services.metrics import ensure_utc
# Same default as monitoring_cycle / monitoring_worker_runtime (avoid import cycle).
_DEFAULT_MONITORING_WORKER_INTERVAL_SECONDS = 900
from app.services.monitoring_tier_budget_policy import (
    CaptureRequestBudgetContext,
    MonitoringTierPolicy,
    snapshot_collection_policy_for_tier,
)
from app.services.snapshot_collection_policy import (
    SnapshotCaptureRequest,
    SnapshotCollectionPolicy,
    checkpoint_expires_at_age_hours,
    checkpoint_match_tolerance_hours,
)

MissingAttemptKey = tuple[str, int]


def missing_capture_retry_interval_seconds(
    *,
    checkpoint_age_hours: int,
    current_age_hours: float,
    policy: SnapshotCollectionPolicy,
    worker_interval_seconds: int = _DEFAULT_MONITORING_WORKER_INTERVAL_SECONDS,
) -> float:
    """
    Minimum seconds before re-requesting the same (video_id, checkpoint) after missing.

    Derived from checkpoint policy:
    - baseline spacing = match tolerance (same age slot should not be hammered every worker tick)
    - at least two worker intervals (orchestrator cadence floor)
    - near checkpoint expiry, shorten toward worker interval so a last attempt remains possible
    """
    tolerance_h = checkpoint_match_tolerance_hours(checkpoint_age_hours, policy)
    expires_h = checkpoint_expires_at_age_hours(checkpoint_age_hours, policy)
    remaining_h = max(0.0, expires_h - float(current_age_hours))
    worker_h = max(worker_interval_seconds / 3600.0, 1.0 / 3600.0)
    base_h = max(tolerance_h, 2.0 * worker_h)
    if remaining_h <= worker_h:
        return 0.0
    if remaining_h < base_h:
        return 2.0 * worker_h * 3600.0
    return base_h * 3600.0


def load_latest_missing_attempt_at(
    session: Session,
    keys: set[MissingAttemptKey],
) -> dict[MissingAttemptKey, datetime]:
    if not keys:
        return {}
    video_ids = {video_id for video_id, _ in keys}
    rows = session.scalars(
        select(MonitoringCaptureOutcome)
        .where(
            MonitoringCaptureOutcome.outcome == "missing",
            MonitoringCaptureOutcome.video_id.in_(video_ids),
        )
        .order_by(
            MonitoringCaptureOutcome.video_id,
            MonitoringCaptureOutcome.checkpoint_age_hours,
            MonitoringCaptureOutcome.attempted_at.desc(),
        ),
    ).all()
    latest: dict[MissingAttemptKey, datetime] = {}
    for row in rows:
        key = (row.video_id, int(row.checkpoint_age_hours))
        if key not in keys or key in latest:
            continue
        latest[key] = ensure_utc(row.attempted_at)
    return latest


def filter_capture_requests_by_missing_cooldown(
    session: Session,
    *,
    requests: Sequence[SnapshotCaptureRequest],
    contexts: Sequence[CaptureRequestBudgetContext],
    now: datetime,
    tier_policy: MonitoringTierPolicy | None = None,
    worker_interval_seconds: int = _DEFAULT_MONITORING_WORKER_INTERVAL_SECONDS,
) -> tuple[list[SnapshotCaptureRequest], list[CaptureRequestBudgetContext], int]:
    """Drop requests still inside missing retry cooldown; returns (kept, kept_ctx, suppressed_count)."""
    req_list = list(requests)
    ctx_list = list(contexts)
    if len(req_list) != len(ctx_list):
        raise ValueError("requests and contexts length mismatch")
    if not req_list:
        return [], [], 0

    tier_cfg = tier_policy or MonitoringTierPolicy()
    keys = {(r.video_id, r.checkpoint_age_hours) for r in req_list}
    latest_missing = load_latest_missing_attempt_at(session, keys)
    reference = ensure_utc(now)

    kept_requests: list[SnapshotCaptureRequest] = []
    kept_contexts: list[CaptureRequestBudgetContext] = []
    suppressed = 0

    for request, context in zip(req_list, ctx_list, strict=True):
        key = (request.video_id, request.checkpoint_age_hours)
        last_at = latest_missing.get(key)
        if last_at is None:
            kept_requests.append(request)
            kept_contexts.append(context)
            continue
        collection_policy = snapshot_collection_policy_for_tier(context.tier, tier_cfg)
        interval_s = missing_capture_retry_interval_seconds(
            checkpoint_age_hours=request.checkpoint_age_hours,
            current_age_hours=request.current_age_hours,
            policy=collection_policy,
            worker_interval_seconds=worker_interval_seconds,
        )
        elapsed_s = (reference - last_at).total_seconds()
        if elapsed_s < interval_s:
            suppressed += 1
            continue
        kept_requests.append(request)
        kept_contexts.append(context)

    return kept_requests, kept_contexts, suppressed
