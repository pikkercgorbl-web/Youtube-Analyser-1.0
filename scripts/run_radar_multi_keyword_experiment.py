"""Multi-keyword radar experiment orchestrator (Stage 1.4)."""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.services.explosive_channels_radar_worker as radar_module
from app.models.db import SessionLocal
from app.services.explosive_channels_radar_worker import ExplosiveChannelsRadarWorker
from app.services.radar_multi_keyword_report import (
    KeywordExperimentResult,
    aggregate_experiment_results,
    format_results_table,
    parse_keyword_scan_output,
)
from app.services.target_keywords_service import (
    WORKER_STATUS_IDLE,
    TargetKeywordsService,
)

DEFAULT_KEYWORDS = (
    "AI tools",
    "productivity",
    "fitness",
    "gaming",
    "history",
    "technology",
    "self improvement",
    "interesting facts",
    "home improvement",
    "travel",
)


class _TeeStream(io.StringIO):
    """Capture stdout while still printing to the original stream."""

    def __init__(self, original: io.TextIOBase) -> None:
        super().__init__()
        self._original = original

    def write(self, text: str) -> int:
        self._original.write(text)
        return super().write(text)

    def flush(self) -> None:
        self._original.flush()
        super().flush()


def load_keywords(args: argparse.Namespace) -> list[str]:
    if args.file:
        path = Path(args.file)
        lines = path.read_text(encoding="utf-8").splitlines()
        return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]

    if args.keywords:
        return [keyword.strip() for keyword in args.keywords if keyword.strip()]

    return list(DEFAULT_KEYWORDS)


async def run_keyword_scan(
    worker: ExplosiveChannelsRadarWorker,
    keyword: str,
) -> KeywordExperimentResult:
    tee = _TeeStream(sys.stdout)
    with redirect_stdout(tee):
        await worker.run_manual_scan(keyword)
    result = parse_keyword_scan_output(keyword, tee.getvalue())
    return result


async def run_experiment(keywords: list[str], delay_seconds: float) -> dict:
    worker = ExplosiveChannelsRadarWorker()
    db = SessionLocal()
    results: list[KeywordExperimentResult] = []

    try:
        if TargetKeywordsService().is_worker_stopped(db):
            TargetKeywordsService().set_worker_status(db, WORKER_STATUS_IDLE)

        radar_module.is_radar_running = True
        try:
            for index, keyword in enumerate(keywords, start=1):
                print(f"\n=== [{index}/{len(keywords)}] Keyword: {keyword!r} ===", flush=True)
                try:
                    result = await run_keyword_scan(worker, keyword)
                    results.append(result)
                except Exception as exc:
                    print(f"❌ Experiment keyword failed: {keyword!r} — {exc}", flush=True)
                    results.append(
                        KeywordExperimentResult(
                            keyword=keyword,
                            success=False,
                            error=str(exc),
                        ),
                    )
                if delay_seconds > 0 and index < len(keywords):
                    print(
                        f"⏸ Experiment pause {delay_seconds:g}s before next keyword...",
                        flush=True,
                    )
                    await asyncio.sleep(delay_seconds)
        finally:
            radar_module.is_radar_running = False
    finally:
        db.close()

    return aggregate_experiment_results(results)


def build_output_path() -> Path:
    artifacts_dir = ROOT / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return artifacts_dir / f"radar_multi_keyword_experiment_{timestamp}.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run sequential multi-keyword radar experiment (Stage 1.4).",
    )
    parser.add_argument(
        "keywords",
        nargs="*",
        help="Keywords to scan sequentially.",
    )
    parser.add_argument(
        "--file",
        "-f",
        help="Text file with one keyword per line (# comments allowed).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Optional extra pause in seconds between keywords (default: 0).",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    keywords = load_keywords(args)
    if not keywords:
        raise SystemExit("No keywords provided.")

    print(f"Starting multi-keyword experiment ({len(keywords)} keywords)...", flush=True)
    report = await run_experiment(keywords, delay_seconds=args.delay)

    print("\n=== RADAR MULTI-KEYWORD EXPERIMENT TABLE ===", flush=True)
    print(format_results_table(report["table_rows"]), flush=True)

    totals = report["totals"]
    print("\n=== AGGREGATE TOTALS ===", flush=True)
    print(f"total_keywords: {totals['total_keywords']}", flush=True)
    print(f"successful_keywords: {totals['successful_keywords']}", flush=True)
    print(f"failed_keywords: {totals['failed_keywords']}", flush=True)
    print(f"total_discovered: {totals['total_discovered']}", flush=True)
    print(f"total_candidates: {totals['total_candidates']}", flush=True)
    print(f"total_passed: {totals['total_passed']}", flush=True)
    print(f"total_rejected: {totals['total_rejected']}", flush=True)
    print(f"total_parse_errors: {totals['total_parse_errors']}", flush=True)

    print("\n=== AGGREGATE REJECTION REASONS ===", flush=True)
    for reason, count in report["rejection_reasons"].items():
        print(f"{reason}: {count}", flush=True)

    if report["failed_keyword_details"]:
        print("\n=== FAILED KEYWORDS ===", flush=True)
        for item in report["failed_keyword_details"]:
            print(f"{item['keyword']}: {item['error']}", flush=True)

    output_path = build_output_path()
    output_path.write_text(
        __import__("json").dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nJSON summary saved to: {output_path}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
