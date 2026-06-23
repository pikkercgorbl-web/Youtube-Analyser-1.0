"""Round-robin YouTube API key manager with quota failover."""

from __future__ import annotations


class YouTubeApiKeyError(RuntimeError):
    """Raised when no valid API keys are configured."""


class YouTubeApiKeyManager:
    """Distributes requests across multiple API keys and rotates on quota errors."""

    def __init__(self, api_keys: list[str]) -> None:
        cleaned = [key.strip() for key in api_keys if key.strip()]
        if not cleaned:
            msg = "No YouTube API keys configured"
            raise YouTubeApiKeyError(msg)
        self._keys = cleaned
        self._index = 0

    @property
    def key_count(self) -> int:
        return len(self._keys)

    def current_key(self) -> str:
        return self._keys[self._index]

    def rotate(self) -> str:
        """Switch to the next key after a quota or key-related API error."""
        self._index = (self._index + 1) % len(self._keys)
        return self.current_key()

    def all_keys(self) -> list[str]:
        return list(self._keys)
