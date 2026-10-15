"""Fix 2A.2 — supported-family deep dive + full tier table (PG read-only)."""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text

EXPECTED = "youtube_radar_restore_check"
SUPPORTED_KEYS = (
    "family:kw:1505",
    "family:kw:1561",
    "family:kw:1506",
    "family:topic:4ac6a6a26765f407",
)


def _url() -> str:
    u = os.environ.get("DATABASE_URL", "").strip()
    if not u:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL="):
                u = line.split("=", 1)[1].strip().strip('"').strip("'")
    if EXPECTED not in (u or ""):
        raise SystemExit("Refusing: not restore_check DB")
    return u


def main() -> None:
    report_path = ROOT / "artifacts" / "audit_opportunity_quality_gate_2a1_report.json"
    tier_report = json.loads(report_path.read_text(encoding="utf-8"))
    engine = create_engine(_url(), connect_args={"options": "-c default_transaction_read_only=on"})
    with engine.connect() as c:
        c.execute(text("SET TRANSACTION READ ONLY"))
        run_id = c.execute(
            text("SELECT run_id FROM attention_runs ORDER BY computed_at DESC LIMIT 1"),
        ).scalar()
        if tier_report.get("run_id") != run_id:
            print(json.dumps({"warn": "tier report run_id differs from latest PG run", "report": tier_report.get("run_id"), "latest": run_id}))

        winner_set = {
            r[0]: json.loads(r[1] or "{}")
            for r in c.execute(
                text("SELECT video_id, payload_json FROM attention_video_winners WHERE run_id = :r"),
                {"r": run_id},
            ).fetchall()
        }

        patterns = {
            r[0]: json.loads(r[1] or "{}")
            for r in c.execute(
                text("SELECT pattern_key, payload_json FROM attention_patterns WHERE run_id = :r"),
                {"r": run_id},
            ).fetchall()
        }

        video_rows = {
            r[0]: {"title": r[1], "channel_id": r[2], "topic": r[3]}
            for r in c.execute(text("SELECT id, title, channel_id, topic FROM videos")).fetchall()
        }
        channel_titles = {r[0]: r[1] for r in c.execute(text("SELECT id, title FROM channels")).fetchall()}

        def family_bundle(family_key: str) -> dict:
            payload = json.loads(
                c.execute(
                    text("SELECT payload_json FROM attention_pattern_families WHERE run_id=:r AND family_key=:k"),
                    {"r": run_id, "k": family_key},
                ).scalar()
                or "{}",
            )
            vids = [
                r[0]
                for r in c.execute(
                    text(
                        "SELECT video_id FROM attention_pattern_family_videos WHERE run_id=:r AND family_key=:k",
                    ),
                    {"r": run_id, "k": family_key},
                ).fetchall()
            ]
            members = [
                r[0]
                for r in c.execute(
                    text(
                        """
                        SELECT pattern_key FROM attention_pattern_family_members
                        WHERE run_id=:r AND family_key=:k
                        """,
                    ),
                    {"r": run_id, "k": family_key},
                ).fetchall()
            ]
            feed_winners = [v for v in vids if v in winner_set]
            non_winners = [v for v in vids if v not in winner_set]

            def vid_row(vid: str, role: str) -> dict:
                meta = video_rows.get(vid, {})
                ch = meta.get("channel_id") or ""
                return {
                    "role": role,
                    "video_id": vid,
                    "title": meta.get("title"),
                    "channel_id": ch,
                    "channel_title": channel_titles.get(ch),
                    "video_topic": (meta.get("topic") or "").strip() or None,
                    "youtube_url": f"https://www.youtube.com/watch?v={vid}",
                    "in_feed_winners": vid in winner_set,
                    "winner_payload_vph": winner_set.get(vid, {}).get("vph"),
                }

            winner_rows = [vid_row(v, "feed_winner") for v in feed_winners]
            # up to 4 non-winner samples: first by sort
            sample_members = [vid_row(v, "member") for v in non_winners[:4]]

            overlapping_kinds = set()
            vid_set = set(vids)
            overlap_patterns = []
            for pk, p in patterns.items():
                p_vids = set(p.get("participating_video_ids") or [])
                if p_vids & vid_set:
                    overlapping_kinds.add(p.get("kind"))
                    if pk not in members:
                        overlap_patterns.append(
                            {"pattern_key": pk, "kind": p.get("kind"), "label": p.get("label")},
                        )

            return {
                "family_key": family_key,
                "label": payload.get("label"),
                "family_kind": payload.get("family_kind"),
                "quality_flags": payload.get("quality_flags"),
                "support_sources": payload.get("support_sources"),
                "member_pattern_keys": members,
                "member_patterns": [{k: patterns.get(pk, {}).get(k) for k in ("pattern_key", "kind", "label")} for pk in members],
                "cross_source_explanation": {
                    "definition": (
                        "cross_source_supported iff len(support_sources)>=2 after _support_and_flags, "
                        "i.e. among patterns in the TRUNCATED top-N list, same videos appear in patterns of "
                        "different kinds (keyword_provenance, title_phrase, video_topic)."
                    ),
                    "overlapping_kinds_in_top20_patterns": sorted(overlapping_kinds),
                    "other_overlapping_patterns_sample": overlap_patterns[:8],
                },
                "feed_winner_count": len(feed_winners),
                "member_count": len(vids),
                "feed_winners": winner_rows,
                "sample_non_winner_members": sample_members,
            }

        supported_deep = [family_bundle(k) for k in SUPPORTED_KEYS]

        # Full 20 table from DB + tier report merge
        families_db = c.execute(
            text(
                """
                SELECT rank, family_key, payload_json
                FROM attention_pattern_families WHERE run_id = :r ORDER BY rank
                """,
            ),
            {"r": run_id},
        ).fetchall()
        tier_by_key = {f["family_key"]: f for f in tier_report.get("families", [])}
        full_table = []
        keys_seen = set()
        tier_sum: dict[str, int] = defaultdict(int)
        for rank, fk, pj in families_db:
            if fk in keys_seen:
                raise SystemExit(f"duplicate family_key: {fk}")
            keys_seen.add(fk)
            p = json.loads(pj or "{}")
            tr = tier_by_key.get(fk, {})
            tier = tr.get("tier", "MISSING")
            rule = tr.get("tier_rule_id", "?")
            w = tr.get("winner_in_feed_count", "?")
            tier_sum[tier] += 1
            full_table.append(
                {
                    "rank": rank,
                    "family_key": fk,
                    "label": p.get("label"),
                    "family_kind": p.get("family_kind"),
                    "flags": p.get("quality_flags"),
                    "tier": tier,
                    "rule_id": rule,
                    "feed_winners": w,
                },
            )

        out = {
            "run_id": run_id,
            "supported_family_deep_dive": supported_deep,
            "full_table_20": full_table,
            "tier_counts_from_table": dict(tier_sum),
            "family_key_unique": len(keys_seen) == 20,
            "pattern_cap_hook": {
                "file": "app/services/attention_patterns.py",
                "function": "build_pattern_candidates",
                "count_before_truncation_line": "~300 (patterns.sort; return patterns[: config.pattern_limit])",
                "requires": "AttentionEvidenceBundle from load_attention_evidence — full recompute >10min on restore_check",
                "safe_alternative_for_next_refresh": (
                    "Append-only JSON in attention_runs.notes_json at end of compute_attention_engine: "
                    "pattern_candidates_by_kind_before_cap, pattern_candidates_by_kind_after_cap, "
                    "dropped_title_phrase_count — read-only logging inside existing compute, no sort/cap change."
                ),
                "persisted_top20_by_kind": defaultdict(int),
            },
        }
        for pk, p in patterns.items():
            kind = p.get("kind") or "unknown"
            out["pattern_cap_hook"]["persisted_top20_by_kind"][kind] += 1
        out["pattern_cap_hook"]["persisted_top20_by_kind"] = dict(out["pattern_cap_hook"]["persisted_top20_by_kind"])

        path = ROOT / "artifacts" / "audit_opportunity_quality_gate_2a2_report.json"
        path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"written": str(path), "tier_sum": dict(tier_sum)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
