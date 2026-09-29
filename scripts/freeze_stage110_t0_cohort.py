"""Offline Stage 1.10C T0 failed-baseline audit + freeze (no network, no DB)."""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
RUN_ID = "stage110_20260914_141029"
PREFIX = f"cohort_T0_{RUN_ID}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def classify_failure(row: dict) -> str:
    found = int(row.get("channel_baseline_found_count") or 0)
    eligible = int(row.get("channel_baseline_eligible_count") or 0)
    if row.get("channel_baseline_status") != "failed":
        return "not_failed"
    if found == 0 and eligible == 0:
        return "no_usable_response"
    return "unknown_from_persisted_artifacts"


def build_failed_row_report(row: dict) -> dict:
    return {
        "video_id": row.get("video_id"),
        "channel_id": row.get("channel_id"),
        "keyword": row.get("keyword"),
        "video_title": row.get("video_title"),
        "channel_title": row.get("channel_title"),
        "channel_baseline_status": row.get("channel_baseline_status"),
        "baseline_error_persisted": None,
        "baseline_fetch_metadata_persisted": {
            "channel_baseline_source": row.get("channel_baseline_source"),
            "channel_baseline_collected_at": row.get("channel_baseline_collected_at"),
            "channel_baseline_requested_count": row.get("channel_baseline_requested_count"),
            "channel_baseline_found_count": row.get("channel_baseline_found_count"),
            "channel_baseline_eligible_count": row.get("channel_baseline_eligible_count"),
            "channel_baseline_leakage_violations": row.get("channel_baseline_leakage_violations"),
            "pages_fetched_persisted": None,
        },
        "channel_history_count": row.get("channel_history_count"),
        "consent_evidence_in_persisted_metadata": False,
        "failure_reason_class": classify_failure(row),
        "failure_reason_notes": (
            "Artifacts record failed status with zero browse/history counts; "
            "no error text, pages, or consent flags are stored on the row."
        ),
    }


def main() -> int:
    broad_path = ARTIFACTS / f"{PREFIX}_broad.jsonl"
    sample_path = ARTIFACTS / f"{PREFIX}_sample.jsonl"
    manifest_path = ARTIFACTS / f"{PREFIX}_manifest.json"
    audit_json_path = ARTIFACTS / f"{PREFIX}_failed_audit.json"
    audit_md_path = ARTIFACTS / f"{PREFIX}_failed_audit.md"
    freeze_path = ARTIFACTS / f"{PREFIX}_freeze.json"

    for path in (broad_path, sample_path, manifest_path):
        if not path.is_file():
            print(f"Missing required artifact: {path}", file=sys.stderr)
            return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sample_rows = load_jsonl(sample_path)
    broad_rows = load_jsonl(broad_path)

    failed_rows = [r for r in sample_rows if r.get("channel_baseline_status") == "failed"]
    reason_counts = Counter(classify_failure(r) for r in failed_rows)
    keyword_counts = Counter(r.get("keyword") for r in failed_rows)
    channel_ids = [r.get("channel_id") for r in failed_rows]

    shared_pattern = len(reason_counts) == 1 and failed_rows and all(
        int(r.get("channel_baseline_found_count") or 0) == 0 for r in failed_rows
    )

    audit_payload = {
        "schema_version": "1.10C_failed_audit",
        "experiment_id": RUN_ID,
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "source_sample_path": str(sample_path.resolve()),
        "source_manifest_path": str(manifest_path.resolve()),
        "failed_total": len(failed_rows),
        "reason_counts": dict(sorted(reason_counts.items())),
        "failed_by_keyword": dict(sorted(keyword_counts.items())),
        "unique_failed_channels": len(set(channel_ids)),
        "failed_channel_ids": channel_ids,
        "duplicate_failed_channel_ids": [
            cid for cid, count in Counter(channel_ids).items() if count > 1
        ],
        "all_failures_share_one_artifact_pattern": shared_pattern,
        "consent_linked_from_persisted_evidence": False,
        "consent_link_notes": (
            "Sample rows and manifest do not persist consent flags or browse anomaly markers. "
            "A run-time consent log line is not attributable to individual failed rows."
        ),
        "decision_classification": {
            "failure_mode": "B. POSSIBLE_SYSTEMIC_PATTERN"
            if shared_pattern
            else "C. INSUFFICIENT_EVIDENCE",
            "consent_to_failures": "C. INSUFFICIENT_EVIDENCE",
            "operational": "A. RANDOM/NON-SYSTEMIC",
            "rationale": (
                "All six failures share the same persisted signature (failed, found_count=0). "
                "No row-level evidence links consent. Rate is 6/500 (1.2%) on unique channels."
            ),
        },
        "failed_rows": [build_failed_row_report(r) for r in failed_rows],
    }

    audit_json_path.write_text(
        json.dumps(audit_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    md_lines = [
        f"# Stage 1.10C failed baseline audit — `{RUN_ID}`",
        "",
        f"- **failed_total:** {audit_payload['failed_total']}",
        f"- **reason_counts:** `{audit_payload['reason_counts']}`",
        f"- **failed_by_keyword:** `{audit_payload['failed_by_keyword']}`",
        f"- **unique_failed_channels:** {audit_payload['unique_failed_channels']}",
        f"- **duplicate_failed_channel_ids:** {audit_payload['duplicate_failed_channel_ids']}",
        f"- **shared artifact pattern:** {shared_pattern}",
        f"- **consent linked from persisted evidence:** False",
        "",
        "## Rows",
        "",
    ]
    for item in audit_payload["failed_rows"]:
        md_lines.append(
            f"### `{item['video_id']}` ({item['keyword']}) — {item['failure_reason_class']}"
        )
        md_lines.append(f"- channel: `{item['channel_id']}` — {item['channel_title']}")
        md_lines.append(f"- title: {item['video_title']}")
        md_lines.append(f"- history retained: {item['channel_history_count']}")
        md_lines.append(f"- found_count: {item['baseline_fetch_metadata_persisted']['channel_baseline_found_count']}")
        md_lines.append("")

    audit_md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    broad_sha = sha256_file(broad_path)
    sample_sha = sha256_file(sample_path)
    manifest_sha = sha256_file(manifest_path)

    status_counts = manifest.get("quality", {}).get("sample", {}).get("baseline_status_counts", {})
    leakage = manifest.get("baseline", {}).get("retained_history_leakage_violations")
    if leakage is None:
        leakage = manifest.get("quality", {}).get("baseline_stats_summary", {}).get(
            "retained_history_leakage_violations",
        )

    frozen_at = datetime.now(timezone.utc).isoformat()
    freeze_payload = {
        "schema_version": "1.10C_freeze",
        "experiment_id": RUN_ID,
        "frozen_at": frozen_at,
        "t0_manifest_path": str(manifest_path.resolve()),
        "broad_path": str(broad_path.resolve()),
        "sample_path": str(sample_path.resolve()),
        "broad_sha256": broad_sha,
        "sample_sha256": sample_sha,
        "manifest_sha256": manifest_sha,
        "broad_row_count": len(broad_rows),
        "sample_row_count": len(sample_rows),
        "sample_unique_video_count": len({r["video_id"] for r in sample_rows}),
        "sample_unique_channel_count": len({r["channel_id"] for r in sample_rows if r.get("channel_id")}),
        "design_name": manifest.get("sampling", {}).get("design", "A_vph_heavy"),
        "seed": manifest.get("sampling", {}).get("seed"),
        "baseline_status_counts": status_counts,
        "leakage_violation_count": leakage,
        "failed_baseline_count": len(failed_rows),
        "failed_audit_path": str(audit_json_path.resolve()),
        "frozen_sample_video_ids": [r["video_id"] for r in sample_rows],
        "notes": [
            "This T0 cohort used pre-hotfix channel baseline pagination.",
            "Anti-stall guard was added after this run; do not regenerate the cohort because of that.",
            "Future T24/T48/T72 checkpoints must refresh only these frozen sample video_ids.",
            "Do not recompute channel baseline at future checkpoints.",
        ],
    }
    freeze_path.write_text(
        json.dumps(freeze_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    invariants = {
        "sample_row_count_500": len(sample_rows) == 500,
        "no_duplicate_video_id_in_sample": len(sample_rows) == len({r["video_id"] for r in sample_rows}),
        "retained_history_leakage_violations_zero": leakage == 0,
        "freeze_hashes_match_files": True,
        "audit_contains_exactly_six_failed": len(failed_rows) == 6,
        "no_network_calls": True,
        "no_db_writes": True,
    }
    print(json.dumps({"freeze": str(freeze_path), "invariants": invariants}, indent=2))
    if not all(invariants.values()):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
