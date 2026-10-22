"""Editable search directions from a user format hypothesis (no LLM, no SavedFamily)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.attention_title_normalization import normalize_title, significant_tokens

_MAX_DIRECTIONS = 3


@dataclass(frozen=True, slots=True)
class FormatSearchDirection:
    query: str
    rationale: str


_SLEEP = frozenset({"sleep", "bedtime", "insomnia", "asmr", "сон", "сна", "засып", "ноч"})
_HISTORY = frozenset(
    {"history", "historical", "ancient", "medieval", "war", "empire", "documentary", "истор", "древн", "средневек"},
)
_CALM = frozenset({"calm", "relax", "quiet", "peaceful", "спокой", "relaxing", "meditation"})
_STORY = frozenset({"story", "stories", "tale", "tales", "narrat", "истори", "рассказ", "сказ"})
_LONG_HINT = frozenset({"long", "hour", "hours", "full", "длинн", "час", "лекци"})


def _has_any(text: str, group: frozenset[str]) -> bool:
    norm = normalize_title(text)
    return any(token in norm for token in group) or any(g in norm for g in group if len(g) > 4)


def suggest_format_search_directions(
    *,
    format_description: str,
    example_video_title: str | None = None,
) -> list[FormatSearchDirection]:
    """
    Return 2–3 editable query strings describing topic + discoverable format cues in titles.
    Does not read SavedFamily or keyword provenance.
    """
    desc = (format_description or "").strip()
    if not desc:
        return []

    seen: set[str] = set()
    out: list[FormatSearchDirection] = []

    def add(query: str, rationale: str) -> None:
        if len(out) >= _MAX_DIRECTIONS:
            return
        q = " ".join(normalize_title(query).split())
        if len(q) < 4:
            return
        key = q.casefold()
        if key in seen:
            return
        seen.add(key)
        out.append(FormatSearchDirection(query=q[:120], rationale=rationale))

    wants_sleep = _has_any(desc, _SLEEP)
    wants_history = _has_any(desc, _HISTORY)
    wants_calm = _has_any(desc, _CALM)
    wants_story = _has_any(desc, _STORY)
    wants_long = _has_any(desc, _LONG_HINT)

    if wants_history and wants_sleep:
        add(
            "history documentary for sleep",
            "История + засыпание — типичная формулировка в названиях длинных «sleep history» роликов.",
        )
        add(
            "historical bedtime stories long",
            "Сочетает исторический сюжет и «bedtime» в выдаче.",
        )
    elif wants_history:
        add("long form history documentary", "Фокус на истории без привязки к sleep-токенам.")
        add("history stories documentary full", "Запасной вариант для полнометражных историй.")
    elif wants_sleep:
        add("long bedtime stories for sleep", "Общий sleep-формат в названиях.")
        add("calm stories for sleep", "Спокойный story-формат.")

    if wants_calm and wants_story and len(out) < _MAX_DIRECTIONS:
        add(
            "calm historical stories narrated",
            "«Calm» + «stories» в названии; не проверяет озвучку или статичные кадры.",
        )

    if example_video_title and len(out) < _MAX_DIRECTIONS:
        tokens = significant_tokens(example_video_title)
        if len(tokens) >= 3:
            phrase = " ".join(tokens[: min(6, len(tokens))])
            add(
                phrase,
                "Фраза из названия примера видео (пользовательский ориентир).",
            )

    if len(out) < 2:
        # Fallback: compress user description into one searchable phrase.
        tokens = significant_tokens(desc)
        if tokens:
            add(" ".join(tokens[:8]), "Сжатие вашего описания формата (без автоматических keywords).")
        if len(tokens) > 4 and len(out) < 2:
            add(" ".join(tokens[:5]), "Укороченный вариант описания.")

    return out[:_MAX_DIRECTIONS]
