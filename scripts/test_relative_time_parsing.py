"""Smoke tests for parse_relative_time_to_days."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.explosive_channels_service import reject_upload_date_text
from app.services.video_filter_service import parse_relative_time_to_days


def main() -> None:
    cases = [
        ("3 года назад", 1095),
        ("3 года", 1095),
        ("6 месяцев назад", 180),
        ("6 months ago", 180),
        ("2 weeks ago", 14),
        ("1 year ago", 365),
        ("5 days ago", 5),
        ("только что", 0),
        ("", -1),
    ]

    failed = 0
    for text, expected in cases:
        actual = parse_relative_time_to_days(text)
        if actual != expected:
            failed += 1
            print(f"FAIL parse_relative_time_to_days({text!r}) -> {actual}, expected {expected}")

    if reject_upload_date_text("3 года назад", "6_months"):
        print("OK: 3 года отклонено при лимите 6 месяцев")
    else:
        failed += 1
        print("FAIL: 3 года должно отклоняться при 6_months")

    if not reject_upload_date_text("2 months ago", "6_months"):
        print("OK: 2 months проходит при лимите 6 месяцев")
    else:
        failed += 1
        print("FAIL: 2 months не должно отклоняться при 6_months")

    if reject_upload_date_text("", "6_months", video_title="Short без даты"):
        print("OK: пустая дата отклоняется при строгом фильтре")
    else:
        failed += 1
        print("FAIL: пустая дата должна отклоняться при 6_months")

    if failed:
        print(f"\n{failed} test(s) failed")
        sys.exit(1)

    print(f"All {len(cases) + 3} relative time checks passed")


if __name__ == "__main__":
    main()
