#!/usr/bin/env python3
"""
Stage 7 (corrected): compare saved LLM queries vs manual English baselines on the same theme.

- No DB writes, no workers, no new LLM calls.
- Baselines are explicit manual controls (not deterministic keyword expansion).
- One InnerTube page per query; identical settings within each pair (hl/gl from query text, upload-date sort).
- Reuses cached search rows from groq_stage7_search_compare_latest.json when settings match.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import load_dotenv

EXPERIMENT_ARTIFACT = ROOT / "artifacts" / "groq_radar_evidence_experiment_20261007T152414Z.json"
PACKETS_SNAPSHOT = ROOT / "artifacts" / "groq_radar_evidence_packets_20261007T152414Z.json"
CACHE_ARTIFACT = ROOT / "artifacts" / "groq_stage7_search_compare_latest.json"

SEARCH_SETTINGS = {
    "client": "iter_radar_search_pages",
    "max_pages": 1,
    "sort_by_upload_date": True,
    "persist_pipeline": False,
    "locale_rule": "hl=en gl=US for Latin queries; hl=ru gl=RU if query contains Cyrillic",
}

THEMATIC_PAIRS = [
    {
        "pair_id": "betrayal_stories",
        "theme_label": "betrayal / personal drama storytime",
        "baseline_query": "betrayal stories",
        "baseline_kind": "manual_control_en",
        "llm_query": "real life betrayal stories",
        "llm_packet_id": "keyword:146",
    },
    {
        "pair_id": "abandoned_places",
        "theme_label": "mysterious abandoned places narratives",
        "baseline_query": "abandoned places stories",
        "baseline_kind": "manual_control_en",
        "llm_query": "real stories of mysterious abandoned places",
        "llm_packet_id": "keyword:146",
    },
    {
        "pair_id": "anime_what_if",
        "theme_label": "anime-style what-if hypotheticals",
        "baseline_query": "anime what if",
        "baseline_kind": "manual_control_en",
        "llm_query": "what if you have cursed energy",
        "llm_packet_id": "keyword:148",
    },
]

TRAVEL_RE = re.compile(r"\b(travel|vlog|trip|packing|jeju|armenia|italy solo)\b", re.I)
CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")

THEME_PATTERNS: dict[str, re.Pattern[str]] = {
    "betrayal_stories": re.compile(
        r"\b(betray|betrayal|cheat|cheating|affair|trust|revenge|drama|story|stories|"
        r"husband|wife|friend|family|relationship|heartbreak)\b",
        re.I,
    ),
    "abandoned_places": re.compile(
        r"\b(abandon|abandoned|ghost|haunt|myster|mystery|urbex|empty|forgotten|"
        r"creepy|bunker|ranch|ruin|explor)\b",
        re.I,
    ),
    "anime_what_if": re.compile(
        r"\b(what if|anime|jjk|jujutsu|cursed|naruto|mha|hypothet|scenario|"
        r"vs\b|power|energy|character)\b",
        re.I,
    ),
}

IRRELEVANT_PATTERNS = re.compile(
    r"\b(recipe|cooking|minecraft|fortnite|music video|official video|live stream|"
    r"asmr sleep|prank|giveaway|crypto|forex)\b",
    re.I,
)

FACELESS_FORMAT_HINT = re.compile(
    r"\b(story|stories|narrat|explained|what if|hypothet|documentary|tale|"
    r"real life|animated explainer|voiceover)\b",
    re.I,
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _settings_match(cached: dict | None) -> bool:
    if not cached:
        return False
    s = cached.get("search_settings") or {}
    return (
        s.get("client") == SEARCH_SETTINGS["client"]
        and s.get("max_pages") == SEARCH_SETTINGS["max_pages"]
        and s.get("sort_by_upload_date") == SEARCH_SETTINGS["sort_by_upload_date"]
    )


def _index_cached_searches(cached: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in cached.get("search_results") or []:
        q = row.get("query")
        if q and q not in out:
            out[q] = row
    return out


def _llm_provenance(experiment: dict, llm_query: str) -> dict[str, Any]:
    for run in experiment.get("runs", []):
        for s in run.get("validated_suggestions") or []:
            if (s.get("query") or "").casefold() == llm_query.casefold():
                return {
                    "packet_id": run.get("packet_id"),
                    "source_video_ids": s.get("source_video_ids") or [],
                    "llm_reason": s.get("reason"),
                }
    return {}


def _content_format(video) -> str:
    from app.integrations.youtube.client import LiveBroadcastStatus, video_is_stream_content

    if video.is_short:
        return "short"
    if video.is_live or video_is_stream_content(video):
        return "live"
    if video.live_broadcast_status == LiveBroadcastStatus.UNKNOWN:
        return "unknown"
    return "regular"


def _language_hint(title: str) -> str:
    if not title:
        return "unknown"
    cyr = len(CYRILLIC_RE.findall(title))
    lat = len(re.findall(r"[A-Za-z]", title))
    if cyr > lat and cyr >= 3:
        return "cyrillic_heavy"
    if lat > cyr and lat >= 3:
        return "latin_heavy"
    if cyr and lat:
        return "mixed"
    return "unknown"


def _innertube_locale_note(query: str) -> dict[str, str]:
    from app.integrations.youtube.client import _innertube_locale_for_text

    hl, gl = _innertube_locale_for_text(query)
    return {"hl": hl, "gl": gl}


async def _search_one(query: str, *, pair_id: str, kind: str) -> dict[str, Any]:
    from app.integrations.youtube.client import iter_radar_search_pages

    started = datetime.now(timezone.utc)
    videos = []
    renderer_counts: dict[str, int] = {}
    async for page in iter_radar_search_pages(
        query,
        sort_by_upload_date=True,
        max_pages=1,
    ):
        videos = list(page.videos)
        renderer_counts = dict(page.renderer_counts or {})
        break
    finished = datetime.now(timezone.utc)
    rows = []
    for v in videos:
        subs = int(v.subscribers_count or 0)
        rows.append(
            {
                "video_id": v.video_id,
                "channel_id": v.channel_id,
                "channel_title": (v.channel_title or "")[:120],
                "title": (v.title or "")[:500],
                "views_count": v.views_count,
                "content_format": _content_format(v),
                "language_hint": _language_hint(v.title or ""),
                "subscribers_count_search": subs if subs > 0 else None,
                "subscribers_note": (
                    "search_card_subs_unconfirmed"
                    if subs <= 0
                    else "innertube_search_subs_not_api_verified"
                ),
                "youtube_url": f"https://www.youtube.com/watch?v={v.video_id}",
            },
        )
    return {
        "query": query,
        "pair_id": pair_id,
        "kind": kind,
        "innertube_locale": _innertube_locale_note(query),
        "started_at_utc": started.isoformat(),
        "finished_at_utc": finished.isoformat(),
        "duration_ms": int((finished - started).total_seconds() * 1000),
        "renderer_counts": renderer_counts,
        "result_count": len(rows),
        "results": rows,
        "source": "live_innertube",
    }


def _classify_row(pair_id: str, title: str, content_format: str) -> dict[str, Any]:
    theme_re = THEME_PATTERNS.get(pair_id)
    thematic = bool(theme_re and theme_re.search(title or ""))
    irrelevant = bool(IRRELEVANT_PATTERNS.search(title or "")) or bool(TRAVEL_RE.search(title or ""))
    faceless_hint = (
        content_format == "regular"
        and not irrelevant
        and bool(FACELESS_FORMAT_HINT.search(title or ""))
    )
    return {
        "thematic_title_match_heuristic": thematic,
        "likely_irrelevant_heuristic": irrelevant,
        "faceless_production_format_hint_only": faceless_hint,
        "faceless_note": "Not verified without watching; shorts/live not counted as faceless-ready",
    }


def _analyze_pair(
    pair: dict,
    baseline: dict,
    llm: dict,
    known_corpus: set[str],
) -> dict[str, Any]:
    pid = pair["pair_id"]
    base_rows = {r["video_id"]: r for r in baseline.get("results", [])}
    llm_rows = {r["video_id"]: r for r in llm.get("results", [])}
    base_ids = set(base_rows)
    llm_ids = set(llm_rows)
    inter = base_ids & llm_ids
    base_only = base_ids - llm_ids
    llm_only = llm_ids - base_ids

    def bucket(ids: set[str], source: dict[str, dict]) -> dict[str, Any]:
        thematic: list[str] = []
        extra_good: list[str] = []
        irrelevant: list[str] = []
        formats: dict[str, list[str]] = {}
        for vid in ids:
            r = source[vid]
            cls = _classify_row(pid, r.get("title") or "", r.get("content_format") or "unknown")
            fmt = r.get("content_format") or "unknown"
            formats.setdefault(fmt, []).append(vid)
            if cls["likely_irrelevant_heuristic"]:
                irrelevant.append(vid)
            elif cls["thematic_title_match_heuristic"]:
                thematic.append(vid)
            else:
                extra_good.append(vid)
        return {
            "thematic_video_ids": thematic,
            "neutral_or_unclear_video_ids": extra_good,
            "likely_irrelevant_video_ids": irrelevant,
            "content_format_counts": {k: len(v) for k, v in formats.items()},
        }

    llm_new_vs_corpus = sorted(llm_ids - known_corpus)
    return {
        "pair_id": pid,
        "theme_label": pair["theme_label"],
        "baseline_query": pair["baseline_query"],
        "llm_query": pair["llm_query"],
        "baseline_kind": pair["baseline_kind"],
        "innertube_locale_baseline": baseline.get("innertube_locale"),
        "innertube_locale_llm": llm.get("innertube_locale"),
        "intersection_video_ids": sorted(inter),
        "intersection_count": len(inter),
        "baseline_only_count": len(base_only),
        "llm_only_count": len(llm_only),
        "baseline_page_analysis": bucket(base_only, base_rows),
        "llm_page_analysis": bucket(llm_only, llm_rows),
        "intersection_titles": [
            {
                "video_id": vid,
                "title": base_rows[vid]["title"],
                "youtube_url": base_rows[vid]["youtube_url"],
                "content_format": base_rows[vid]["content_format"],
            }
            for vid in sorted(inter)
        ],
        "llm_overlap_known_evidence_corpus": sorted(llm_ids & known_corpus),
        "llm_ids_not_in_evidence_corpus_count": len(llm_new_vs_corpus),
        "llm_new_ids_not_auto_useful": True,
        "same_theme_interpretation": (
            "Both queries are English and target the same narrative niche; overlap and title heuristics "
            "measure query phrasing, not proof that LLM beats manual baselines."
        ),
    }


def _row_example(
    pair: dict,
    r: dict,
    *,
    role: str,
    in_intersection: bool,
) -> dict[str, Any]:
    cls = _classify_row(pair["pair_id"], r.get("title") or "", r.get("content_format") or "unknown")
    return {
        "pair_id": pair["pair_id"],
        "role": role,
        "baseline_query": pair["baseline_query"],
        "llm_query": pair["llm_query"],
        "video_id": r["video_id"],
        "title": r["title"],
        "channel_title": r.get("channel_title"),
        "youtube_url": r["youtube_url"],
        "content_format": r["content_format"],
        "language_hint": r.get("language_hint"),
        "in_baseline_llm_intersection": in_intersection,
        **cls,
        "limitations": [
            "Title-only heuristic; watch video to judge faceless suitability",
            "No API subscriber cap claim (≤100k not asserted)",
            "Single InnerTube page; new ID ≠ validated opportunity",
        ],
    }


def _manual_examples_for_pair(
    pair: dict,
    baseline: dict,
    llm: dict,
    analysis: dict,
    *,
    min_examples: int = 3,
    max_examples: int = 5,
) -> list[dict]:
    base_rows = {r["video_id"]: r for r in baseline.get("results", [])}
    llm_rows = {r["video_id"]: r for r in llm.get("results", [])}
    inter = set(analysis.get("intersection_video_ids") or [])
    examples: list[dict] = []
    seen: set[str] = set()

    def add(r: dict, role: str, in_inter: bool) -> None:
        if r["video_id"] in seen or len(examples) >= max_examples:
            return
        seen.add(r["video_id"])
        examples.append(_row_example(pair, r, role=role, in_intersection=in_inter))

    for vid in sorted(inter)[:2]:
        add(base_rows[vid], "intersection_baseline_and_llm", True)

    for vid in analysis["llm_page_analysis"].get("thematic_video_ids") or []:
        if vid not in inter:
            add(llm_rows[vid], "llm_only_thematic_extra", False)
        if len(examples) >= max_examples:
            break

    for vid in analysis["baseline_page_analysis"].get("thematic_video_ids") or []:
        add(base_rows[vid], "baseline_only_thematic", False)
        if len(examples) >= max_examples:
            break

    for vid in (analysis["llm_page_analysis"].get("likely_irrelevant_video_ids") or [])[:1]:
        add(llm_rows[vid], "llm_only_likely_irrelevant", False)

    for vid in (analysis["baseline_page_analysis"].get("likely_irrelevant_video_ids") or [])[:1]:
        add(base_rows[vid], "baseline_only_likely_irrelevant", False)

    if len(examples) < min_examples:
        for r in llm.get("results") or []:
            add(r, "llm_page_fill", r["video_id"] in inter)
            if len(examples) >= min_examples:
                break
    return examples[:max_examples]


async def _run_with_cache(
    plan: list[dict],
    cached_by_query: dict[str, dict],
    *,
    cache_settings_ok: bool,
) -> tuple[list[dict], int]:
    out: list[dict] = []
    live_count = 0
    for i, row in enumerate(plan):
        q = row["query"]
        cached = cached_by_query.get(q)
        if cached and cache_settings_ok:
            entry = {
                "query": q,
                "pair_id": row["pair_id"],
                "kind": row["kind"],
                "innertube_locale": cached.get("innertube_locale") or _innertube_locale_note(q),
                "result_count": cached.get("result_count"),
                "results": cached.get("results") or [],
                "renderer_counts": cached.get("renderer_counts") or {},
                "source": "reused_from_cache",
                "reused_from": str(CACHE_ARTIFACT.relative_to(ROOT)),
            }
            out.append(entry)
            continue
        if i > 0 and live_count > 0:
            await asyncio.sleep(1.5)
        result = await _search_one(q, pair_id=row["pair_id"], kind=row["kind"])
        live_count += 1
        out.append(result)
    return out, live_count


def _build_plan() -> list[dict]:
    plan: list[dict] = []
    for pair in THEMATIC_PAIRS:
        plan.append(
            {"pair_id": pair["pair_id"], "kind": "baseline", "query": pair["baseline_query"]},
        )
        plan.append({"pair_id": pair["pair_id"], "kind": "llm_saved", "query": pair["llm_query"]})
    return plan


def main() -> int:
    load_dotenv(ROOT / ".env")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = ROOT / "artifacts" / f"groq_stage7_thematic_pairs_{ts}.json"
    latest = ROOT / "artifacts" / "groq_stage7_search_compare_latest.json"

    experiment = _load_json(EXPERIMENT_ARTIFACT)
    snapshot = _load_json(PACKETS_SNAPSHOT)
    known_corpus: set[str] = set()
    for p in snapshot.get("packets", []):
        for r in p.get("rows", []):
            known_corpus.add(r["video_id"])

    cached_doc = _load_json(CACHE_ARTIFACT) if CACHE_ARTIFACT.exists() else {}
    cached_by_query = _index_cached_searches(cached_doc) if _settings_match(cached_doc) else {}

    for pair in THEMATIC_PAIRS:
        pair["llm_provenance"] = _llm_provenance(experiment, pair["llm_query"])

    plan = _build_plan()
    cache_ok = _settings_match(cached_doc)
    search_results, live_searches = asyncio.run(
        _run_with_cache(plan, cached_by_query, cache_settings_ok=cache_ok),
    )

    by_query = {s["query"]: s for s in search_results}
    pair_analyses = []
    manual_all: list[dict] = []
    for pair in THEMATIC_PAIRS:
        b = by_query[pair["baseline_query"]]
        l = by_query[pair["llm_query"]]
        analysis = _analyze_pair(pair, b, l, known_corpus)
        pair_analyses.append(analysis)
        manual_all.extend(_manual_examples_for_pair(pair, b, l, analysis))

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": 7,
        "methodology": "thematic_en_pairs_manual_baseline_vs_saved_llm",
        "supersedes_flawed_run": {
            "note": "Prior 9-search RU/EN cross-topic compare is NOT evidence of LLM advantage.",
            "flawed_artifact_may_exist": "groq_stage7_search_compare_latest.json (pre-fix content)",
        },
        "no_llm_calls": True,
        "no_db_writes": True,
        "live_innertube_searches_this_run": live_searches,
        "max_live_searches_allowed": 6,
        "source_experiment": str(EXPERIMENT_ARTIFACT.relative_to(ROOT)),
        "source_packets": str(PACKETS_SNAPSHOT.relative_to(ROOT)),
        "cache_reuse": {
            "path": str(CACHE_ARTIFACT.relative_to(ROOT)) if CACHE_ARTIFACT.exists() else None,
            "settings_matched": _settings_match(cached_doc),
            "queries_reused": [
                s["query"] for s in search_results if s.get("source") == "reused_from_cache"
            ],
        },
        "thematic_pairs": THEMATIC_PAIRS,
        "search_plan": plan,
        "search_settings": SEARCH_SETTINGS,
        "search_results": search_results,
        "pair_analyses": pair_analyses,
        "manual_review_examples": manual_all,
        "conclusions": [
            "Compare English manual baselines to saved English LLM queries on the same theme only.",
            "Intersection size reflects query wording and YouTube ranking, not LLM superiority.",
            "LLM-only video IDs require manual review; not auto-counted as discoveries.",
            "Faceless production claims require video review; format hints are title-based only.",
            "Channel size ≤100k not stated without API subscriber evidence.",
        ],
        "disclaimers": [
            "InnerTube locale follows query script (en/US for these pairs).",
            "Upload-date sort on page 1 only; not full Radar discovery qualification.",
            "Evidence corpus overlap does not validate search result quality.",
        ],
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    out_path.write_text(text, encoding="utf-8")
    latest.write_text(text, encoding="utf-8")
    print(
        json.dumps(
            {
                "artifact": str(out_path.relative_to(ROOT)),
                "live_searches": live_searches,
                "pairs": len(THEMATIC_PAIRS),
            },
            indent=2,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
