"""Shared FastAPI dependencies."""

from functools import lru_cache

from app.core.config import settings
from app.integrations.youtube.client import YouTubeApiClient
from app.integrations.youtube.key_manager import YouTubeApiKeyManager


@lru_cache
def get_youtube_client() -> YouTubeApiClient:
    key_manager = YouTubeApiKeyManager(settings.youtube_api_keys)
    return YouTubeApiClient(key_manager)
