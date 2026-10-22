"""Strict parsing for selected environment flags (no service imports)."""

from __future__ import annotations

_TRUTHY_PRIORITY_FLAGS = frozenset({"1", "true", "yes", "on"})
_FALSY_PRIORITY_FLAGS = frozenset({"0", "false", "no", "off"})


def parse_outcome_capture_di_winner_priority_value(value: object) -> bool:
    """Parse OUTCOME_CAPTURE_DI_WINNER_PRIORITY; missing/empty → OFF; malformed → error."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if not isinstance(value, str):
        raise ValueError(
            "OUTCOME_CAPTURE_DI_WINNER_PRIORITY must be 0/1/true/false/yes/no/on/off"
        )
    token = value.strip().lower()
    if not token:
        return False
    if token in _TRUTHY_PRIORITY_FLAGS:
        return True
    if token in _FALSY_PRIORITY_FLAGS:
        return False
    raise ValueError(
        f"OUTCOME_CAPTURE_DI_WINNER_PRIORITY must be 0/1/true/false/yes/no/on/off, got {value!r}"
    )
