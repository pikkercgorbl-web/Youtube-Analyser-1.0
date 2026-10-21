"""Format recon heuristics (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.format_reconnaissance_match import assess_publication_against_hypothesis
from app.services.format_reconnaissance_query_suggest import suggest_format_search_directions


def test_suggest_directions_sleep_history():
    dirs = suggest_format_search_directions(
        format_description="Long calm historical stories for sleep, voiceover slideshow",
    )
    assert 2 <= len(dirs) <= 3
    joined = " ".join(d.query.casefold() for d in dirs)
    assert "history" in joined or "sleep" in joined


def test_assess_long_history_title():
    a = assess_publication_against_hypothesis(
        title="The Entire History of Rome — Bedtime Documentary for Sleep",
        duration_text="2:15:00",
        duration_seconds=8100,
        kind="regular",
        format_description="historical sleep stories",
    )
    assert a.tier in ("strong", "partial")
    assert "озвучка" not in " ".join(a.reasons).casefold()


def main() -> None:
    test_suggest_directions_sleep_history()
    test_assess_long_history_title()
    print("test_format_reconnaissance_match: OK")


if __name__ == "__main__":
    main()
