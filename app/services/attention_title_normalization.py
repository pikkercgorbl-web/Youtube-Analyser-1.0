"""Deterministic title normalization for Pattern v1 (Stage 1.22A).

Rules:
- casefold
- replace ``&`` with ``and``
- strip punctuation except word characters and spaces
- collapse whitespace
- drop 1–2 digit numeric tokens (episode-style noise)
- drop a conservative stopword list (EN/RU filler)
- keep 4-digit years and tokens like ``gta5`` / ``2k``

Does not stem, lemmatize, translate, or embed.
Prefers false negatives over aggressive merging.
"""

from __future__ import annotations

import hashlib
import re

_PUNCT = re.compile(r"[^\w\s]+", re.UNICODE)
_WS = re.compile(r"\s+")
_SHORT_NUMERIC = re.compile(r"^\d{1,2}$")

STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "the",
        "to",
        "of",
        "in",
        "on",
        "for",
        "with",
        "vs",
        "versus",
        "official",
        "video",
        "full",
        "new",
        "how",
        "you",
        "your",
        "my",
        "me",
        "i",
        "is",
        "this",
        "that",
        "it",
        "at",
        "from",
        "by",
        "or",
        "be",
        "are",
        "was",
        "и",
        "в",
        "на",
        "с",
        "для",
        "как",
        "это",
        "что",
        "по",
        "из",
        "не",
        "за",
        "от",
        "о",
        "об",
        "же",
        "ли",
    },
)


def normalize_title(title: str) -> str:
    text = (title or "").casefold().replace("&", " and ")
    text = _PUNCT.sub(" ", text)
    text = _WS.sub(" ", text).strip()
    return text


def significant_tokens(title: str) -> tuple[str, ...]:
    normalized = normalize_title(title)
    tokens: list[str] = []
    for token in normalized.split():
        if token in STOPWORDS:
            continue
        if _SHORT_NUMERIC.fullmatch(token):
            continue
        if len(token) < 2:
            continue
        tokens.append(token)
    return tuple(tokens)


def title_ngrams(title: str, *, min_n: int = 2, max_n: int = 4) -> tuple[str, ...]:
    tokens = significant_tokens(title)
    if len(tokens) < min_n:
        return ()
    phrases: list[str] = []
    seen: set[str] = set()
    upper = min(max_n, len(tokens))
    for n in range(min_n, upper + 1):
        for start in range(0, len(tokens) - n + 1):
            phrase = " ".join(tokens[start : start + n])
            if phrase not in seen:
                seen.add(phrase)
                phrases.append(phrase)
    return tuple(phrases)


def phrase_pattern_key(phrase: str) -> str:
    digest = hashlib.sha256(phrase.encode("utf-8")).hexdigest()[:16]
    return f"phrase:{digest}"


def keyword_pattern_key(keyword_id: int) -> str:
    return f"kw:{int(keyword_id)}"


def topic_pattern_key(topic: str) -> str:
    normalized = normalize_title(topic)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"topic:{digest}"
