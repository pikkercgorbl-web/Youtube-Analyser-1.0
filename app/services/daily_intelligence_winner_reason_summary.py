"""Short user-facing reason line from frozen winner evidence (Daily Intelligence list)."""

from __future__ import annotations

from typing import Any

REASON_MISSING = "Причина в отчёте не сохранена"

# User-visible one-liners (no internal codes / baseline tier names).
SUMMARY_HIGH_VPH = "Высокий темп просмотров в окне анализа"
SUMMARY_TOP_IN_WINDOW = "Сильный результат среди видео окна анализа"
SUMMARY_ACCELERATING = "Темп просмотров рос по серии снимков"
SUMMARY_CONFIRMED_72H = "Рост просмотров подтверждён через 72 часа"
SUMMARY_ABOVE_CHANNEL = "Сильнее обычных роликов канала на том же возрасте"
SUMMARY_FROM_REPORT = "Сигнал зафиксирован в сохранённом отчёте"


def winner_reason_summary_from_evidence(evidence: dict[str, Any] | None) -> str:
    """
    One-line summary from persisted payload_json only — no live Attention recompute.
    """
    if not evidence:
        return REASON_MISSING

    codes = {str(c) for c in (evidence.get("reason_codes") or [])}
    human = [str(h).strip() for h in (evidence.get("human_reasons") or []) if str(h).strip()]

    if "breakout_high_rank" in codes and evidence.get("breakout_rank") is not None:
        return SUMMARY_TOP_IN_WINDOW
    if "high_current_vph" in codes and evidence.get("vph") is not None:
        return SUMMARY_HIGH_VPH
    if "accelerating_velocity" in codes:
        return SUMMARY_ACCELERATING
    if "confirmed_72h_growth" in codes:
        return SUMMARY_CONFIRMED_72H
    if "channel_relative_outlier" in codes:
        rel = evidence.get("channel_relative_signal")
        if isinstance(rel, dict) and rel.get("baseline_quality") == "production_ready":
            return SUMMARY_ABOVE_CHANNEL

    if human:
        return _human_reason_summary(human[0])

    return REASON_MISSING


def _human_reason_summary(text: str) -> str:
    lower = text.lower()
    if "top quartile" in lower and "vph" in lower:
        return SUMMARY_HIGH_VPH
    if "rank" in lower and ("window" in lower or "attention" in lower or "breakout" in lower):
        return SUMMARY_TOP_IN_WINDOW
    if "2×" in text or "2x" in lower or "median" in lower:
        return SUMMARY_ABOVE_CHANNEL
    if "acceleration" in lower or "rose across" in lower or "views-per-hour" in lower:
        return SUMMARY_ACCELERATING
    if "72h" in lower or "72 h" in lower or "72-hour" in lower:
        return SUMMARY_CONFIRMED_72H
    if _looks_internal(text):
        return SUMMARY_FROM_REPORT
    if len(text) > 140:
        return text[:137] + "…"
    return text


def _looks_internal(text: str) -> bool:
    lower = text.lower()
    blocked = (
        "breakout",
        "production_ready",
        "diagnostic",
        "reason_code",
        "innertube",
        "eligible",
    )
    return any(token in lower for token in blocked)
