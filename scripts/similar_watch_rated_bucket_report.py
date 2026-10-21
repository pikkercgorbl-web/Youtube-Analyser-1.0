#!/usr/bin/env python3
"""Compare fit/not_fit vs primary/other for rated similar-watch findings (live rules)."""

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
    build_anchor_profile,
    parse_frozen_json,
    relevance_from_payload,
)


def _bucket_for_finding(session, saved: SavedVideo, finding: SavedVideoSimilarFinding) -> str:
    anchor = build_anchor_profile(
        title=saved.frozen_title,
        frozen_payload=parse_frozen_json(saved.frozen_payload_json),
    )
    try:
        payload = json.loads(finding.payload_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    rel = relevance_from_payload(payload, anchor, matched_query=finding.matched_query or "")
    return rel.tier


def report_for_watch(session, saved_video_id: int, label: str) -> dict:
    saved = session.get(SavedVideo, saved_video_id)
    if saved is None:
        return {"label": label, "error": "missing saved video"}
    feedback_rows = session.scalars(
        select(SavedVideoSimilarFindingFeedback).where(
            SavedVideoSimilarFindingFeedback.saved_video_id == saved_video_id,
        ),
    ).all()
    finding_ids = [int(r.finding_id) for r in feedback_rows]
    if not feedback_rows:
        return {
            "label": label,
            "saved_video_id": saved_video_id,
            "rated_count": 0,
            "fit_in_primary": 0,
            "fit_in_other": 0,
            "not_fit_in_primary": 0,
            "not_fit_in_other": 0,
            "fit_in_other_samples": [],
        }
    findings = {
        int(f.id): f
        for f in session.scalars(
            select(SavedVideoSimilarFinding).where(
                SavedVideoSimilarFinding.saved_video_id == saved_video_id,
                SavedVideoSimilarFinding.id.in_(finding_ids),
            ),
        ).all()
    }
    stats = {
        "label": label,
        "saved_video_id": saved_video_id,
        "rated_count": len(feedback_rows),
        "fit_in_primary": 0,
        "fit_in_other": 0,
        "not_fit_in_primary": 0,
        "not_fit_in_other": 0,
        "fit_in_other_samples": [],
    }
    for fb in feedback_rows:
        finding = findings.get(int(fb.finding_id))
        if finding is None:
            continue
        tier = _bucket_for_finding(session, saved, finding)
        try:
            payload = json.loads(finding.payload_json or "{}")
        except json.JSONDecodeError:
            payload = {}
        anchor = build_anchor_profile(
            title=saved.frozen_title,
            frozen_payload=parse_frozen_json(saved.frozen_payload_json),
        )
        rel = relevance_from_payload(payload, anchor, matched_query=finding.matched_query or "")
        if fb.verdict == "fit":
            if tier == "primary":
                stats["fit_in_primary"] += 1
            else:
                stats["fit_in_other"] += 1
                if len(stats["fit_in_other_samples"]) < 20:
                    stats["fit_in_other_samples"].append(
                        {
                            "title": payload.get("title"),
                            "matched_query": finding.matched_query,
                            "score": rel.score,
                            "other_reason": rel.other_reason,
                        },
                    )
        elif fb.verdict == "not_fit":
            if tier == "primary":
                stats["not_fit_in_primary"] += 1
            else:
                stats["not_fit_in_other"] += 1
    return stats


def main() -> None:
    targets = [
        (1, "grain"),
        (4, "tesla"),
    ]
    out = []
    with SessionLocal() as session:
        for sid, label in targets:
            out.append(report_for_watch(session, sid, label))
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
