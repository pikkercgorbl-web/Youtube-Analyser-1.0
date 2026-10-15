"""One-shot manual search benchmark (default UI filters). Requires running backend."""

from __future__ import annotations

import json
import sys
import time
import urllib.request

QUERY = sys.argv[1] if len(sys.argv) > 1 else "grain carts"
BASE = "http://127.0.0.1:8000"


def post(path: str, body: dict) -> tuple[float, dict]:
    started = time.perf_counter()
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        payload = json.load(resp)
    return (time.perf_counter() - started) * 1000.0, payload


def main() -> None:
    default_body = {
        "query": QUERY,
        "sort_by": "relevance",
        "include_timing": True,
        "filters": {
            "hide_shorts": False,
            "hide_regular": False,
            "hide_streams": False,
            "hide_hieroglyphs": False,
            "virality_only_above_one": False,
            "virality_min": None,
            "virality_max": None,
            "views_min": None,
            "views_max": None,
            "subscribers_min": None,
            "subscribers_max": None,
            "channel_views_min": None,
            "channel_views_max": None,
            "channel_videos_min": None,
            "channel_videos_max": None,
            "channel_age_min": None,
            "channel_age_max": None,
            "published_within": None,
            "duration": None,
        },
    }
    wall_ms, data = post("/api/search", {**default_body, "phase": "full"})
    timing = data.get("timing") or {}
    print(f"query={QUERY!r} results={len(data.get('items') or [])}")
    print(f"client_wall_ms={wall_ms:.0f} server_total_ms={timing.get('total_wall_ms', 0):.0f}")
    print(f"timing={json.dumps(timing, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
