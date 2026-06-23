"""Parse ISO 8601 duration strings returned by YouTube (e.g. PT4M13S)."""

from __future__ import annotations

import re

_ISO8601_DURATION = re.compile(
    r"^PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?$",
)


def parse_iso8601_duration(value: str) -> int:
    """Convert a YouTube ISO 8601 duration to total seconds."""
    match = _ISO8601_DURATION.match(value.strip())
    if not match:
        return 0
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    return hours * 3600 + minutes * 60 + seconds
