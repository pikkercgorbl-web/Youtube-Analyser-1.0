"""Product Fix 2A — read-only Opportunity Pattern Family audit (PG restore_check)."""
from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text

from app.services.attention_title_normalization import normalize_title

EXPECTED = "youtube_radar_restore_check"
_BROAD_UNIQUE_TITLE_RATIO = 0.45
_BROAD_MIN_VIDEOS = 8


def _url() -> str:
    u = os.environ.get("DATABASE_URL", "").strip()
    if not u:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL="):
                u = line.split("=", 1)[1].strip().strip('"').strip("'")
    if EXPECTED not in (u or ""):
        raise SystemExit("Refusing: not restore_check DB")
    return u


def _title_tokens(title: str) -> set[str]:
    norm = normalize_title(title or "")
    return {t for t in re.split(r"\s+", norm) if len(t) >= 3}


def _heterogeneity_score(titles: list[str]) -> dict:
    if not titles:
        return {"unique_title_ratio": None, "median_pairwise_token_jaccard": None, "likely_heterogeneous": False}
    norms = [normalize_title(t) for t in titles if t]
    unique_ratio = len(set(norms)) / len(norms) if norms else 0.0
    tokens = [_title_tokens(t) for t in titles if t]
    jaccards: list[float] = []
    for i, a in enumerate(tokens):
        for b in tokens[i + 1 :]:
            if not a and not b:
                continue
            union = len(a | b) or 1
            jaccards.append(len(a & b) / union)
    med_j = sorted(jaccards)[len(jaccards) // 2] if jaccards else 1.0
    likely = unique_ratio >= _BROAD_UNIQUE_TITLE_RATIO and len(norms) >= _BROAD_MIN_VIDEOS
    if med_j < 0.08 and len(norms) >= 4:
        likely = True
    return {
        "unique_title_ratio": round(unique_ratio, 3),
        "median_pairwise_token_jaccard": round(med_j, 3),
        "likely_heterogeneous": likely,
    }


def _propose_gate(row: dict) -> str:
    flags = set(row.get("quality_flags") or [])
    kind = row.get("family_kind") or ""
    support = set(row.get("support_sources") or [])
    winners = int(row.get("winner_count") or 0)
    breakout = int(row.get("breakout_eligible_count") or 0)
    channels = int(row.get("channel_count") or 0)
    zero_share = float(row.get("zero_or_null_views_share") or 0)
    vph_measured = int(row.get("vph_measured_count") or 0)
    hetero = bool(row.get("likely_heterogeneous"))

    if (
        "keyword_only" in flags
        or "broad_keyword_group" in flags
        or (kind == "keyword_provenance" and support <= {"keyword"})
    ):
        if breakout >= 2 and winners >= 2 and channels >= 3 and not hetero:
            return "needs_review"
        return "diagnostic"

    if "repeated_title_template" in flags or (
        kind == "title_phrase" and "phrase_supported" in flags and not hetero
    ):
        if winners >= 1 and breakout >= 1 and zero_share < 0.5:
            return "strong"
        return "needs_review"

    if "cross_source_supported" in flags or support >= {"keyword", "title_phrase"} or support >= {
        "keyword",
        "topic",
    }:
        if winners >= 1 and breakout >= 1:
            return "strong"
        return "needs_review"

    if kind == "video_topic" and "topic_supported" in flags:
        if breakout >= 2 and winners >= 2 and not hetero:
            return "needs_review"
        return "diagnostic"

    if winners >= 2 and breakout >= 2 and channels >= 3 and vph_measured >= 2 and zero_share < 0.35:
        return "strong"
    if winners >= 1 and breakout >= 1:
        return "needs_review"
    return "diagnostic"


def main() -> None:
    engine = create_engine(_url(), connect_args={"options": "-c default_transaction_read_only=on"})
    with engine.connect() as c:
        c.execute(text("SET TRANSACTION READ ONLY"))
        run_id = c.execute(
            text("SELECT run_id FROM attention_runs ORDER BY computed_at DESC LIMIT 1"),
        ).scalar()
        if not run_id:
            print(json.dumps({"error": "no attention run"}, indent=2))
            return

        families = c.execute(
            text(
                """
                SELECT rank, family_key, payload_json
                FROM attention_pattern_families
                WHERE run_id = :run_id
                ORDER BY rank ASC
                """,
            ),
            {"run_id": run_id},
        ).fetchall()

        winner_ids = {
            r[0]
            for r in c.execute(
                text("SELECT video_id FROM attention_video_winners WHERE run_id = :run_id"),
                {"run_id": run_id},
            ).fetchall()
        }

        winner_payload = {
            r[0]: json.loads(r[1] or "{}")
            for r in c.execute(
                text(
                    "SELECT video_id, payload_json FROM attention_video_winners WHERE run_id = :run_id",
                ),
                {"run_id": run_id},
            ).fetchall()
        }

        family_videos: dict[str, list[str]] = defaultdict(list)
        for fk, vid in c.execute(
            text(
                """
                SELECT family_key, video_id
                FROM attention_pattern_family_videos
                WHERE run_id = :run_id
                """,
            ),
            {"run_id": run_id},
        ).fetchall():
            family_videos[fk].append(vid)

        video_meta: dict[str, dict] = {}
        for vid, title in c.execute(
            text("SELECT id, title FROM videos"),
        ).fetchall():
            video_meta[vid] = {"title": title or ""}

        latest_views: dict[str, int | None] = {}
        for vid, views in c.execute(
            text(
                """
                SELECT DISTINCT ON (video_id) video_id, views
                FROM video_snapshots
                ORDER BY video_id, captured_at DESC
                """,
            ),
        ).fetchall():
            latest_views[vid] = int(views) if views is not None else None

        rows_out: list[dict] = []
        gate_counts = defaultdict(int)

        for rank, family_key, payload_json in families:
            payload = json.loads(payload_json or "{}")
            vids = family_videos.get(family_key) or list(payload.get("video_ids") or [])
            titles = [video_meta.get(v, {}).get("title", "") for v in vids]
            views_list = [latest_views.get(v) for v in vids]
            zero_null = sum(1 for v in views_list if v is None or v == 0)
            vph_measured = sum(
                1
                for v in vids
                if winner_payload.get(v, {}).get("vph") is not None
                and float(winner_payload.get(v, {}).get("vph") or 0) > 0
            )
            winner_count = sum(1 for v in vids if v in winner_ids)
            hetero = _heterogeneity_score(titles)

            row = {
                "rank": rank,
                "family_key": family_key,
                "label": payload.get("label"),
                "family_kind": payload.get("family_kind"),
                "quality_flags": list(payload.get("quality_flags") or []),
                "support_sources": list(payload.get("support_sources") or []),
                "grouping_reasons": list(payload.get("grouping_reasons") or []),
                "video_count": len(vids),
                "channel_count": payload.get("channel_count"),
                "keyword_count": payload.get("keyword_count"),
                "breakout_eligible_count": payload.get("breakout_eligible_count"),
                "winner_count": winner_count,
                "non_winner_members": len(vids) - winner_count,
                "zero_or_null_views_share": round(zero_null / len(vids), 3) if vids else 0.0,
                "vph_measured_count": vph_measured,
                "has_phrase_support": "phrase_supported" in (payload.get("quality_flags") or []),
                "has_topic_support": "topic_supported" in (payload.get("quality_flags") or []),
                "keyword_only": "keyword_only" in (payload.get("quality_flags") or []),
                "broad_keyword_group": "broad_keyword_group" in (payload.get("quality_flags") or []),
                **hetero,
                "member_pattern_keys": list(payload.get("member_pattern_keys") or []),
            }
            row["proposed_gate"] = _propose_gate(row)
            gate_counts[row["proposed_gate"]] += 1
            rows_out.append(row)

        keyword_search = [
            r
            for r in rows_out
            if r.get("label")
            and ("егэ" in str(r["label"]).lower() or "история россии" in str(r["label"]).lower())
        ]

        summary = {
            "run_id": run_id,
            "family_total": len(rows_out),
            "winner_list_size": len(winner_ids),
            "gate_distribution_proposed": dict(gate_counts),
            "by_kind": defaultdict(int),
            "flag_counts": defaultdict(int),
        }
        for r in rows_out:
            summary["by_kind"][r.get("family_kind") or "unknown"] += 1
            for f in r.get("quality_flags") or []:
                summary["flag_counts"][f] += 1
        summary["by_kind"] = dict(summary["by_kind"])
        summary["flag_counts"] = dict(summary["flag_counts"])

        out = {
            "summary": summary,
            "families": rows_out,
            "keyword_egе_examples": keyword_search,
        }
        out_path = ROOT / "artifacts" / "audit_opportunity_quality_gate_2a_report.json"
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"written": str(out_path), "summary": summary}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
