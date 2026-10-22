"""Immutable original daily observation artifacts + revisions + 14d index."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from app.services.metrics import ensure_utc
from app.services.radar_daily_observation_report import (
    compute_day_over_day,
    metric_value,
    render_radar_daily_observation_markdown,
)

ORIGINAL_SUBDIR = "original"
REVISIONS_SUBDIR = "revisions"
INDEX_FILENAME = "index_last_14_complete_utc_days.json"

WriteOutcome = Literal["created_original", "skipped_existing_original", "created_revision"]


def observation_root(output_dir: Path) -> Path:
    return output_dir


def original_dir(output_dir: Path) -> Path:
    return output_dir / ORIGINAL_SUBDIR


def revisions_dir(output_dir: Path, utc_day: date) -> Path:
    return output_dir / REVISIONS_SUBDIR / utc_day.isoformat()


def original_json_path(output_dir: Path, utc_day: date) -> Path:
    return original_dir(output_dir) / f"{utc_day.isoformat()}.json"


def original_md_path(output_dir: Path, utc_day: date) -> Path:
    return original_dir(output_dir) / f"{utc_day.isoformat()}.md"


def revision_stamp(generated_at: datetime) -> str:
    return ensure_utc_str(generated_at).replace(":", "").replace("-", "")


def ensure_utc_str(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def migrate_legacy_flat_artifacts(output_dir: Path) -> list[str]:
    """Move pre-v3 flat {day}.json|.md into original/ once."""
    moved: list[str] = []
    out = observation_root(output_dir)
    orig = original_dir(out)
    orig.mkdir(parents=True, exist_ok=True)
    for json_path in sorted(out.glob("20*.json")):
        name = json_path.name
        if json_path.parent.name in (ORIGINAL_SUBDIR, REVISIONS_SUBDIR):
            continue
        if name == INDEX_FILENAME or ".run" in name or name.startswith("index_"):
            continue
        day_str = json_path.stem
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day_str):
            continue
        dest = orig / name
        if not dest.exists():
            json_path.replace(dest)
            moved.append(str(dest))
        md_src = out / f"{day_str}.md"
        md_dest = orig / f"{day_str}.md"
        if md_src.is_file() and not md_dest.exists():
            md_src.replace(md_dest)
    for json_path in sorted(orig.glob("20*.json")):
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if data.get("artifact_record"):
            continue
        stamped = annotate_artifact_report(data, artifact_kind="original")
        json_path.write_text(json.dumps(stamped, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        day_str = json_path.stem
        md_path = orig / f"{day_str}.md"
        prev = load_previous_day_report(out, date.fromisoformat(day_str))
        md_path.write_text(
            render_radar_daily_observation_markdown(stamped, previous_day_report=prev),
            encoding="utf-8",
        )
    return moved


def complete_utc_days_for_catchup(
    *,
    reference_now: datetime,
    max_days: int,
) -> list[date]:
    """UTC days strictly before today UTC, oldest first, capped by max_days."""
    today = ensure_utc(reference_now).date()
    n = max(1, min(int(max_days), 90))
    days: list[date] = []
    for offset in range(n, 0, -1):
        days.append(today - timedelta(days=offset))
    return days


def missing_original_days(output_dir: Path, candidates: list[date]) -> list[date]:
    return [d for d in candidates if not original_json_path(output_dir, d).is_file()]


def annotate_artifact_report(
    report: dict[str, Any],
    *,
    artifact_kind: Literal["original", "revision"],
    revision_of_utc_day: str | None = None,
) -> dict[str, Any]:
    payload = dict(report)
    payload["artifact_record"] = {
        "kind": artifact_kind,
        "immutable_original": artifact_kind == "original",
        "revision_of_utc_day": revision_of_utc_day or payload.get("utc_day"),
        "read_models_limitation": (
            "publish_as_of_utc_day_end is null when replace-on-publish removed history before window_end. "
            "latest_in_database_at_generation is current_at_generation only — never end-of-report-day state."
        ),
    }
    if artifact_kind == "original":
        payload["artifact_record"]["first_captured_at_utc"] = payload.get("generated_at_utc")
    return payload


def persist_daily_observation_artifacts(
    report: dict[str, Any],
    *,
    output_dir: Path,
    as_revision: bool = False,
) -> tuple[WriteOutcome, Path, Path | None]:
    """
    Write original (once) or revision. Original paths: original/{day}.json|.md
    """
    output_dir = observation_root(output_dir)
    migrate_legacy_flat_artifacts(output_dir)
    utc_day = date.fromisoformat(str(report["utc_day"]))
    previous = load_previous_day_report(output_dir, utc_day)

    if as_revision:
        report_out = annotate_artifact_report(report, artifact_kind="revision")
        report_out["day_over_day"] = compute_day_over_day(report_out, previous)
        rev_dir = revisions_dir(output_dir, utc_day)
        rev_dir.mkdir(parents=True, exist_ok=True)
        stamp = revision_stamp(datetime.fromisoformat(report_out["generated_at_utc"].replace("Z", "+00:00")))
        json_path = rev_dir / f"{utc_day.isoformat()}.revision.{stamp}.json"
        md_path = rev_dir / f"{utc_day.isoformat()}.revision.{stamp}.md"
        json_path.write_text(json.dumps(report_out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        md_path.write_text(
            render_radar_daily_observation_markdown(report_out, previous_day_report=previous),
            encoding="utf-8",
        )
        return "created_revision", json_path, md_path

    orig_json = original_json_path(output_dir, utc_day)
    orig_md = original_md_path(output_dir, utc_day)
    if orig_json.is_file():
        return "skipped_existing_original", orig_json, orig_md if orig_md.is_file() else None

    original_dir(output_dir).mkdir(parents=True, exist_ok=True)
    report_out = annotate_artifact_report(report, artifact_kind="original")
    report_out["day_over_day"] = compute_day_over_day(report_out, previous)
    orig_json.write_text(json.dumps(report_out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    orig_md.write_text(
        render_radar_daily_observation_markdown(report_out, previous_day_report=previous),
        encoding="utf-8",
    )
    return "created_original", orig_json, orig_md


def _monitoring_missing_ratio(report: dict[str, Any]) -> float | None:
    agg = report.get("monitoring", {}).get("aggregated_across_cycles_in_window") or {}
    selected = metric_value(agg.get("selected_request_count"))
    missing = metric_value(agg.get("missing_count"))
    if not isinstance(selected, int) or selected <= 0:
        return None
    if not isinstance(missing, int):
        return None
    return round(missing / selected, 6)


def _index_row_from_report(report: dict[str, Any], *, present: bool) -> dict[str, Any]:
    if not present:
        return {
            "utc_day": report.get("utc_day") if isinstance(report.get("utc_day"), str) else None,
            "original_present": False,
            "status": "missing",
        }
    disc = report.get("discovery", {})
    mon = report.get("monitoring", {})
    agg = mon.get("aggregated_across_cycles_in_window") or {}
    selected = metric_value(agg.get("selected_request_count"))
    missing = metric_value(agg.get("missing_count"))
    return {
        "utc_day": report.get("utc_day"),
        "original_present": True,
        "original_generated_at_utc": (report.get("artifact_record") or {}).get("first_captured_at_utc")
        or report.get("generated_at_utc"),
        "discovery_distinct_cycles": metric_value(disc.get("distinct_discovery_run_ids_completed_in_window")),
        "discovery_hits": metric_value(disc.get("discovery_hits_in_window")),
        "monitoring_selected_requests": selected,
        "monitoring_inserted_snapshots": metric_value(agg.get("inserted_snapshot_count")),
        "monitoring_missing_count": missing,
        "monitoring_missing_to_selected_ratio": _monitoring_missing_ratio(report),
        "note": "From saved original artifact only; not live DB.",
    }


def build_observation_index_last_n_days(
    output_dir: Path,
    *,
    complete_day_count: int = 14,
    reference_now: datetime | None = None,
) -> dict[str, Any]:
    now = reference_now or datetime.now(timezone.utc)
    migrate_legacy_flat_artifacts(output_dir)
    days = complete_utc_days_for_catchup(reference_now=now, max_days=complete_day_count)
    rows: list[dict[str, Any]] = []
    for utc_day in days:
        path = original_json_path(output_dir, utc_day)
        if not path.is_file():
            rows.append({"utc_day": utc_day.isoformat(), "original_present": False, "status": "missing"})
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        row = _index_row_from_report(report, present=True)
        rows.append(row)
    present_n = sum(1 for r in rows if r.get("original_present"))
    return {
        "generated_at_utc": ensure_utc_str(now),
        "source": "saved_original_artifacts_only",
        "complete_utc_day_count": complete_day_count,
        "originals_present": present_n,
        "originals_missing": complete_day_count - present_n,
        "days": rows,
        "observation_note": "Overview of captured daily reports; not hypothesis success scoring.",
    }


def write_observation_index(output_dir: Path, *, complete_day_count: int = 14) -> Path:
    payload = build_observation_index_last_n_days(output_dir, complete_day_count=complete_day_count)
    out = observation_root(output_dir) / INDEX_FILENAME
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def load_previous_day_report(output_dir: Path, utc_day: date) -> dict[str, Any] | None:
    """Previous calendar UTC day original report for day-over-day."""
    prev = utc_day - timedelta(days=1)
    path = original_json_path(output_dir, prev)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
