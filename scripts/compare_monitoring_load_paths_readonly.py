#!/usr/bin/env python3
"""Read-only: compare monitoring load metrics at one timestamp (post-bootstrap code)."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import load_dotenv
from app.models.db import SessionLocal
from app.services.metrics import utc_now
from app.services.monitoring_cycle import (
    _state_to_tier_input,
    _plan_and_requests_for_decision,
    _tier_counts,
)
from app.services.monitoring_tier_budget_policy import (
    ApiBudgetPolicy,
    MonitoringTier,
    MonitoringTierPolicy,
    allocate_capture_budget,
    apply_channel_active_cap,
    apply_global_monitoring_cap,
    assign_monitoring_tiers,
    snapshot_collection_policy_for_tier,
)
from app.services.monitoring_video_source import load_monitored_video_states
from app.services.snapshot_collection_policy import load_snapshots_by_video_id
from app.services.snapshot_measurement import derive_latest_measurement
from app.services.video_snapshot_storage import get_latest_snapshots_for_videos
from app.models.orm import KeywordDiscoveryHit, Video
from sqlalchemy import select

OUT = ROOT / "artifacts" / "monitoring_load_path_compare.json"


def _metrics(session, now) -> dict:
    states = load_monitored_video_states(session, now=now)
    tier_cfg = MonitoringTierPolicy()
    budget_cfg = ApiBudgetPolicy()
    decisions = assign_monitoring_tiers([_state_to_tier_input(s) for s in states], tier_cfg)
    ch = apply_channel_active_cap(decisions, tier_cfg.max_active_videos_per_channel)
    gl = apply_global_monitoring_cap(ch.retained, budget_cfg.max_active_monitored_videos)
    active = list(gl.retained)
    state_by_id = {s.video_id: s for s in states}
    snaps = load_snapshots_by_video_id(session, [d.video_id for d in active])
    due = overdue = 0
    contexts = []
    for d in active:
        plan, reqs = _plan_and_requests_for_decision(
            d,
            state_by_id=state_by_id,
            snapshots_by_video_id=snaps,
            current_time=now,
            tier_policy=tier_cfg,
            run_id="compare",
        )
        for cp in plan.due_checkpoints:
            if cp.status == "due":
                due += 1
            elif cp.status == "overdue":
                overdue += 1
        for r in reqs:
            from app.services.monitoring_cycle import _budget_context

            contexts.append(_budget_context(r, decision=d, plan=plan))
    budget = allocate_capture_budget(contexts, budget_cfg)
    missing = sum(1 for s in states if s.raw_vph is None)
    src = Counter()
    for s in states:
        v = session.get(Video, s.video_id)
        if not v:
            continue
        latest = get_latest_snapshots_for_videos(session, [s.video_id], compute_before=now).get(s.video_id)
        hits = list(session.scalars(select(KeywordDiscoveryHit).where(KeywordDiscoveryHit.video_id == s.video_id)))
        m = derive_latest_measurement(video=v, latest_snapshot=latest, discovery_hits=hits, compute_before=now)
        if s.raw_vph is not None:
            src[m.source] += 1
    return {
        "at_utc": now.isoformat(),
        "loaded": len(states),
        "active": len(active),
        "missing_vph": missing,
        "due": due,
        "overdue": overdue,
        "selected": budget.selected_for_capture_count,
        "measurement_source_among_with_vph": dict(src),
        "tier_counts": _tier_counts(active),
    }


def _examples(session, now, limit=3) -> dict:
    examples = {"keyword_discovery": [], "format_enrichment_snapshot": []}
    states = load_monitored_video_states(session, now=now)
    for s in states:
        if len(examples["keyword_discovery"]) >= limit and len(examples["format_enrichment_snapshot"]) >= limit:
            break
        v = session.get(Video, s.video_id)
        if not v:
            continue
        latest = get_latest_snapshots_for_videos(session, [s.video_id], compute_before=now).get(s.video_id)
        hits = list(session.scalars(select(KeywordDiscoveryHit).where(KeywordDiscoveryHit.video_id == s.video_id)))
        m = derive_latest_measurement(video=v, latest_snapshot=latest, discovery_hits=hits, compute_before=now)
        if m.source == "discovery" and len(examples["keyword_discovery"]) < limit:
            examples["keyword_discovery"].append(
                {"video_id": s.video_id, "vph": s.raw_vph, "measured_at": m.measured_at.isoformat() if m.measured_at else None},
            )
        if latest and latest.source == "format_enrichment" and len(examples["format_enrichment_snapshot"]) < limit:
            examples["format_enrichment_snapshot"].append(
                {"video_id": s.video_id, "vph": s.raw_vph, "captured_at": latest.captured_at.isoformat()},
            )
    return examples


def main() -> int:
    load_dotenv(ROOT / ".env")
    session = SessionLocal()
    try:
        now = utc_now()
        report = {
            "generated_at_utc": now.isoformat(),
            "note": "Single load-path (current code). Historical pre-fix counts were missing_vph~2277 in full pool.",
            "current": _metrics(session, now),
            "examples": _examples(session, now),
        }
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"artifact": str(OUT.relative_to(ROOT)), "active": report["current"]["active"]}, indent=2))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
