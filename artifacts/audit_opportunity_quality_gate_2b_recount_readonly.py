"""Product Fix 2B — read-only recount of presentation tiers on latest attention snapshot."""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.services.attention_read_model import load_attention_snapshot
from app.services.opportunity_family_presentation import (
    load_video_title_channel_maps,
    present_opportunity_family,
)


def _url() -> str:
    u = os.environ.get("DATABASE_URL", "").strip()
    if not u:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL="):
                u = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not u:
        raise SystemExit("DATABASE_URL required")
    return u


def main() -> None:
    engine = create_engine(_url())
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        result = load_attention_snapshot(session)
        if result is None:
            raise SystemExit("No attention snapshot")
        winner_set = frozenset(row.video_id for row in result.video_winners)
        video_ids = {vid for family in result.families for vid in family.video_ids}
        titles, channels = load_video_title_channel_maps(
            session,
            video_ids,
            winner_rows=result.video_winners,
        )
        rows = []
        tier_counts: Counter[str] = Counter()
        for family in result.families:
            pres = present_opportunity_family(
                family,
                feed_winner_id_set=winner_set,
                video_titles=titles,
                video_channels=channels,
            )
            tier_counts[pres.opportunity_presentation_tier] += 1
            rows.append(
                {
                    "family_key": family.family_key,
                    "label": family.label,
                    "family_kind": family.family_kind,
                    "quality_flags": list(family.quality_flags),
                    "tier": pres.opportunity_presentation_tier,
                    "grouping_basis_label": pres.grouping_basis_label,
                    "tier_reason": pres.tier_reason,
                    "feed_winner_video_ids": list(pres.feed_winner_video_ids),
                    "title_evidence_video_ids": list(pres.title_evidence_video_ids),
                },
            )
        out = {
            "run_id": result.summary.run_id,
            "computed_at": result.summary.computed_at.isoformat(),
            "tier_counts": dict(tier_counts),
            "families": rows,
        }
        path = ROOT / "artifacts" / "audit_opportunity_quality_gate_2b_report.json"
        path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"tier_counts": out["tier_counts"], "run_id": out["run_id"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
