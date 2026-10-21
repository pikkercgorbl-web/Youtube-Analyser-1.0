#!/usr/bin/env python3
"""Before/after bucket counts: stale payload tier vs live assess_similarity (rated findings only)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.models.db import SessionLocal
from app.models.orm import SavedVideo, SavedVideoSimilarFinding, SavedVideoSimilarFindingFeedback
from app.services.saved_video_similar_relevance import (
    RelevanceAssessment,
    assess_similarity,
    build_anchor_profile,
    parse_frozen_json,
)


def _tier_from_cached_payload(payload: dict) -> str:
    tier_raw = str(payload.get("relevance_tier") or "other")
    return "primary" if tier_raw == "primary" else "other"


def _live_tier(saved: SavedVideo, finding: SavedVideoSimilarFinding) -> RelevanceAssessment:
    anchor = build_anchor_profile(
        title=saved.frozen_title,
        frozen_payload=parse_frozen_json(saved.frozen_payload_json),
    )
    try:
        payload = json.loads(finding.payload_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    return assess_similarity(
        anchor,
        candidate_title=str(payload.get("title") or ""),
        matched_query=finding.matched_query or "",
    )


def compare_watch(session, saved_video_id: int, label: str) -> dict:
    saved = session.get(SavedVideo, saved_video_id)
    if saved is None:
        return {"label": label, "error": "missing"}
    feedback_rows = session.scalars(
        select(SavedVideoSimilarFindingFeedback).where(
            SavedVideoSimilarFindingFeedback.saved_video_id == saved_video_id,
        ),
    ).all()
    if not feedback_rows:
        return {"label": label, "saved_video_id": saved_video_id, "rated_count": 0}
    ids = [int(r.finding_id) for r in feedback_rows]
    findings = {
        int(f.id): f
        for f in session.scalars(
            select(SavedVideoSimilarFinding).where(
                SavedVideoSimilarFinding.id.in_(ids),
            ),
        ).all()
    }

    def tally(verdict: str, tier_fn) -> dict[str, int]:
        out = {"primary": 0, "other": 0}
        for fb in feedback_rows:
            if fb.verdict != verdict:
                continue
            f = findings.get(int(fb.finding_id))
            if f is None:
                continue
            try:
                payload = json.loads(f.payload_json or "{}")
            except json.JSONDecodeError:
                payload = {}
            if tier_fn == "cached":
                tier = _tier_from_cached_payload(payload)
            else:
                tier = _live_tier(saved, f).tier
            out[tier] += 1
        return out

    fit_other_before = []
    for fb in feedback_rows:
        if fb.verdict != "fit":
            continue
        f = findings.get(int(fb.finding_id))
        if f is None:
            continue
        try:
            payload = json.loads(f.payload_json or "{}")
        except json.JSONDecodeError:
            payload = {}
        if _tier_from_cached_payload(payload) != "other":
            continue
        live = _live_tier(saved, f)
        if live.tier == "other":
            fit_other_before.append(
                {
                    "title": payload.get("title"),
                    "matched_query": f.matched_query,
                    "score": live.score,
                    "other_reason": live.other_reason,
                    "cached_tier": payload.get("relevance_tier"),
                    "cached_score": payload.get("relevance_score"),
                },
            )

    return {
        "label": label,
        "saved_video_id": saved_video_id,
        "rated_count": len(feedback_rows),
        "before_cached": {
            "fit": tally("fit", "cached"),
            "not_fit": tally("not_fit", "cached"),
        },
        "after_live": {
            "fit": tally("fit", "live"),
            "not_fit": tally("not_fit", "live"),
        },
        "fit_marked_other_still_other_after_live": fit_other_before,
    }


def main() -> None:
    with SessionLocal() as session:
        rows = [compare_watch(session, sid, label) for sid, label in ((1, "grain"), (4, "tesla"))]
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
