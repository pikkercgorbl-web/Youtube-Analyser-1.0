"""Generate YouTube video title ideas via Google Gemini."""

from __future__ import annotations

import json
import re

import google.generativeai as genai

from app.core.config import settings

GEMINI_MODEL = "gemini-2.5-flash"
_IDEAS_PROMPT = (
    "На основе этих популярных названий видео на YouTube, придумай 5 новых "
    "уникальных, кликабельных и хайповых названий для видео на русском языке "
    "в этой же тематике. Верни строго JSON со списком идей, без лишнего текста.\n\n"
    "Формат ответа:\n"
    '{{"ideas": ["название 1", "название 2", "название 3", "название 4", "название 5"]}}\n\n'
    "Названия для анализа:\n{titles}"
)


class GeminiIdeasError(RuntimeError):
    """Raised when Gemini title generation fails."""


def generate_video_title_ideas(video_titles: list[str]) -> list[str]:
    api_key = settings.gemini_api_key.strip()
    if not api_key:
        raise GeminiIdeasError("GEMINI_API_KEY is not configured")

    cleaned_titles = [title.strip() for title in video_titles if title.strip()]
    if not cleaned_titles:
        raise GeminiIdeasError("At least one non-empty video title is required")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(GEMINI_MODEL)

    titles_block = "\n".join(f"- {title}" for title in cleaned_titles[:30])
    prompt = _IDEAS_PROMPT.format(titles=titles_block)

    try:
        response = model.generate_content(prompt)
    except Exception as exc:
        raise GeminiIdeasError(f"Gemini API request failed: {exc}") from exc

    raw_text = (getattr(response, "text", None) or "").strip()
    if not raw_text:
        raise GeminiIdeasError("Gemini returned an empty response")

    return _parse_ideas_json(raw_text)


def _parse_ideas_json(raw_text: str) -> list[str]:
    candidate = raw_text.strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", candidate, flags=re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1).strip()

    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise GeminiIdeasError("Gemini response is not valid JSON") from exc

    ideas_raw = payload.get("ideas") if isinstance(payload, dict) else payload
    if not isinstance(ideas_raw, list):
        raise GeminiIdeasError("Gemini JSON must contain an 'ideas' list")

    ideas = [str(item).strip() for item in ideas_raw if str(item).strip()]
    if not ideas:
        raise GeminiIdeasError("Gemini returned no title ideas")

    return ideas[:5]
