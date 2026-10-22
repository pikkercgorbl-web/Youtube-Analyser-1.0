"""Fix 2A.1 — exact tier counts + views + winner independence (PG read-only)."""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.orm import KeywordDiscoveryHit, Video

EXPECTED = "youtube_radar_restore_check"
VIEWS_EXCLUSION_THRESHOLD = 0.35
Tier = Literal["supported_opportunity", "needs_review", "search_collection"]


def _url() -> str:
    u = os.environ.get("DATABASE_URL", "").strip()
    if not u:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL="):
                u = line.split("=", 1)[1].strip().strip('"').strip("'")
    if EXPECTED not in (u or ""):
        raise SystemExit("Refusing: not restore_check DB")
    return u


@dataclass(frozen=True, slots=True)
class TierResult:
    tier: Tier
    rule_id: str
    reasons: tuple[str, ...]


def classify_family(row: dict[str, Any]) -> TierResult:
    flags = set(row.get("quality_flags") or [])
    kind = str(row.get("family_kind") or "")
    w = int(row.get("winner_in_feed_count") or 0)
    zero_null_share = float(row.get("zero_or_null_views_share") or 0.0)
    keyword_only = "keyword_only" in flags
    broad = "broad_keyword_group" in flags
    cross = "cross_source_supported" in flags
    phrase = "phrase_supported" in flags
    template = "repeated_title_template" in flags
    views_block = zero_null_share >= VIEWS_EXCLUSION_THRESHOLD

    if w == 0:
        return TierResult("search_collection", "R1", ("no_top50_feed_winners",))
    if cross and w >= 2 and not (keyword_only and broad) and not views_block:
        return TierResult(
            "supported_opportunity",
            "R2",
            ("cross_source_supported", "feed_winners_gte_2", "not_broad_keyword_only", "views_below_exclusion"),
        )
    if (phrase or template) and not broad and w >= 1 and not views_block:
        return TierResult(
            "supported_opportunity",
            "R3",
            ("phrase_or_template_support", "not_broad_keyword_group", "feed_winners_gte_1", "views_below_exclusion"),
        )
    if keyword_only and broad:
        return TierResult("needs_review", "R4", ("keyword_only", "broad_keyword_group", "feed_winners_gte_1"))
    if cross and w == 1:
        return TierResult("needs_review", "R5", ("cross_source_supported", "feed_winners_eq_1"))
    if keyword_only and not broad and w >= 2:
        return TierResult("needs_review", "R6", ("keyword_only", "not_broad", "feed_winners_gte_2"))
    if kind == "video_topic" and not cross and w >= 1:
        return TierResult("needs_review", "R7", ("video_topic_kind", "no_cross_source", "feed_winners_gte_1"))
    if w >= 1:
        return TierResult("needs_review", "R8", ("residual_with_feed_winners",))
    return TierResult("search_collection", "R9", ("residual_no_feed_winners",))


def _winner_provenance(session: Session, winner_ids: list[str]) -> dict[str, Any]:
    if not winner_ids:
        return {
            "distinct_winner_channels": 0,
            "shared_single_keyword_all_winners": False,
            "keyword_id_sets": {},
            "overlapping_provenance": False,
        }
    channels: set[str] = set()
    kw_sets: dict[str, set[int]] = {}
    for vid in winner_ids:
        v = session.get(Video, vid)
        if v and v.channel_id:
            channels.add(v.channel_id)
        hits = session.scalars(select(KeywordDiscoveryHit).where(KeywordDiscoveryHit.video_id == vid)).all()
        kw_sets[vid] = {h.keyword_id for h in hits}
    all_kw = [s for s in kw_sets.values() if s]
    shared_one = False
    if all_kw:
        inter = set.intersection(*all_kw) if len(all_kw) > 1 else all_kw[0]
        if len(inter) == 1 and all(inter <= s for s in all_kw):
            shared_one = True
    union = set.union(*all_kw) if all_kw else set()
    overlapping = len(union) < sum(len(s) for s in all_kw)
    return {
        "distinct_winner_channels": len(channels),
        "shared_single_keyword_all_winners": shared_one,
        "keyword_id_sets": {k: sorted(v) for k, v in kw_sets.items()},
        "overlapping_provenance": overlapping,
    }


def _views_breakdown(
    vids: list[str],
    latest_views: dict[str, int | None],
    has_any_snapshot: dict[str, bool],
    has_monitoring_history: dict[str, bool],
) -> dict[str, Any]:
    zero = null = missing_snap = no_hist = 0
    for vid in vids:
        if not has_any_snapshot.get(vid):
            missing_snap += 1
            if not has_monitoring_history.get(vid):
                no_hist += 1
            continue
        v = latest_views.get(vid)
        if v is None:
            null += 1
        elif v == 0:
            zero += 1
        if not has_monitoring_history.get(vid):
            no_hist += 1
    n = len(vids) or 1
    return {
        "views_eq_0": zero,
        "views_null_with_snapshot": null,
        "missing_latest_snapshot": missing_snap,
        "no_monitoring_history": no_hist,
        "member_count": len(vids),
        "zero_null_missing_share": round((zero + null + missing_snap) / n, 4),
    }


CLASSIFICATION_SPEC = {
    "tiers": ["supported_opportunity", "needs_review", "search_collection"],
    "mutually_exclusive": True,
    "precedence": [
        "R1: winner_in_feed_count==0 → search_collection",
        "R2: cross_source AND feed_winners>=2 AND NOT(keyword_only AND broad) AND views_share<0.35 → supported_opportunity",
        "R3: (phrase_supported OR repeated_title_template) AND NOT broad AND feed_winners>=1 AND views_share<0.35 → supported_opportunity",
        "R4: keyword_only AND broad_keyword_group AND feed_winners>=1 → needs_review",
        "R5: cross_source AND feed_winners==1 → needs_review",
        "R6: keyword_only AND NOT broad AND feed_winners>=2 → needs_review",
        "R7: family_kind==video_topic AND NOT cross_source AND feed_winners>=1 → needs_review",
        "R8: feed_winners>=1 → needs_review",
        "R9: fallback → search_collection",
    ],
    "missing_defaults": {"quality_flags": [], "winner_in_feed_count": 0, "zero_or_null_views_share": 0.0},
    "views_share_definition": "(views_0 + views_null + missing_latest_snapshot) / member_count",
}


def main() -> None:
    engine = create_engine(_url(), connect_args={"options": "-c default_transaction_read_only=on"})
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        run_row = session.execute(
            text(
                "SELECT run_id, pattern_limit FROM attention_runs ORDER BY computed_at DESC LIMIT 1",
            ),
        ).one()
        run_id = run_row.run_id
        pattern_limit = int(run_row.pattern_limit)
        families_db = session.execute(
            text(
                """
                SELECT rank, family_key, payload_json
                FROM attention_pattern_families WHERE run_id = :r ORDER BY rank
                """,
            ),
            {"r": run_id},
        ).fetchall()
        winner_ids = {
            r[0]
            for r in session.execute(
                text("SELECT video_id FROM attention_video_winners WHERE run_id = :r"),
                {"r": run_id},
            ).fetchall()
        }
        family_videos: dict[str, list[str]] = defaultdict(list)
        for fk, vid in session.execute(
            text("SELECT family_key, video_id FROM attention_pattern_family_videos WHERE run_id = :r"),
            {"r": run_id},
        ).fetchall():
            family_videos[fk].append(vid)

        latest_views: dict[str, int | None] = {}
        has_snapshot: dict[str, bool] = {}
        for vid, views in session.execute(
            text(
                "SELECT DISTINCT ON (video_id) video_id, views FROM video_snapshots ORDER BY video_id, captured_at DESC",
            ),
        ).fetchall():
            latest_views[vid] = int(views) if views is not None else None
            has_snapshot[vid] = True

        snap_count = {
            r[0]: int(r[1])
            for r in session.execute(text("SELECT video_id, COUNT(*)::int FROM video_snapshots GROUP BY video_id")).fetchall()
        }

        tier_counts: dict[str, int] = defaultdict(int)
        rows_out = []
        for rank, fk, payload_json in families_db:
            payload = json.loads(payload_json or "{}")
            vids = family_videos.get(fk) or list(payload.get("video_ids") or [])
            feed_winners = [v for v in vids if v in winner_ids]
            views_bd = _views_breakdown(
                vids,
                latest_views,
                has_snapshot,
                {v: snap_count.get(v, 0) > 0 for v in vids},
            )
            prov = _winner_provenance(session, feed_winners)
            row = {
                "rank": rank,
                "family_key": fk,
                "label": payload.get("label"),
                "family_kind": payload.get("family_kind"),
                "quality_flags": list(payload.get("quality_flags") or []),
                "support_sources": list(payload.get("support_sources") or []),
                "member_video_count": len(vids),
                "winner_in_feed_count": len(feed_winners),
                "winner_video_ids": feed_winners,
                "zero_or_null_views_share": views_bd["zero_null_missing_share"],
                "views_breakdown": views_bd,
                "winner_independence": prov,
            }
            tr = classify_family(row)
            row["tier"] = tr.tier
            row["tier_rule_id"] = tr.rule_id
            row["tier_reasons"] = list(tr.reasons)
            tier_counts[tr.tier] += 1
            rows_out.append(row)

        shares = [r["zero_or_null_views_share"] for r in rows_out]
        out = {
            "run_id": run_id,
            "classification_spec": CLASSIFICATION_SPEC,
            "tier_counts_exact": dict(tier_counts),
            "views_threshold_analysis": {
                "threshold": VIEWS_EXCLUSION_THRESHOLD,
                "families_at_or_above_threshold": sum(1 for s in shares if s >= VIEWS_EXCLUSION_THRESHOLD),
                "families_below_threshold": sum(1 for s in shares if s < VIEWS_EXCLUSION_THRESHOLD),
                "max_zero_null_missing_share": max(shares) if shares else 0,
                "supported_blocked_by_views_alone": 0,
            },
            "aggregate_views_all_member_videos": _aggregate_views(rows_out),
            "pattern_cap_investigation": {
                "persisted_patterns_in_db": session.execute(
                    text("SELECT COUNT(*) FROM attention_patterns WHERE run_id = :r"),
                    {"r": run_id},
                ).scalar(),
                "pattern_limit_from_run": pattern_limit,
                "uncapped_simulation_status": "not_completed",
                "reason": (
                    "load_attention_evidence() + build_pattern_candidates() read-only recompute did not finish within "
                    "10 minutes on youtube_radar_restore_check in audit environment; cannot safely assert uncapped counts."
                ),
                "code_path_confirmed": {
                    "generation_order": "keyword_provenance patterns, then title_phrase, then video_topic",
                    "truncation": "patterns.sort(...); return patterns[:config.pattern_limit] in build_pattern_candidates",
                    "sort_key": "channel_count desc, breakout_video_count desc, videos_last_24h desc, video_count desc, pattern_key",
                    "title_phrase_before_truncation": True,
                    "title_phrase_in_persisted_top20": sum(
                        1
                        for _, _, pj in families_db
                        if json.loads(pj or "{}").get("family_kind") == "title_phrase"
                    ),
                },
            },
            "families": rows_out,
        }
        for r in rows_out:
            if r["zero_or_null_views_share"] >= VIEWS_EXCLUSION_THRESHOLD:
                hypo = classify_family({**r, "zero_or_null_views_share": 0.0})
                if hypo.tier == "supported_opportunity" and r["tier"] != "supported_opportunity":
                    out["views_threshold_analysis"]["supported_blocked_by_views_alone"] += 1

        path = ROOT / "artifacts" / "audit_opportunity_quality_gate_2a1_report.json"
        path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"tier_counts_exact": dict(tier_counts), "written": str(path)}, ensure_ascii=False))


def _aggregate_views(rows: list[dict]) -> dict[str, int]:
    t = defaultdict(int)
    for r in rows:
        bd = r["views_breakdown"]
        for k in ("views_eq_0", "views_null_with_snapshot", "missing_latest_snapshot", "no_monitoring_history"):
            t[k] += bd[k]
        t["member_videos_total"] += bd["member_count"]
    return dict(t)


if __name__ == "__main__":
    main()
