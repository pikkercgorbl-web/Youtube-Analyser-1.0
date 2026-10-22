"""Tests for frozen winner reason_summary (Daily Intelligence list)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.daily_intelligence_winner_reason_summary import (
    REASON_MISSING,
    SUMMARY_ABOVE_CHANNEL,
    SUMMARY_ACCELERATING,
    SUMMARY_CONFIRMED_72H,
    SUMMARY_FROM_REPORT,
    SUMMARY_HIGH_VPH,
    SUMMARY_TOP_IN_WINDOW,
    winner_reason_summary_from_evidence,
)


def test_high_current_vph() -> None:
    assert (
        winner_reason_summary_from_evidence(
            {"reason_codes": ["high_current_vph"], "vph": 120.0},
        )
        == SUMMARY_HIGH_VPH
    )


def test_breakout_high_rank_plain_language() -> None:
    text = winner_reason_summary_from_evidence(
        {"reason_codes": ["breakout_high_rank"], "breakout_rank": 2},
    )
    assert text == SUMMARY_TOP_IN_WINDOW
    assert "breakout" not in text.lower()


def test_accelerating() -> None:
    assert (
        winner_reason_summary_from_evidence({"reason_codes": ["accelerating_velocity"]})
        == SUMMARY_ACCELERATING
    )


def test_confirmed_72h() -> None:
    assert (
        winner_reason_summary_from_evidence({"reason_codes": ["confirmed_72h_growth"]})
        == SUMMARY_CONFIRMED_72H
    )


def test_channel_relative() -> None:
    text = winner_reason_summary_from_evidence(
        {
            "reason_codes": ["channel_relative_outlier"],
            "channel_relative_signal": {"baseline_quality": "production_ready"},
        },
    )
    assert text == SUMMARY_ABOVE_CHANNEL
    assert "production" not in text.lower()


def test_missing_evidence() -> None:
    assert winner_reason_summary_from_evidence({}) == REASON_MISSING
    assert winner_reason_summary_from_evidence(None) == REASON_MISSING


def test_no_raw_codes_in_output() -> None:
    text = winner_reason_summary_from_evidence({"reason_codes": ["unknown_code_xyz"]})
    assert "unknown_code" not in text
    assert text == REASON_MISSING


def test_internal_human_reason_sanitized() -> None:
    text = winner_reason_summary_from_evidence(
        {"human_reasons": ["breakout_v1 rank 3 in this attention window"]},
    )
    assert "breakout" not in text.lower()
    assert text == SUMMARY_TOP_IN_WINDOW


def test_english_human_fallback() -> None:
    text = winner_reason_summary_from_evidence(
        {"human_reasons": ["Some custom analyst note without blocked tokens"]},
    )
    assert "Some custom analyst note" in text


def main() -> None:
    test_high_current_vph()
    test_breakout_high_rank_plain_language()
    test_accelerating()
    test_confirmed_72h()
    test_channel_relative()
    test_missing_evidence()
    test_no_raw_codes_in_output()
    test_internal_human_reason_sanitized()
    test_english_human_fallback()
    print("OK daily intelligence winner reason_summary tests")


if __name__ == "__main__":
    main()
