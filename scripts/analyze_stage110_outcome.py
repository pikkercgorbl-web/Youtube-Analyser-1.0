"""Offline Stage 1.10 validation cohort outcome analysis (T0→T72)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.radar_stage110_outcome_analysis import run_stage110_outcome_analysis

ARTIFACTS = ROOT / "artifacts"
REVIEW_ID = "stage110_20260914_141029"


def main() -> int:
    report = run_stage110_outcome_analysis(artifacts_dir=ARTIFACTS)
    joined = report.pop("_joined_t72", [])

    json_path = ARTIFACTS / f"radar_outcome_analysis_stage110_T0_to_T72_{REVIEW_ID}.json"
    md_path = ARTIFACTS / f"radar_outcome_analysis_stage110_T0_to_T72_{REVIEW_ID}.md"
    joined_path = ARTIFACTS / f"radar_outcome_joined_stage110_T0_to_T72_{REVIEW_ID}.jsonl"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with joined_path.open("w", encoding="utf-8") as handle:
        for row in joined:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")

    q1 = report["Q1_vph_vs_views"]["final_T72"]
    md_path.write_text(
        "\n".join(
            [
                "# Stage 1.10 validation outcome analysis (T0 → T72)",
                "",
                f"**Experiment:** `{REVIEW_ID}`",
                f"**T0 reference:** {report['t0_reference_timestamp']}",
                f"**T72 elapsed (actual):** {report['checkpoint_usable_n']['T72']['elapsed_hours']} h",
                "",
                "## Usable N",
                "",
                f"`{report['checkpoint_usable_n']}`",
                "",
                "## Q1 — T0 VPH vs views (T72 final)",
                "",
                f"- Spearman views: `{q1['H0_t0_views']['spearman']}`",
                f"- Spearman VPH: `{q1['H1_t0_vph']['spearman']}`",
                f"- Δρ (VPH−views): `{q1['delta_rho_vph_minus_views']}`",
                f"- Top-10 capture views: `{q1['top10_recall_views']}`",
                f"- Top-10 capture VPH: `{q1['top10_recall_vph']}`",
                f"- Bootstrap: `{report['Q1_vph_vs_views']['bootstrap_t72']}`",
                "",
                "## Q2 — Channel-relative baseline (T72)",
                "",
                f"`{report['Q2_channel_baseline']}`",
                "",
                "## Checkpoint stability",
                "",
                f"`{report['checkpoint_stability']}`",
                "",
                "## Missingness (T72)",
                "",
                f"`{report['missingness_t72']}`",
                "",
                "## First cohort comparison",
                "",
                f"`{report['first_cohort_comparison']}`",
                "",
            ],
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "json": str(json_path),
                "md": str(md_path),
                "joined": str(joined_path),
                "t72_refreshed_n": report["checkpoint_usable_n"]["T72"]["refreshed"],
            },
            indent=2,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
