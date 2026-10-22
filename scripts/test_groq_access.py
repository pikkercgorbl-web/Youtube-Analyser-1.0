#!/usr/bin/env python3
"""One-shot Groq API smoke test (Stage 7 prep — no Radar LLM integration)."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import load_dotenv

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
REQUESTED_MODEL = "openai/gpt-oss-120b"
TIMEOUT_SECONDS = 60.0

SYNTHETIC_TITLES = [
    {"video_id": "SYN_V001", "title": "I tried every cozy farming sim in 2025 — ranking them all"},
    {"video_id": "SYN_V002", "title": "Miniature painting wet palette blending for beginners"},
    {"video_id": "SYN_V003", "title": "Blender 4.x character walk cycle in 20 minutes"},
    {"video_id": "SYN_V004", "title": "Roguelike deckbuilder where your cards are room layouts"},
]

SYSTEM_PROMPT = (
    "You help niche YouTube research. Input rows are SYNTHETIC examples, not real videos. "
    "Respond in English only."
)

USER_PROMPT = f"""The following YouTube video titles are SYNTHETIC test data:

{json.dumps(SYNTHETIC_TITLES, indent=2)}

Suggest up to 3 English YouTube search queries that could discover similar content.
For each query provide:
- query (string)
- brief reason (one sentence)
- source_video_ids (list of input video_id values that support it)

Return JSON only: {{"suggestions": [{{"query": "...", "reason": "...", "source_video_ids": ["..."]}}]}}
"""


def _rate_limit_headers(response: httpx.Response) -> dict[str, str]:
    prefixes = ("x-ratelimit-", "retry-after", "x-request-id")
    out: dict[str, str] = {}
    for key, value in response.headers.items():
        lower = key.lower()
        if lower.startswith(prefixes) or lower in ("retry-after", "x-request-id"):
            out[key] = value
    return dict(sorted(out.items(), key=lambda kv: kv[0].lower()))


def main() -> int:
    load_dotenv(ROOT / ".env")
    api_key = (os.environ.get("GROQ_API_KEY") or "").strip()
    artifact_path = ROOT / "artifacts" / "groq_access_smoke.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    checked_at = datetime.now(timezone.utc).isoformat()

    base_report: dict = {
        "checked_at_utc": checked_at,
        "endpoint": GROQ_CHAT_URL,
        "requested_model": REQUESTED_MODEL,
        "synthetic_input_video_ids": [r["video_id"] for r in SYNTHETIC_TITLES],
        "note": "Success does not prove free tier; verify plan/limits in Groq Console.",
        "groq_api_key_configured": bool(api_key),
    }

    if not api_key:
        base_report["ok"] = False
        base_report["error"] = "GROQ_API_KEY is not set in .env (or was overridden in the shell)."
        artifact_path.write_text(json.dumps(base_report, indent=2), encoding="utf-8")
        print(json.dumps({**base_report, "artifact": str(artifact_path.relative_to(ROOT))}, indent=2))
        print("\nSet GROQ_API_KEY in .env and re-run: python scripts/test_groq_access.py", file=sys.stderr)
        return 2

    payload = {
        "model": REQUESTED_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT},
        ],
        "temperature": 0.2,
        "max_tokens": 512,
    }

    started = time.perf_counter()
    report = dict(base_report)
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            response = client.post(
                GROQ_CHAT_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        duration_s = round(time.perf_counter() - started, 3)
        report["http_status"] = response.status_code
        report["duration_seconds"] = duration_s
        report["rate_limit_headers"] = _rate_limit_headers(response)

        if response.status_code != 200:
            report["ok"] = False
            try:
                err_body = response.json()
            except json.JSONDecodeError:
                err_body = {"raw_text": response.text[:2000]}
            report["error"] = err_body
            artifact_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report, indent=2))
            return 1

        body = response.json()
        report["ok"] = True
        report["response_model"] = body.get("model")
        report["usage"] = body.get("usage")
        content = ""
        choices = body.get("choices") or []
        if choices:
            content = (choices[0].get("message") or {}).get("content") or ""
        report["assistant_content_length"] = len(content)
        suggestions = None
        parse_error = None
        try:
            parsed = json.loads(content)
            suggestions = parsed.get("suggestions")
        except json.JSONDecodeError as exc:
            parse_error = str(exc)
            suggestions = content[:4000] if content else None
        report["suggestions"] = suggestions
        if parse_error:
            report["suggestions_parse_error"] = parse_error

    except httpx.TimeoutException:
        report["ok"] = False
        report["duration_seconds"] = round(time.perf_counter() - started, 3)
        report["error"] = f"Request timed out after {TIMEOUT_SECONDS}s"
        artifact_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 1
    except httpx.HTTPError as exc:
        report["ok"] = False
        report["duration_seconds"] = round(time.perf_counter() - started, 3)
        report["error"] = f"HTTP client error: {type(exc).__name__}: {exc}"
        artifact_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 1

    artifact_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    console = {
        "ok": report["ok"],
        "http_status": report.get("http_status"),
        "response_model": report.get("response_model"),
        "duration_seconds": report.get("duration_seconds"),
        "usage": report.get("usage"),
        "rate_limit_headers": report.get("rate_limit_headers"),
        "suggestions": report.get("suggestions"),
        "artifact": str(artifact_path.relative_to(ROOT)),
    }
    print(json.dumps(console, indent=2, ensure_ascii=False))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
