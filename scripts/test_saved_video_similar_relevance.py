#!/usr/bin/env python3
"""Relevance + query suggest tests (grain carts live-scan examples)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.saved_video_similar_query_suggest import suggest_similar_search_queries
from app.services.saved_video_similar_relevance import (
    assess_similarity,
    build_anchor_profile,
    query_meets_subject_bar,
    relevance_from_payload,
)

ANCHOR_TITLE = "10 Biggest Grain Carts Ever Built"


def _profile():
    return build_anchor_profile(title=ANCHOR_TITLE, frozen_payload=None)


def test_suggest_no_carts_ever_built_fragment() -> None:
    suggestions = suggest_similar_search_queries(title=ANCHOR_TITLE)
    assert "carts ever built" not in [s.casefold() for s in suggestions]
    assert any("grain" in s and "cart" in s for s in suggestions)
    assert 1 <= len(suggestions) <= 5


def test_query_bar_rejects_weak_query() -> None:
    p = _profile()
    assert query_meets_subject_bar("biggest grain carts ever built", p)
    assert not query_meets_subject_bar("carts ever built", p)


def test_live_irrelevant_titles() -> None:
    p = _profile()
    cases = [
        ("THE USSR'S BIGGEST CON ARTIST: How He Stole Millions", "other"),
        ("Top 10 BEST Satisfactory Mods in 2026", "other"),
        ("TOURISTS ARE RARE HERE! Real Life in RURAL CHINA!", "other"),
        ("This Giant John Deere Combine Swallows an Entire Cornfield!", "other"),
        ("Get stronger in 6 weeks, warmup.", "other"),
        ("Chris Olson Can Kill a Pickleball Paddle With One Video", "other"),
        ("Cigars & Wild Headlines | CHPOD 642", "other"),
        ("The Real Cost of a Kilogram in Orbit", "other"),
    ]
    for title, tier in cases:
        rel = assess_similarity(p, candidate_title=title, matched_query="biggest grain carts ever built")
        assert rel.tier == tier, (title, rel.tier, rel.other_reason)


def test_tesla_subject_extraction() -> None:
    title = "The NEW Tesla Roadster: My Honest Reaction"
    p = build_anchor_profile(title=title, frozen_payload=None)
    assert "tesla" in p.subject_tokens
    assert "roadster" in p.subject_tokens
    rel = assess_similarity(
        p,
        candidate_title="Tesla Roadster 2025 prototype spotted",
        matched_query="tesla roadster",
    )
    assert rel.tier == "primary"


def test_grain_cart_primary() -> None:
    p = _profile()
    rel = assess_similarity(
        p,
        candidate_title="World's Largest Grain Cart — 2000 Bushel Monster",
        matched_query="biggest grain carts",
    )
    assert rel.tier == "primary"
    assert rel.why_found


def test_stale_payload_recategorized_with_live_rules() -> None:
    p = _profile()
    payload = {
        "title": "Running grain cart with 2009 8000 series and 2015 760 harvester",
        "relevance_tier": "other",
        "relevance_score": 18,
        "other_reason": "низкая тематическая близость",
    }
    rel = relevance_from_payload(payload, p, matched_query="grain carts")
    assert rel.tier == "primary", rel


def test_pov_anchor_rejects_non_pov_primary() -> None:
    anchor_title = (
        "POV: The Salesman Had You Arrested — Then the GM Confirmed You Own the Dealership"
    )
    p = build_anchor_profile(title=anchor_title)
    rel = assess_similarity(
        p,
        candidate_title="HOA Had Me Arrested Over My Own Truck",
        matched_query="had arrested",
    )
    assert rel.tier == "other"
    assert rel.other_reason and "POV" in rel.other_reason
    rel_ok = assess_similarity(
        p,
        candidate_title="POV: You Started Washing Cars for $15 — Now You Own 9 Car Washes",
        matched_query="pov salesman",
    )
    assert rel_ok.tier == "primary"


def test_dual_subject_below_score_threshold_still_primary() -> None:
    p = _profile()
    rel = assess_similarity(
        p,
        candidate_title="Brian gets to be the grain cart driver",
        matched_query="biggest grain carts",
    )
    assert rel.tier == "primary"


if __name__ == "__main__":
    test_suggest_no_carts_ever_built_fragment()
    test_query_bar_rejects_weak_query()
    test_live_irrelevant_titles()
    test_tesla_subject_extraction()
    test_grain_cart_primary()
    test_stale_payload_recategorized_with_live_rules()
    test_pov_anchor_rejects_non_pov_primary()
    test_dual_subject_below_score_threshold_still_primary()
    print("OK relevance tests")
