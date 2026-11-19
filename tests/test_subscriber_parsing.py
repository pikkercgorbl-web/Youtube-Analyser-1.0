"""Smoke tests for parse_subscriber_count."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.youtube.client import parse_subscriber_count, parse_subscriber_count_text


def main() -> None:
    cases = [
        ("1,5 млн подписчиков", 1_500_000),
        ("1.5M subscribers", 1_500_000),
        ("234K", 234_000),
        ("234k subscribers", 234_000),
        ("10 тыс.", 10_000),
        ("850", 850),
        ("5.09M subscribers", 5_090_000),
        ("1,508,234 subscribers", 1_508_234),
        ("1 500 000 подписчиков", 1_500_000),
        ("Subscribers hidden", 0),
        ("Подписчики скрыты", 0),
        ("No subscribers", 0),
        ("", 0),
    ]

    failed = 0
    for text, expected in cases:
        actual = parse_subscriber_count(text)
        if actual != expected:
            failed += 1
            print(f"FAIL parse_subscriber_count({text!r}) -> {actual}, expected {expected}")

    hidden = parse_subscriber_count_text("Subscribers hidden")
    if hidden is not None:
        failed += 1
        print(f"FAIL parse_subscriber_count_text hidden -> {hidden}, expected None")

    zero = parse_subscriber_count_text("No subscribers")
    if zero != 0:
        failed += 1
        print(f"FAIL parse_subscriber_count_text zero -> {zero}, expected 0")

    parsed = parse_subscriber_count_text("1,5 млн подписчиков")
    if parsed != 1_500_000:
        failed += 1
        print(f"FAIL parse_subscriber_count_text 1.5M -> {parsed}, expected 1500000")

    if failed:
        print(f"\n{failed} test(s) failed")
        sys.exit(1)

    print(f"All {len(cases) + 3} subscriber parsing checks passed")


if __name__ == "__main__":
    main()
