"""Deterministic thematic relevance for SavedVideo similar-watch (no LLM, no views)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from app.services.attention_title_normalization import normalize_title, significant_tokens, title_ngrams

RelevanceTier = Literal["primary", "other"]

# Title tokens that must not alone justify similarity.
GENERIC_TITLE_TOKENS = frozenset(
    {
        "biggest",
        "largest",
        "greatest",
        "best",
        "top",
        "ever",
        "built",
        "made",
        "world",
        "most",
        "huge",
        "massive",
        "giant",
        "ultimate",
        "ranked",
        "countdown",
        "insane",
        "crazy",
        "real",
        "life",
        "story",
        "history",
        "rise",
        "fall",
        "why",
        "how",
        "what",
        "when",
        "then",
        "now",
        "technology",
        "new",
        "honest",
        "reaction",
        "video",
        "loved",
        "decades",
    },
)

_LEADING_COUNT = re.compile(r"^\d+\s+")

# Homograph disambiguation: only when this token is a subject term in the anchor title.
_SHOPPING_CART_SIGNALS = frozenset(
    {"shop", "shopping", "store", "checkout", "woocommerce", "ecommerce", "cartoon"},
)

PRIMARY_SCORE_THRESHOLD = 42


@dataclass(frozen=True, slots=True)
class AnchorSubjectProfile:
    title: str
    subject_tokens: tuple[str, ...]
    subject_phrases: tuple[str, ...]
    video_topic: str | None


@dataclass(frozen=True, slots=True)
class RelevanceAssessment:
    score: int
    tier: RelevanceTier
    why_found: str | None
    other_reason: str | None


def _strip_leading_count(title: str) -> str:
    return _LEADING_COUNT.sub("", title.strip())


def _token_matches_subject(token: str, subject_set: set[str]) -> bool:
    if token in subject_set:
        return True
    if len(token) > 3 and token.endswith("s") and token[:-1] in subject_set:
        return True
    if f"{token}s" in subject_set:
        return True
    return False


def _subject_hits_in_tokens(tokens: set[str], subjects: tuple[str, ...]) -> list[str]:
    subject_set = set(subjects)
    hits: list[str] = []
    for subj in subjects:
        if any(_token_matches_subject(t, {subj}) for t in tokens):
            hits.append(subj)
    return hits


def subject_tokens_from_title(title: str) -> tuple[str, ...]:
    tokens = significant_tokens(_strip_leading_count(title))
    out = [t for t in tokens if t not in GENERIC_TITLE_TOKENS and not (t.isdigit() and len(t) <= 3)]
    return tuple(dict.fromkeys(out))


def _subject_phrases(title: str, subjects: tuple[str, ...]) -> tuple[str, ...]:
    subject_set = set(subjects)
    phrases: list[str] = []
    seen: set[str] = set()
    for phrase in title_ngrams(_strip_leading_count(title), min_n=2, max_n=4):
        parts = phrase.split()
        subject_hits = sum(1 for p in parts if p in subject_set)
        generic_only = all(p in GENERIC_TITLE_TOKENS or p.isdigit() for p in parts)
        if generic_only:
            continue
        if subject_hits >= 2 or (subject_hits >= 1 and len(parts) >= 2 and subject_hits / len(parts) >= 0.5):
            if phrase not in seen:
                seen.add(phrase)
                phrases.append(phrase)
    return tuple(phrases)


def build_anchor_profile(*, title: str, frozen_payload: dict[str, Any] | None = None) -> AnchorSubjectProfile:
    frozen = frozen_payload or {}
    ctx = frozen.get("context") if isinstance(frozen.get("context"), dict) else {}
    topic_raw = ctx.get("video_topic")
    topic = str(topic_raw).strip() if isinstance(topic_raw, str) and topic_raw.strip() else None
    subjects = subject_tokens_from_title(title)
    return AnchorSubjectProfile(
        title=title,
        subject_tokens=subjects,
        subject_phrases=_subject_phrases(title, subjects),
        video_topic=topic,
    )


def query_meets_subject_bar(query: str, profile: AnchorSubjectProfile) -> bool:
    """Reject search queries that drop anchor subject terms (e.g. «carts ever built»)."""
    q_norm = normalize_title(query)
    if not q_norm:
        return False
    full_title_norm = normalize_title(_strip_leading_count(profile.title))
    if full_title_norm and q_norm == full_title_norm:
        return True
    parts = q_norm.split()
    q_tokens = set(parts)
    subjects = set(profile.subject_tokens)
    if not subjects:
        return len(q_tokens) >= 3
    subject_hits = q_tokens & subjects
    if len(subjects) >= 2 and len(subject_hits) < 2:
        return False
    if len(subjects) == 1 and not subject_hits:
        return False
    if parts and parts[-1] in GENERIC_TITLE_TOKENS and len(subject_hits) < len(parts):
        if len(parts) >= 2 and parts[-2] in GENERIC_TITLE_TOKENS:
            return False
        if parts[-1] in {"ever", "built", "made"}:
            return False
    return True


def _homograph_shopping_cart(norm_title: str, profile: AnchorSubjectProfile) -> str | None:
    subjects = set(profile.subject_tokens)
    if "cart" not in subjects and "carts" not in subjects:
        return None
    tokens = set(norm_title.split())
    if not (tokens & {"cart", "carts"}):
        return None
    if tokens & _SHOPPING_CART_SIGNALS:
        return "похоже на интернет-магазин, а не на тему исходного ролика"
    if "shopping cart" in norm_title or "add to cart" in norm_title:
        return "похоже на интернет-магазин, а не на тему исходного ролика"
    return None


def _generic_only_overlap(norm_title: str, profile: AnchorSubjectProfile) -> bool:
    title_tokens = set(norm_title.split())
    anchor_norm = normalize_title(_strip_leading_count(profile.title))
    anchor_tokens = set(anchor_norm.split())
    overlap = title_tokens & anchor_tokens
    if not overlap:
        return False
    return overlap.issubset(GENERIC_TITLE_TOKENS)


def _multi_subject_gate(
    profile: AnchorSubjectProfile,
    *,
    norm: str,
    subject_hits: list[str],
) -> str | None:
    """When the anchor has several subject terms, one shared word is not enough."""
    if len(profile.subject_tokens) < 2:
        return None
    if any(phrase in norm for phrase in profile.subject_phrases):
        return None
    if len(subject_hits) >= 2:
        return None
    if len(subject_hits) == 1:
        return "совпало только одно предметное слово из нескольких в исходном названии"
    return None


def assess_similarity(
    profile: AnchorSubjectProfile,
    *,
    candidate_title: str,
    matched_query: str,
) -> RelevanceAssessment:
    norm = normalize_title(candidate_title)
    if not norm:
        return RelevanceAssessment(0, "other", None, "нет названия для сравнения")

    homograph = _homograph_shopping_cart(norm, profile)
    if homograph:
        return RelevanceAssessment(0, "other", None, homograph)

    score = 0
    why_parts: list[str] = []

    subjects = profile.subject_tokens
    subject_set = set(subjects)
    cand_tokens = set(norm.split())

    subject_hits = _subject_hits_in_tokens(cand_tokens, subjects)
    if subject_hits:
        score += 18 * len(subject_hits)
        why_parts.append("совпадение предметных слов: " + ", ".join(subject_hits))

    for phrase in profile.subject_phrases:
        if phrase in norm:
            score += 28
            why_parts.append(f"фраза из исходного названия «{phrase}»")
            break

    if query_meets_subject_bar(matched_query, profile):
        q_norm = normalize_title(matched_query)
        if q_norm and (q_norm in norm or any(p in norm for p in q_norm.split() if p in subject_set)):
            score += 8
    else:
        score -= 12

    if _generic_only_overlap(norm, profile):
        return RelevanceAssessment(
            max(0, score),
            "other",
            None,
            "совпали только общие слова (biggest, ever, built и т.п.)",
        )

    gate = _multi_subject_gate(profile, norm=norm, subject_hits=subject_hits)
    if gate:
        return RelevanceAssessment(max(0, score), "other", None, gate)

    if not subject_hits and not any(p in norm for p in profile.subject_phrases):
        lone_cart = (" cart " in f" {norm} " or norm.startswith("cart ")) and (
            "cart" in subject_set or "carts" in subject_set
        )
        if lone_cart:
            return RelevanceAssessment(
                max(0, score),
                "other",
                None,
                "слово «cart» без других предметных слов из исходного названия",
            )
        return RelevanceAssessment(
            max(0, score),
            "other",
            None,
            "нет предметных слов из исходного названия",
        )

    score = max(0, min(100, score))
    dual_anchor_overlap = len(subject_hits) >= 2 and len(subjects) >= 2
    tier: RelevanceTier = (
        "primary" if score >= PRIMARY_SCORE_THRESHOLD or dual_anchor_overlap else "other"
    )
    pov_format_mismatch: str | None = None
    if tier == "primary" and "pov" in subject_set and "pov" not in cand_tokens:
        tier = "other"
        pov_format_mismatch = "другой формат ролика (нет POV из исходного названия)"
    why: str | None = None
    other_reason: str | None = None
    if tier == "primary" and why_parts:
        why = "; ".join(why_parts[:2])
    elif tier == "other":
        other_reason = pov_format_mismatch or (
            "низкая тематическая близость"
            if score >= 20
            else "слабое совпадение с темой исходного ролика"
        )
    return RelevanceAssessment(score, tier, why, other_reason)


def attach_relevance_to_payload(
    payload: dict[str, Any],
    profile: AnchorSubjectProfile,
    *,
    matched_query: str,
) -> dict[str, Any]:
    title = str(payload.get("title") or "")
    rel = assess_similarity(profile, candidate_title=title, matched_query=matched_query)
    out = dict(payload)
    out["relevance_score"] = rel.score
    out["relevance_tier"] = rel.tier
    out["why_found"] = rel.why_found
    out["other_reason"] = rel.other_reason
    return out


def relevance_from_payload(
    payload: dict[str, Any],
    profile: AnchorSubjectProfile,
    *,
    matched_query: str,
) -> RelevanceAssessment:
    """Always apply current rules to the stored title (ignore scan-time tier cache)."""
    return assess_similarity(
        profile,
        candidate_title=str(payload.get("title") or ""),
        matched_query=matched_query,
    )


def parse_frozen_json(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
