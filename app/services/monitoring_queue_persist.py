"""Persist monitoring queue snapshot from enriched active pool (Stage 1.20E.3)."""

from __future__ import annotations

import json

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models.orm import MonitoringVideoQueueEntry
from app.services.monitoring_api_service import MonitoringEnrichedVideo, _priority_sort_key


def _checkpoint_flags(row: MonitoringEnrichedVideo) -> tuple[bool, bool, bool]:
    has_due = any(cp.status == "due" for cp in row.plan.due_checkpoints)
    has_overdue = any(cp.status == "overdue" for cp in row.plan.due_checkpoints)
    has_pending = any(cp.status == "pending" for cp in row.plan.checkpoints)
    return has_due, has_overdue, has_pending


def entries_from_enriched(
    run_id: str,
    enriched: list[MonitoringEnrichedVideo],
) -> list[MonitoringVideoQueueEntry]:
    ordered = sorted(enriched, key=_priority_sort_key)
    entries: list[MonitoringVideoQueueEntry] = []
    for rank, row in enumerate(ordered):
        has_due, has_overdue, has_pending = _checkpoint_flags(row)
        due_hours = [cp.target_age_hours for cp in row.plan.due_checkpoints if cp.status == "due"]
        overdue_hours = [
            cp.target_age_hours for cp in row.plan.due_checkpoints if cp.status == "overdue"
        ]
        latest_at = row.latest_snapshot.captured_at if row.latest_snapshot else None
        entries.append(
            MonitoringVideoQueueEntry(
                run_id=run_id,
                video_id=row.state.video_id,
                channel_id=row.state.channel_id,
                tier=row.decision.tier.value,
                monitoring_status=row.plan.monitoring_status,
                has_due_checkpoint=has_due,
                has_overdue_checkpoint=has_overdue,
                has_pending_checkpoint=has_pending,
                priority_rank=rank,
                current_vph=row.current_vph,
                current_views=row.current_views,
                age_hours=row.state.age_hours,
                published_at=row.state.published_at,
                latest_snapshot_at=latest_at,
                next_checkpoint_hours=row.plan.next_checkpoint_hours,
                due_checkpoint_hours_json=json.dumps(due_hours),
                overdue_checkpoint_hours_json=json.dumps(overdue_hours),
                channel_velocity_baseline_status=row.state.channel_velocity_baseline_status,
                vph_vs_channel_median=row.state.vph_vs_channel_median,
                content_format=row.state.content_format,
            ),
        )
    return entries


def replace_monitoring_video_queue(
    session: Session,
    run_id: str,
    enriched: list[MonitoringEnrichedVideo],
) -> int:
    """Replace queue snapshot for run_id; prune rows from other runs."""
    entries = entries_from_enriched(run_id, enriched)
    session.execute(delete(MonitoringVideoQueueEntry).where(MonitoringVideoQueueEntry.run_id != run_id))
    session.execute(delete(MonitoringVideoQueueEntry).where(MonitoringVideoQueueEntry.run_id == run_id))
    if entries:
        session.add_all(entries)
    session.flush()
    return len(entries)
