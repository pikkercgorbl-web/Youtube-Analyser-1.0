"""YouTube URL and channel reference parsing."""

from __future__ import annotations

import re
from enum import Enum
from urllib.parse import parse_qs, urlparse

_CHANNEL_ID_PATTERN = re.compile(r"^UC[\w-]{22}$")
_VIDEO_ID_PATTERN = re.compile(r"^[\w-]{11}$")
_CHANNEL_URL_PATTERN = re.compile(
    r"(?:youtube\.com|youtu\.be)/channel/(?P<id>UC[\w-]{22})",
    re.IGNORECASE,
)
_HANDLE_URL_PATTERN = re.compile(
    r"youtube\.com/@(?P<handle>[\w.-]+)",
    re.IGNORECASE,
)
_CUSTOM_URL_PATTERN = re.compile(
    r"youtube\.com/c/(?P<slug>[\w.-]+)",
    re.IGNORECASE,
)
_USER_URL_PATTERN = re.compile(
    r"youtube\.com/user/(?P<slug>[\w.-]+)",
    re.IGNORECASE,
)
_VIDEO_URL_PATTERNS = (
    re.compile(r"youtube\.com/watch\?", re.IGNORECASE),
    re.compile(r"youtu\.be/", re.IGNORECASE),
    re.compile(r"youtube\.com/shorts/", re.IGNORECASE),
    re.compile(r"youtube\.com/live/", re.IGNORECASE),
)
_CHANNEL_PATH_PATTERNS = (
    re.compile(r"youtube\.com/channel/", re.IGNORECASE),
    re.compile(r"youtube\.com/c/", re.IGNORECASE),
    re.compile(r"youtube\.com/@", re.IGNORECASE),
)


class YouTubeUrlKind(str, Enum):
    VIDEO = "video"
    CHANNEL = "channel"


def normalize_youtube_url(reference: str) -> str:
    """Ensure a reference has a scheme for URL parsing."""
    value = reference.strip()
    if not value:
        msg = "Empty YouTube URL"
        raise ValueError(msg)
    if "://" in value:
        return value
    if value.startswith("@"):
        return f"https://www.youtube.com/{value}"
    if _CHANNEL_ID_PATTERN.match(value):
        return f"https://www.youtube.com/channel/{value}"
    return f"https://{value}"


def classify_youtube_url(reference: str) -> tuple[YouTubeUrlKind, str]:
    """
    Detect whether a reference points to a video or a channel.

    Returns the kind and a lookup key:
    - video: 11-char video id
    - channel: channel id, handle slug, or normalized channel URL
    """
    value = reference.strip()
    if not value:
        msg = "Empty YouTube URL"
        raise ValueError(msg)

    if _CHANNEL_ID_PATTERN.match(value):
        return YouTubeUrlKind.CHANNEL, value

    if value.startswith("@"):
        return YouTubeUrlKind.CHANNEL, normalize_youtube_url(value)

    normalized = normalize_youtube_url(value)
    parsed = urlparse(normalized)
    host_path = f"{parsed.netloc}{parsed.path}".lower()
    query = parsed.query.lower()

    if any(pattern.search(host_path) or pattern.search(query) for pattern in _VIDEO_URL_PATTERNS):
        video_id = extract_video_id_from_url(normalized)
        if video_id:
            return YouTubeUrlKind.VIDEO, video_id
        msg = f"Cannot extract video id from URL: {reference!r}"
        raise ValueError(msg)

    if any(pattern.search(host_path) for pattern in _CHANNEL_PATH_PATTERNS):
        return YouTubeUrlKind.CHANNEL, normalized

    if _CHANNEL_ID_PATTERN.match(value):
        return YouTubeUrlKind.CHANNEL, value

    msg = f"Unsupported or invalid YouTube URL: {reference!r}"
    raise ValueError(msg)


def extract_video_id_from_url(reference: str) -> str | None:
    """Extract a YouTube video id from common video URL formats."""
    normalized = normalize_youtube_url(reference)
    parsed = urlparse(normalized)
    host_path = f"{parsed.netloc}{parsed.path}".lower()

    if "youtube.com/watch" in host_path:
        video_ids = parse_qs(parsed.query).get("v", [])
        if video_ids and _VIDEO_ID_PATTERN.match(video_ids[0]):
            return video_ids[0]

    for prefix in ("youtu.be/", "youtube.com/shorts/", "youtube.com/live/"):
        if prefix in host_path:
            slug = parsed.path.rstrip("/").split("/")[-1]
            if _VIDEO_ID_PATTERN.match(slug):
                return slug

    return None


def extract_channel_identifier(reference: str) -> str:
    """
    Extract a channel lookup key from free-form user input.

    Returns either:
    - a ``UC...`` channel id
    - an ``@handle`` string
    - a normalized channel page URL for ``/c/`` and ``/user/`` links
    """
    value = reference.strip()
    if not value:
        msg = "Empty channel reference"
        raise ValueError(msg)

    if _CHANNEL_ID_PATTERN.match(value):
        return value

    if value.startswith("@"):
        return value

    normalized = normalize_youtube_url(value)
    parsed = urlparse(normalized)
    path = parsed.path.rstrip("/")
    host_path = f"{parsed.netloc}{path}".lower()

    if _CHANNEL_URL_PATTERN.search(host_path):
        id_match = re.search(r"/channel/(UC[\w-]{22})", path, re.IGNORECASE)
        if id_match:
            return id_match.group(1)

    if match := _HANDLE_URL_PATTERN.search(host_path):
        return f"@{match.group('handle')}"

    if _CUSTOM_URL_PATTERN.search(host_path) or _USER_URL_PATTERN.search(host_path):
        return normalized

    msg = f"Cannot extract channel identifier from: {reference!r}"
    raise ValueError(msg)


def parse_youtube_channel_ref(reference: str) -> str:
    """
    Normalize a YouTube channel ID or URL to a lookup key.

    Supports:
    - Raw channel IDs (`UCxxxxxxxx`)
    - `/channel/UC...`, `/@handle`, `/c/name`, `/user/name` URLs
    - `@handle` strings

    `@handle` URLs are returned as `handle:<name>` for downstream lookup.
    """
    value = reference.strip()
    if value.startswith("handle:") or value.startswith("custom:"):
        return value

    identifier = extract_channel_identifier(reference)

    if _CHANNEL_ID_PATTERN.match(identifier):
        return identifier

    if identifier.startswith("@"):
        return f"handle:{identifier[1:]}"

    parsed = urlparse(identifier)
    host_path = f"{parsed.netloc}{parsed.path}".lower()
    if match := _CUSTOM_URL_PATTERN.search(host_path):
        return f"custom:{match.group('slug')}"
    if match := _USER_URL_PATTERN.search(host_path):
        return f"custom:{match.group('slug')}"

    return identifier


def is_handle_key(channel_key: str) -> bool:
    return channel_key.startswith("handle:")


def handle_from_key(channel_key: str) -> str:
    return channel_key.removeprefix("handle:")
