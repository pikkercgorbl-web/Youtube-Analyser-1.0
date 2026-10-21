"""Deterministic topic-search query plan for SavedFamily (no LLM)."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Literal

from app.services.attention_title_normalization import normalize_title, significant_tokens, title_ngrams
from app.services.saved_video_similar_watch_config import saved_video_similar_watch_settings

SourceType = Literal["family_label", "aligned_keyword", "shared_title_phrase"]
SuggestionMode = Literal["auto", "heterogeneous", "manual"]

_ID_LIKE = re.compile(r"^(UC[\w-]{10,}|\d{5,})$")
_PATTERN_KEY = re.compile(r"^(pf_|pat_|pattern_|kw:\d+)", re.I)
_MUSIC_OR_OFFTOPIC = re.compile(
    r"\b(phonk|karaoke|lyrics|reddit|истории\s+reddit|1\s+час)\b",
    re.I,
)
_MUSIC_ANCHOR = re.compile(r"\b(phonk|karaoke|lyrics|song|music|песн)\b", re.I)

_BILINGUAL_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"meme", "memes", "мем", "мемы"}),
    frozenset({"then", "now", "тогда", "сейчас"}),
    frozenset({"discipline", "дисциплина"}),
    frozenset({"what", "if", "что", "если"}),
    frozenset({"space", "космос", "universe"}),
    frozenset({"reddit", "reddit"}),
    frozenset({"weird", "facts", "факт", "факты"}),
)

ALIGN_THRESHOLD = 0.34
_BROAD_THEME_TOKENS = frozenset(
    {
        "meme",
        "memes",
        "мем",
        "мемы",
        "then",
        "now",
        "vs",
        "what",
        "if",
        "что",
        "если",
        "video",
        "edit",
        "song",
    },
)


@dataclass(frozen=True, slots=True)
class TopicQuerySuggestionItem:
    query: str
    source_type: SourceType
    source_explanation: str
    supporting_video_count: int | None = None


@dataclass(frozen=True, slots=True)
class TopicSearchDirection:
    direction_id: str
    label: str
    explanation: str
    suggestions: tuple[TopicQuerySuggestionItem, ...] = ()


@dataclass(frozen=True, slots=True)
class FamilyTopicQueryPlan:
    mode: SuggestionMode
    message: str | None
    suggestions: tuple[TopicQuerySuggestionItem, ...]
    directions: tuple[TopicSearchDirection, ...] = ()
    mixed_keyword_provenance: bool = False
    anchor_label: str = ""


def _looks_like_bare_id(text: str) -> bool:
    stripped = text.strip()
    if not stripped or _ID_LIKE.match(stripped) or _PATTERN_KEY.match(stripped) or stripped.isdigit():
        return True
    return False


def _expand_tokens(tokens: set[str]) -> set[str]:
    out = set(tokens)
    for group in _BILINGUAL_GROUPS:
        if tokens & group:
            out |= group
    return out


def _token_set(text: str) -> set[str]:
    return set(significant_tokens(text))


def _alignment_score(a: str, b: str) -> float:
    ta = _expand_tokens(_token_set(a))
    tb = _expand_tokens(_token_set(b))
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return inter / min(len(ta), len(tb))


def _anchor_specific_tokens(anchor: str) -> set[str]:
    raw = set(_token_set(anchor))
    specific = {t for t in raw if t not in _BROAD_THEME_TOKENS}
    return specific if specific else raw


def _keyword_allowed_for_anchor(keyword: str, anchor: str) -> bool:
    if _MUSIC_OR_OFFTOPIC.search(keyword):
        return False
    if re.search(r"\bsong\b", keyword, re.I) and not _MUSIC_ANCHOR.search(anchor):
        return False
    return True


def _labels_align(a: str, b: str) -> bool:
    """Symmetric label similarity (patterns / directions)."""
    if not a.strip() or not b.strip():
        return False
    if a.casefold() in b.casefold() or b.casefold() in a.casefold():
        return True
    return _alignment_score(a, b) >= ALIGN_THRESHOLD


def keyword_aligns_to_family_anchor(keyword: str, anchor: str) -> bool:
    """Keyword text is usable as the same search direction as the family anchor."""
    if not keyword.strip() or not anchor.strip():
        return False
    if not _keyword_allowed_for_anchor(keyword, anchor):
        return False
    if keyword.casefold() == anchor.casefold() or keyword.casefold() in anchor.casefold():
        return True
    if anchor.casefold() in keyword.casefold():
        return True
    kt = _expand_tokens(_token_set(keyword))
    at = _expand_tokens(_token_set(anchor))
    specific = _anchor_specific_tokens(anchor)
    if specific and (specific & kt):
        return True
    meme_group = frozenset({"meme", "memes", "мем", "мемы"})
    time_group = frozenset({"then", "now", "тогда", "сейчас"})
    if (kt & meme_group) and (at & meme_group) and (kt & time_group) and (at & time_group):
        if re.search(r"\b(edit|remix|mix)\b", keyword, re.I):
            return False
        extra = kt - at - meme_group - time_group - _BROAD_THEME_TOKENS
        if extra:
            return False
        return True
    return _alignment_score(keyword, anchor) >= ALIGN_THRESHOLD and (not specific or bool(specific & kt))


def _family_video_count(frozen: dict[str, Any]) -> int:
    family = frozen.get("family") if isinstance(frozen.get("family"), dict) else {}
    count = family.get("video_count")
    if isinstance(count, int) and count > 0:
        return count
    vids = frozen.get("video_ids")
    if isinstance(vids, list):
        return len(vids)
    members = frozen.get("member_patterns")
    if isinstance(members, list) and members:
        first = members[0]
        if isinstance(first, dict):
            vc = first.get("video_count")
            if isinstance(vc, int):
                return vc
    return 0


def _member_pattern_labels(frozen: dict[str, Any]) -> list[tuple[str, int]]:
    rows: list[tuple[str, int]] = []
    members = frozen.get("member_patterns")
    if not isinstance(members, list):
        return rows
    for row in members:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "").strip()
        if not label or _looks_like_bare_id(label):
            continue
        vc = int(row.get("video_count") or 0)
        rows.append((label, vc))
    return rows


def _repeated_title_phrases(frozen: dict[str, Any], *, anchor: str, cap: int) -> list[tuple[str, int]]:
    evidence = frozen.get("breakout_video_evidence")
    if not isinstance(evidence, list):
        return []
    titles = [str(row.get("title") or "") for row in evidence if isinstance(row, dict)]
    titles = [t for t in titles if len(t.strip()) >= 12]
    if len(titles) < 3:
        return []
    min_hits = max(3, int(len(titles) * 0.25))
    counts: Counter[str] = Counter()
    anchor_tokens = _expand_tokens(_token_set(anchor))
    for title in titles:
        for phrase in title_ngrams(title, min_n=3, max_n=5):
            if len(phrase) < 10:
                continue
            pt = _expand_tokens(_token_set(phrase))
            if anchor_tokens and not (pt & anchor_tokens):
                continue
            counts[phrase] += 1
    ranked = [(p, c) for p, c in counts.most_common() if c >= min_hits and not _looks_like_bare_id(p)]
    return ranked[:cap]


def _cluster_keyword_texts(
    keyword_pairs: list[tuple[int, str]],
    *,
    anchor: str,
) -> tuple[list[tuple[int, str]], list[list[tuple[int, str]]]]:
    """Return (aligned_to_anchor, other_clusters)."""
    aligned: list[tuple[int, str]] = []
    other: list[tuple[int, str]] = []
    for kid, text in keyword_pairs:
        if keyword_aligns_to_family_anchor(text, anchor):
            aligned.append((kid, text))
        else:
            other.append((kid, text))

    # Sub-cluster unrelated keywords by mutual alignment (simple greedy).
    clusters: list[list[tuple[int, str]]] = []
    for kid, text in other:
        placed = False
        for cluster in clusters:
            if any(_labels_align(text, c[1]) for c in cluster):
                cluster.append((kid, text))
                placed = True
                break
        if not placed:
            clusters.append([(kid, text)])
    clusters = [c for c in clusters if len(c) >= 1]
    return aligned, clusters


def _suggestions_from_anchor(
    *,
    anchor: str,
    aligned_keywords: list[tuple[int, str]],
    frozen: dict[str, Any],
    cap: int,
) -> list[TopicQuerySuggestionItem]:
    seen: set[str] = set()
    items: list[TopicQuerySuggestionItem] = []
    family_videos = _family_video_count(frozen)

    def add(query: str, source_type: SourceType, explanation: str, support: int | None = None) -> None:
        if len(items) >= cap:
            return
        text = " ".join(normalize_title(query).split())
        if len(text) < 3 or _looks_like_bare_id(text):
            return
        key = text.casefold()
        if key in seen:
            return
        seen.add(key)
        items.append(
            TopicQuerySuggestionItem(
                query=text[:120],
                source_type=source_type,
                source_explanation=explanation,
                supporting_video_count=support,
            ),
        )

    add(
        anchor,
        "family_label",
        f"Название сохранённой темы (в Attention у семьи {family_videos} видео).",
        family_videos or None,
    )

    aligned_sorted = sorted(
        aligned_keywords,
        key=lambda row: (-_alignment_score(row[1], anchor), row[1].casefold()),
    )
    for _kid, kw in aligned_sorted:
        if keyword_aligns_to_family_anchor(kw, anchor) and kw.casefold() != anchor.casefold():
            add(
                kw,
                "aligned_keyword",
                "Ключевое слово той же тематической группы, что и название темы (shared keyword provenance).",
                None,
            )

    for phrase, hits in _repeated_title_phrases(frozen, anchor=anchor, cap=2):
        add(
            phrase,
            "shared_title_phrase",
            f"Повторяющаяся фраза в заголовках видео семьи в Attention (≈{hits} роликов).",
            hits,
        )

    return items[:cap]


def _direction_from_cluster(
    direction_id: str,
    label: str,
    explanation: str,
    keywords: list[tuple[int, str]],
    *,
    frozen: dict[str, Any],
    cap: int,
) -> TopicSearchDirection:
    anchor = label
    if keywords:
        anchor = max((t for _, t in keywords), key=lambda t: len(t))
    suggestions = _suggestions_from_anchor(
        anchor=anchor,
        aligned_keywords=keywords,
        frozen=frozen,
        cap=cap,
    )
    return TopicSearchDirection(
        direction_id=direction_id,
        label=label,
        explanation=explanation,
        suggestions=tuple(suggestions),
    )


def build_family_topic_query_plan(
    *,
    frozen_label: str,
    frozen_payload: dict[str, Any] | None,
    keyword_texts_by_id: dict[int, str] | None = None,
) -> FamilyTopicQueryPlan:
    """
    Build editable query suggestions expressing one coherent search direction.
    Does not emit one query per member_pattern; does not pad to max_queries.
    """
    cfg = saved_video_similar_watch_settings
    cap = cfg.max_queries_per_watch
    frozen = frozen_payload or {}
    keyword_by_id = keyword_texts_by_id or {}

    raw_ids = frozen.get("keyword_ids")
    id_order: list[int] = []
    if isinstance(raw_ids, list):
        for item in raw_ids:
            try:
                id_order.append(int(item))
            except (TypeError, ValueError):
                continue
    keyword_pairs = [(kid, keyword_by_id[kid]) for kid in id_order if kid in keyword_by_id and keyword_by_id[kid].strip()]

    members = _member_pattern_labels(frozen)
    anchor = (frozen_label or "").strip()
    if not anchor and members:
        anchor = max(members, key=lambda row: row[1])[0]
    family = frozen.get("family") if isinstance(frozen.get("family"), dict) else {}
    if not anchor:
        anchor = str(family.get("label") or "").strip()

    # Multiple member patterns with different subjects → pick a direction, not N pattern queries.
    if len(members) >= 2:
        roots = [m[0] for m in members]
        cohesive = all(_labels_align(roots[0], other) for other in roots[1:])
        if not cohesive:
            directions: list[TopicSearchDirection] = []
            for idx, (label, vc) in enumerate(members):
                pat_keywords: list[tuple[int, str]] = []
                # Keywords cannot be mapped per pattern in frozen v1 without pattern keys; use whole list alignment.
                aligned, _other = _cluster_keyword_texts(keyword_pairs, anchor=label)
                pat_keywords = aligned
                directions.append(
                    _direction_from_cluster(
                        f"pattern_{idx}",
                        label,
                        f"Отдельный паттерн в семье ({vc} видео в Attention). Выберите одно направление.",
                        pat_keywords,
                        frozen=frozen,
                        cap=cap,
                    ),
                )
            return FamilyTopicQueryPlan(
                mode="heterogeneous",
                message=(
                    "Тема объединяет несколько разных паттернов. Выберите одно направление поиска "
                    "или задайте 1–5 запросов вручную."
                ),
                suggestions=(),
                directions=tuple(directions),
                mixed_keyword_provenance=len(keyword_pairs) > len(members),
                anchor_label=anchor,
            )

    if not anchor:
        return FamilyTopicQueryPlan(
            mode="manual",
            message="Тема слишком разнородна для автоматического поиска — задайте 1–5 запросов вручную.",
            suggestions=(),
            anchor_label="",
        )

    aligned, other_clusters = _cluster_keyword_texts(keyword_pairs, anchor=anchor)
    mixed = bool(other_clusters and aligned and sum(len(c) for c in other_clusters) >= 2)

    # No thematic overlap among keywords and label too generic.
    if not aligned and other_clusters:
        if len(other_clusters) >= 2:
            directions = []
            for idx, cluster in enumerate(other_clusters):
                sample = cluster[0][1]
                directions.append(
                    _direction_from_cluster(
                        f"cluster_{idx}",
                        sample[:80],
                        "Группа ключевых слов без общего предмета с названием темы.",
                        cluster,
                        frozen=frozen,
                        cap=cap,
                    ),
                )
            return FamilyTopicQueryPlan(
                mode="heterogeneous",
                message=(
                    "Тема слишком разнородна для автоматического поиска. "
                    "Выберите одно направление или задайте 1–5 запросов вручную."
                ),
                suggestions=(),
                directions=tuple(directions),
                mixed_keyword_provenance=True,
                anchor_label=anchor,
            )
        # Single unrelated cluster only — manual
        return FamilyTopicQueryPlan(
            mode="manual",
            message=(
                "Ключевые слова в Attention не совпадают с названием темы. "
                "Задайте 1–5 запросов вручную."
            ),
            suggestions=(),
            mixed_keyword_provenance=True,
            anchor_label=anchor,
        )

    suggestions = _suggestions_from_anchor(
        anchor=anchor,
        aligned_keywords=aligned,
        frozen=frozen,
        cap=cap,
    )

    directions: list[TopicSearchDirection] = []
    if mixed:
        primary = _direction_from_cluster(
            "primary",
            anchor,
            "Запросы вокруг названия темы и близких ключевых слов.",
            aligned,
            frozen=frozen,
            cap=cap,
        )
        directions.append(primary)
        for idx, cluster in enumerate(other_clusters):
            if len(cluster) < 2:
                continue
            label = cluster[0][1][:80]
            directions.append(
                _direction_from_cluster(
                    f"other_{idx}",
                    label,
                    "Другая группа ключевых слов из той же Attention-семьи (не смешивайте с основным направлением).",
                    cluster,
                    frozen=frozen,
                    cap=cap,
                ),
            )
        message = (
            "В Attention к теме привязаны разные группы ключевых слов. "
            "Выберите одно направление или отредактируйте набор запросов — "
            "не объединяйте, например, мемы, Reddit и музыку в одну выдачу."
        )
        if not suggestions:
            mode: SuggestionMode = "heterogeneous"
        else:
            mode = "auto"
        return FamilyTopicQueryPlan(
            mode=mode,
            message=message,
            suggestions=tuple(suggestions),
            directions=tuple(directions),
            mixed_keyword_provenance=True,
            anchor_label=anchor,
        )

    if not suggestions:
        return FamilyTopicQueryPlan(
            mode="manual",
            message="Тема слишком разнородна для автоматического поиска — задайте 1–5 запросов вручную.",
            suggestions=(),
            anchor_label=anchor,
        )

    return FamilyTopicQueryPlan(
        mode="auto",
        message=None,
        suggestions=tuple(suggestions),
        directions=(),
        mixed_keyword_provenance=False,
        anchor_label=anchor,
    )


def labels_align(a: str, b: str) -> bool:
    return _labels_align(a, b)


def plan_to_json_dict(plan: FamilyTopicQueryPlan) -> dict[str, Any]:
    return {
        "mode": plan.mode,
        "message": plan.message,
        "mixed_keyword_provenance": plan.mixed_keyword_provenance,
        "anchor_label": plan.anchor_label,
        "suggestions": [
            {
                "query": s.query,
                "source_type": s.source_type,
                "source_explanation": s.source_explanation,
                "supporting_video_count": s.supporting_video_count,
            }
            for s in plan.suggestions
        ],
        "directions": [
            {
                "direction_id": d.direction_id,
                "label": d.label,
                "explanation": d.explanation,
                "suggestions": [
                    {
                        "query": s.query,
                        "source_type": s.source_type,
                        "source_explanation": s.source_explanation,
                        "supporting_video_count": s.supporting_video_count,
                    }
                    for s in d.suggestions
                ],
            }
            for d in plan.directions
        ],
    }
