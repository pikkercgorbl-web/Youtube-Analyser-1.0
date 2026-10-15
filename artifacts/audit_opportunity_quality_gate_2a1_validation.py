"""Product Fix 2A.1 — deterministic quality gate validation (PG read-only)."""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.orm import KeywordDiscoveryHit, TargetKeyword, Video
from app.services.attention_engine_types import AttentionEngineConfig
from app.services.attention_engine_service import attention_window
from app.services.attention_patterns import build_pattern_candidates
from app.services.attention_evidence import load_attention_evidence
from app.services.attention_video_winners import build_video_winners
from app.services.metrics import ensure_utc

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
    """
    Mutually exclusive, exhaustive tier rules (fixed precedence).

    Missing fields:
    - quality_flags / support_sources missing → treated as empty tuple
    - winner_in_feed_count missing → 0
    - zero_or_null_views_share missing → 0.0 (does not block supported alone)
    """
    flags = set(row.get("quality_flags") or [])
    support = set(row.get("support_sources") or [])
    kind = str(row.get("family_kind") or "")
    w = int(row.get("winner_in_feed_count") or 0)
    zero_null_share = float(row.get("zero_or_null_views_share") or 0.0)
    keyword_only = "keyword_only" in flags
    broad = "broad_keyword_group" in flags
    cross = "cross_source_supported" in flags
    phrase = "phrase_supported" in flags
    template = "repeated_title_template" in flags
    views_block = zero_null_share >= VIEWS_EXCLUSION_THRESHOLD

    # R1
    if w == 0:
        return TierResult("search_collection", "R1", ("no_top50_feed_winners",))

    # R2 — supported: multi-source + multiple feed winners, not broad keyword-only bucket
    if cross and w >= 2 and not (keyword_only and broad) and not views_block:
        return TierResult(
            "supported_opportunity",
            "R2",
            ("cross_source_supported", "feed_winners_gte_2", "not_broad_keyword_only", "views_below_exclusion"),
        )

    # R3 — supported: title format signals
    if (phrase or template) and not broad and w >= 1 and not views_block:
        return TierResult(
            "supported_opportunity",
            "R3",
            ("phrase_or_template_support", "not_broad_keyword_group", "feed_winners_gte_1", "views_below_exclusion"),
        )

    # R4 — needs_review: broad keyword discovery but feed winners exist
    if keyword_only and broad:
        return TierResult("needs_review", "R4", ("keyword_only", "broad_keyword_group", "feed_winners_gte_1"))

    # R5 — needs_review: cross-source but single feed winner
    if cross and w == 1:
        return TierResult("needs_review", "R5", ("cross_source_supported", "feed_winners_eq_1"))

    # R6 — needs_review: narrow keyword-only with multiple feed winners
    if keyword_only and not broad and w >= 2:
        return TierResult("needs_review", "R6", ("keyword_only", "not_broad", "feed_winners_gte_2"))

    # R7 — needs_review: video_topic without cross-source
    if kind == "video_topic" and not cross and w >= 1:
        return TierResult("needs_review", "R7", ("video_topic_kind", "no_cross_source", "feed_winners_gte_1"))

    # R8 — needs_review: residual with any feed winner
    if w >= 1:
        return TierResult("needs_review", "R8", ("residual_with_feed_winners",))

    # R9 — exhaustive fallback
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
    overlapping = len(union) < sum(len(s) for s in all_kw)  # shared keyword ids across winners
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
        if vid not in latest_views and not has_any_snapshot.get(vid):
            missing_snap += 1
            continue
        if not has_any_snapshot.get(vid):
            missing_snap += 1
            continue
        v = latest_views.get(vid)
        if v is None:
            null += 1
        elif v == 0:
            zero += 1
        if not has_monitoring_history.get(vid):
            no_hist += 1
    n = len(vids) or 1
    zero_null_share = (zero + null + missing_snap) / n
    return {
        "views_eq_0": zero,
        "views_null_with_snapshot": null,
        "missing_latest_snapshot": missing_snap,
        "no_monitoring_history": no_hist,
        "member_count": len(vids),
        "zero_null_missing_share": round(zero_null_share, 4),
    }


def main() -> None:
    engine = create_engine(_url(), connect_args={"options": "-c default_transaction_read_only=on"})
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        run_row = session.execute(
            text(
                """
                SELECT run_id, computed_at, window_hours, pattern_limit, video_limit
                FROM attention_runs ORDER BY computed_at DESC LIMIT 1
                """,
            ),
        ).one()
        run_id = run_row.run_id
        pattern_limit = int(run_row.pattern_limit)

        families = session.execute(
            text(
                """
                SELECT rank, family_key, payload_json
                FROM attention_pattern_families WHERE run_id = :r ORDER BY rank
                """,
            ),
            {"r": run_id},
        ).fetchall()

        winner_payload = {
            r[0]: json.loads(r[1] or "{}")
            for r in session.execute(
                text("SELECT video_id, payload_json FROM attention_video_winners WHERE run_id = :r"),
                {"r": run_id},
            ).fetchall()
        }
        winner_ids = set(winner_payload)

        family_videos: dict[str, list[str]] = defaultdict(list)
        for fk, vid in session.execute(
            text("SELECT family_key, video_id FROM attention_pattern_family_videos WHERE run_id = :r"),
            {"r": run_id},
        ).fetchall():
            family_videos[fk].append(vid)

        latest_views: dict[str, int | None] = {}
        has_snapshot: dict[str, bool] = defaultdict(bool)
        for vid, views in session.execute(
            text(
                """
                SELECT DISTINCT ON (video_id) video_id, views
                FROM video_snapshots ORDER BY video_id, captured_at DESC
                """,
            ),
        ).fetchall():
            latest_views[vid] = int(views) if views is not None else None
            has_snapshot[vid] = True

        snap_count = {
            r[0]: int(r[1])
            for r in session.execute(
                text("SELECT video_id, COUNT(*)::int FROM video_snapshots GROUP BY video_id"),
            ).fetchall()
        }

        tier_rows: list[dict[str, Any]] = []
        tier_counts: dict[str, int] = defaultdict(int)

        for rank, family_key, payload_json in families:
            payload = json.loads(payload_json or "{}")
            vids = family_videos.get(family_key) or list(payload.get("video_ids") or [])
            feed_winners = [v for v in vids if v in winner_ids]
            views_bd = _views_breakdown(vids, latest_views, has_snapshot, {v: snap_count.get(v, 0) > 0 for v in vids})
            prov = _winner_provenance(session, feed_winners)

            row = {
                "rank": rank,
                "family_key": family_key,
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
            tier = classify_family(row)
            row["tier"] = tier.tier
            row["tier_rule_id"] = tier.rule_id
            row["tier_reasons"] = list(tier.reasons)
            tier_counts[tier.tier] += 1
            tier_rows.append(row)

        # Pattern cap simulation (read-only recompute from evidence; no persist)
        computed_at = ensure_utc(run_row.computed_at)
        cfg20 = AttentionEngineConfig(pattern_limit=pattern_limit, video_limit=int(run_row.video_limit))
        window_start, window_end = attention_window(now=computed_at, window_hours=int(run_row.window_hours))
        lookback_start = window_end - timedelta(days=cfg20.channel_recent_days + cfg20.channel_previous_days)
        bundle = load_attention_evidence(
            session,
            window_start=window_start,
            window_end=window_end,
            channel_lookback_start=lookback_start,
        )
        winners = build_video_winners(bundle, cfg20, now=computed_at, publishable_confirmed_ids=None)
        all_patterns = build_pattern_candidates(bundle, cfg20, winners=winners, now=computed_at, publishable_confirmed_ids=None)
        # build_pattern_candidates truncates internally — need uncapped
        cfg_uncapped = AttentionEngineConfig(pattern_limit=10_000, video_limit=int(run_row.video_limit))
        patterns_uncapped = build_pattern_candidates(
            bundle,
            cfg_uncapped,
            winners=winners,
            now=computed_at,
            publishable_confirmed_ids=None,
        )

        def kind_counts(patterns) -> dict[str, int]:
            c: dict[str, int] = defaultdict(int)
            for p in patterns:
                c[p.kind] += 1
            return dict(c)

        def flag_counts_uncapped() -> dict[str, int]:
            from app.services.attention_pattern_families import build_pattern_families, load_family_identity

            titles = {vid: rec.video.title for vid, rec in bundle.records.items()}
            first_seen = {}
            for vid, rec in bundle.records.items():
                times = []
                if rec.video.published_at:
                    times.append(ensure_utc(rec.video.published_at))
                for hit in rec.hits:
                    times.append(ensure_utc(hit.discovered_at))
                if times:
                    first_seen[vid] = min(times)
            fams, _ = build_pattern_families(
                patterns_uncapped,
                now=computed_at,
                identity=load_family_identity(session),
                first_seen=first_seen,
                titles=titles,
            )
            fc: dict[str, int] = defaultdict(int)
            for f in fams:
                for fl in f.quality_flags:
                    fc[fl] += 1
            return {"family_count": len(fams), "flag_counts": dict(fc), "kind_counts": kind_counts(patterns_uncapped)}

        top20_keys = {p.pattern_key for p in all_patterns}
        uncapped_keys = {p.pattern_key for p in patterns_uncapped}
        dropped = [p for p in patterns_uncapped if p.pattern_key not in top20_keys]

        def summarize_pattern_list(patterns, limit: int):
            sliced = patterns[:limit]
            return {
                "count": len(sliced),
                "by_kind": kind_counts(sliced),
                "with_repeated_title_template": sum(
                    1
                    for p in sliced
                    if p.kind == "title_phrase" and p.breakout_video_count >= 2
                ),
            }

        cap_report = {
            "persisted_pattern_limit": pattern_limit,
            "patterns_generated_uncapped": len(patterns_uncapped),
            "patterns_after_limit_20": len(all_patterns),
            "uncapped_by_kind": kind_counts(patterns_uncapped),
            "top20_by_kind": kind_counts(all_patterns),
            "dropped_count": len(dropped),
            "dropped_by_kind": kind_counts(dropped),
            "title_phrase_in_uncapped": kind_counts(patterns_uncapped).get("title_phrase", 0),
            "title_phrase_in_top20": kind_counts(all_patterns).get("title_phrase", 0),
            "dropped_with_feed_winners": [],
            "uncapped_families_summary": flag_counts_uncapped(),
        }
        winner_set = {w.video_id for w in winners}
        for p in dropped[:50]:
            ids = set(p.participating_video_ids)
            w_in = len(ids & winner_set)
            cap_report["dropped_with_feed_winners"].append(
                {
                    "pattern_key": p.pattern_key,
                    "kind": p.kind,
                    "label": p.label,
                    "video_count": p.video_count,
                    "channel_count": p.channel_count,
                    "feed_winner_intersection": w_in,
                },
            )
        cap_report["dropped_with_feed_winners"].sort(key=lambda x: -x["feed_winner_intersection"])

        # Views threshold analysis across families
        shares = [r["zero_or_null_views_share"] for r in tier_rows]
        threshold_stats = {
            "threshold": VIEWS_EXCLUSION_THRESHOLD,
            "families_at_or_above": sum(1 for s in shares if s >= VIEWS_EXCLUSION_THRESHOLD),
            "families_below": sum(1 for s in shares if s < VIEWS_EXCLUSION_THRESHOLD),
            "max_share": max(shares) if shares else 0,
            "would_block_supported_only": sum(
                1
                for r in tier_rows
                if r["zero_or_null_views_share"] >= VIEWS_EXCLUSION_THRESHOLD and r["tier"] == "supported_opportunity"
            ),
        }

        spec = {
            "tiers": ["supported_opportunity", "needs_review", "search_collection"],
            "precedence": [
                "R1: winner_in_feed_count==0 → search_collection",
                "R2: cross_source AND winners>=2 AND NOT(keyword_only AND broad) AND views_share<0.35 → supported",
                "R3: (phrase_supported OR repeated_title_template) AND NOT broad AND winners>=1 AND views_share<0.35 → supported",
                "R4: keyword_only AND broad_keyword_group AND winners>=1 → needs_review",
                "R5: cross_source AND winners==1 → needs_review",
                "R6: keyword_only AND NOT broad AND winners>=2 → needs_review",
                "R7: video_topic AND NOT cross_source AND winners>=1 → needs_review",
                "R8: winners>=1 → needs_review",
                "R9: fallback → search_collection",
            ],
            "missing_field_defaults": {
                "quality_flags": [],
                "winner_in_feed_count": 0,
                "zero_or_null_views_share": 0.0,
            },
            "views_metric": "zero_null_missing_share = (views_0 + views_null + missing_latest_snapshot) / members",
        }

        out = {
            "run_id": run_id,
            "classification_spec": spec,
            "tier_counts_exact": dict(tier_counts),
            "families": tier_rows,
            "views_threshold_analysis": threshold_stats,
            "pattern_cap_simulation": cap_report,
        }
        out_path = ROOT / "artifacts" / "audit_opportunity_quality_gate_2a1_report.json"
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"written": str(out_path), "tier_counts": dict(tier_counts), "cap": cap_report["dropped_by_kind"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
