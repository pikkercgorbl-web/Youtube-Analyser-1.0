"""Deterministic search-query suggestions from a saved video title (no LLM)."""



from __future__ import annotations



import json

import re

from typing import Any



from app.services.attention_title_normalization import normalize_title, significant_tokens, title_ngrams

from app.services.saved_video_similar_relevance import (

    _strip_leading_count,

    query_meets_subject_bar,

    subject_tokens_from_title,

    build_anchor_profile,

)

from app.services.saved_video_similar_watch_config import saved_video_similar_watch_settings



_LEADING_NUM = re.compile(r"^\d+\s*")





def suggest_similar_search_queries(*, title: str, frozen_payload: dict[str, Any] | None = None) -> list[str]:

    """

    Return 1–5 editable query strings derived from title subject terms and stable phrases.

    Not AI recommendations — rule-based variants only. Does not pad with low-quality fragments.

    """

    cfg = saved_video_similar_watch_settings

    cap = cfg.max_queries_per_watch

    profile = build_anchor_profile(title=title, frozen_payload=frozen_payload)



    seen: set[str] = set()

    ordered: list[str] = []



    def add(raw: str) -> None:

        text = " ".join(normalize_title(raw).split())

        if len(text) < 3:

            return

        if not query_meets_subject_bar(text, profile):

            return

        key = text.casefold()

        if key in seen:

            return

        seen.add(key)

        ordered.append(text)



    stripped = _strip_leading_count(title)

    if stripped.strip():

        add(stripped.strip()[:120])



    subjects = profile.subject_tokens

    if len(subjects) >= 2:

        add(" ".join(subjects[: min(4, len(subjects))]))



    for phrase in profile.subject_phrases:

        add(phrase)

        if len(ordered) >= cap:

            break



    if len(ordered) < cap:

        tokens = significant_tokens(stripped)

        for phrase in title_ngrams(stripped, min_n=2, max_n=4):

            parts = phrase.split()

            if sum(1 for p in parts if p in set(subjects)) >= max(1, min(2, len(subjects))):

                add(phrase)

            if len(ordered) >= cap:

                break



    frozen = frozen_payload or {}

    ctx = frozen.get("context") if isinstance(frozen.get("context"), dict) else {}

    for kid_label in ctx.get("keyword_labels") or []:

        if isinstance(kid_label, str):

            add(kid_label)



    identity = frozen.get("identity") if isinstance(frozen.get("identity"), dict) else {}

    channel = str(identity.get("channel_title") or "").strip()
    channel_ok = (
        len(channel) >= 3
        and not channel.startswith("UC")
        and " " in channel
        and len(channel) <= 48
    )
    if subjects and channel_ok:
        add(f"{' '.join(subjects[:3])} {channel}")



    return ordered[:cap]





def parse_frozen_json(raw: str) -> dict[str, Any]:

    try:

        data = json.loads(raw or "{}")

    except json.JSONDecodeError:

        return {}

    return data if isinstance(data, dict) else {}


