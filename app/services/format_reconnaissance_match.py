"""Metadata-only heuristics for format recon (no content analysis)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from app.services.attention_title_normalization import normalize_title

MatchTier = Literal["strong", "partial", "weak", "unlikely"]

_DURATION_RE = re.compile(
    r"(?:(\d+)\s*h(?:ours?)?)?\s*(?:(\d+)\s*m(?:in(?:ute)?s?)?)?",
    re.I,
)


@dataclass(frozen=True, slots=True)
class FormatMatchAssessment:
    tier: MatchTier
    score: int
    reasons: tuple[str, ...]
    manual_checks: tuple[str, ...] = ()


def parse_duration_seconds(duration_text: str | None, duration_seconds: int | None) -> int | None:
    if duration_seconds is not None and duration_seconds > 0:
        return duration_seconds
    if not duration_text:
        return None
    text = duration_text.strip().lower()
    if text in {"live", "upcoming"}:
        return None
    parts = text.split(":")
    try:
        if len(parts) == 3:
            h, m, s = (int(p) for p in parts)
            return h * 3600 + m * 60 + s
        if len(parts) == 2:
            m, s = (int(p) for p in parts)
            return m * 60 + s
        if len(parts) == 1 and parts[0].isdigit():
            return int(parts[0])
    except ValueError:
        pass
    m = _DURATION_RE.search(text)
    if m:
        hours = int(m.group(1) or 0)
        mins = int(m.group(2) or 0)
        total = hours * 3600 + mins * 60
        return total if total > 0 else None
    return None


def assess_publication_against_hypothesis(
    *,
    title: str,
    duration_text: str = "",
    duration_seconds: int | None = None,
    kind: str = "unknown",
    format_description: str = "",
) -> FormatMatchAssessment:
    """
    Score using title tokens + duration + kind only.
    Never infers static images, voiceover, monetization, or on-camera host.
    """
    reasons: list[str] = []
    manual: list[str] = [
        "Озвучка и статичные кадры не определяются без просмотра",
        "Ведущий в кадре не определяется по метаданным",
    ]
    norm = normalize_title(title)
    score = 0

    sleep_hit = any(k in norm for k in ("sleep", "bedtime", "insomnia", "fall asleep", "сон", "засып"))
    history_hit = any(
        k in norm for k in ("history", "historical", "ancient", "medieval", "empire", "war", "истор", "древн")
    )
    calm_hit = any(k in norm for k in ("calm", "relax", "peaceful", "quiet", "спокой"))
    story_hit = any(k in norm for k in ("story", "stories", "tale", "рассказ", "сказ"))
    doc_hit = "documentary" in norm or "документ" in norm

    dur = parse_duration_seconds(duration_text, duration_seconds)
    if kind == "short" or (dur is not None and dur < 120):
        return FormatMatchAssessment(
            tier="unlikely",
            score=0,
            reasons=("Короткий формат / Short по доступным данным",),
            manual_checks=tuple(manual),
        )

    if sleep_hit:
        score += 25
        reasons.append("В названии есть sleep/bedtime-тематика")
    if history_hit:
        score += 25
        reasons.append("В названии есть history/historical-тематика")
    if calm_hit:
        score += 10
        reasons.append("В названии есть calm/relax")
    if story_hit or doc_hit:
        score += 10
        reasons.append("Story/documentary в названии")

    if dur is not None:
        if dur >= 3600:
            score += 30
            reasons.append(f"Длительность ≥1 ч ({duration_text or dur}s)")
        elif dur >= 1200:
            score += 15
            reasons.append(f"Длительность ≥20 мин ({duration_text or dur}s)")
        elif dur >= 600:
            score += 5
            reasons.append(f"Средняя длительность ({duration_text or dur}s)")
        else:
            score -= 10
            reasons.append("Относительно короткая длительность для «длинного» формата")

    if "short" in norm or "#shorts" in title.lower():
        score -= 20
        reasons.append("Shorts-маркер в названии")

    if format_description and "histor" in normalize_title(format_description) and not history_hit:
        manual.append("Историческая тема в гипотезе, но слабо видна в названии")

    if score >= 55:
        tier: MatchTier = "strong"
    elif score >= 35:
        tier = "partial"
    elif score >= 15:
        tier = "weak"
    else:
        tier = "unlikely"

    return FormatMatchAssessment(
        tier=tier,
        score=max(0, min(100, score)),
        reasons=tuple(reasons) if reasons else ("Слабое совпадение по метаданным",),
        manual_checks=tuple(manual),
    )
