"""Run one format-recon report (read-only, no DB)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HYPOTHESIS = (
    "Длинные спокойные исторические истории для сна: озвучка, "
    "последовательность статичных изображений, без ведущего в кадре."
)


async def main() -> None:
    from app.api.deps import get_youtube_client
    from app.services.format_reconnaissance import FormatReconnaissanceRequest, report_to_dict, run_format_reconnaissance

    client = get_youtube_client()
    report = await run_format_reconnaissance(
        client,
        FormatReconnaissanceRequest(
            format_description=HYPOTHESIS,
            example_video_url=None,
            search_queries=None,
            results_per_query=25,
            max_channel_previews=6,
        ),
    )
    data = report_to_dict(report)
    out_dir = ROOT / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "format_reconnaissance_report.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
