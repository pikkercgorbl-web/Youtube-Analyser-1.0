#!/usr/bin/env python3
"""Clean baseline measurement for Channel Momentum pipeline (read-only)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import load_dotenv

MOMENTUM_H = 24
MOMENTUM_TOL = 6.0
MOMENTUM_MAX_AGE = MOMENTUM_H + MOMENTUM_TOL
MOMENTUM_MIN_AGE = MOMENTUM_H - MOMENTUM_TOL


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _hours(a: datetime, b: datetime) -> float:
    return round((ensure_utc(b) - ensure_utc(a)).total_seconds() / 3600.0, 4)


def _pctile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = int(round((len(ordered) - 1) * q))
    return round(ordered[idx], 4)


def _parse_fixed_now(value: str | None) -> datetime | None:
    if not value:
        return None
    return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _measurement_start_from_env(root: Path) -> tuple[datetime | None, str | None]:
    raw = (os.environ.get("MOMENTUM_MEASUREMENT_START_UTC") or "").strip()
    if raw:
        return _parse_fixed_now(raw), "MOMENTUM_MEASUREMENT_START_UTC"
    marker = root / "artifacts" / "momentum_measurement_start.json"
    if marker.is_file():
        payload = json.loads(marker.read_text(encoding="utf-8"))
        ts = _parse_fixed_now(str(payload.get("measurement_start_utc", "")))
        if ts:
            return ts, "artifacts/momentum_measurement_start.json"
    return None, None


def _collect_published_at_contradiction_examples(session, *, limit: int = 20) -> list[dict]:
    from sqlalchemy import func, select

    from app.models.orm import KeywordDiscoveryHit, Video, VideoSnapshot

    sub_first_hit = (
        select(
            KeywordDiscoveryHit.video_id,
            func.min(KeywordDiscoveryHit.discovered_at).label("first_disc"),
            func.min(KeywordDiscoveryHit.discovery_run_id).label("run_id"),
        )
        .group_by(KeywordDiscoveryHit.video_id)
        .subquery()
    )
    snap_api = (
        select(
            VideoSnapshot.video_id,
            func.min(VideoSnapshot.published_at).label("api_published_at"),
        )
        .where(VideoSnapshot.published_at.is_not(None))
        .group_by(VideoSnapshot.video_id)
        .subquery()
    )
    rows = session.execute(
        select(
            Video.id,
            Video.published_at,
            Video.published_at_source,
            sub_first_hit.c.first_disc,
            sub_first_hit.c.run_id,
            snap_api.c.api_published_at,
        )
        .join(sub_first_hit, sub_first_hit.c.video_id == Video.id)
        .outerjoin(snap_api, snap_api.c.video_id == Video.id)
        .where(sub_first_hit.c.first_disc < Video.published_at)
        .order_by((Video.published_at - sub_first_hit.c.first_disc).desc())
        .limit(limit),
    ).all()
    examples: list[dict] = []
    for vid, stored_pub, src, disc, run_id, api_pub in rows:
        lag_min = (ensure_utc(stored_pub) - ensure_utc(disc)).total_seconds() / 60.0
        cause = "unknown"
        if lag_min <= 5:
            cause = "innertube_relative_now_fallback_or_sub_day_rounding"
        elif api_pub and ensure_utc(api_pub) < ensure_utc(disc):
            cause = "stored_innertube_after_api_available_in_snapshots"
        elif api_pub:
            cause = "innertube_overwrite_before_api_merge_fix"
        examples.append(
            {
                "video_id": vid,
                "raw_published_text": None,
                "raw_published_text_note": "Not persisted on discovery path (InnerTube card only).",
                "stored_published_at": ensure_utc(stored_pub).isoformat(),
                "stored_published_at_source": src,
                "first_discovered_at": ensure_utc(disc).isoformat(),
                "discovery_run_id": run_id,
                "discovery_source": "discovery_worker" if (run_id or "").startswith("discovery_") else run_id,
                "api_published_at_from_snapshots": (
                    ensure_utc(api_pub).isoformat() if api_pub else None
                ),
                "inferred_root_cause": cause,
            },
        )
    return examples


@dataclass
class ProvenanceBucket:
    label: str
    video_count: int
    example_video_ids: list[str]
    notes: str


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Channel Momentum baseline audit")
    parser.add_argument(
        "--fixed-now-utc",
        help="ISO timestamp for reproducible slice (default: utc_now at run)",
    )
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    from sqlalchemy import func, select

    from app.models.db import SessionLocal
    from app.models.orm import (
        Channel,
        KeywordDiscoveryHit,
        KeywordScanRun,
        RadarApiBudgetDay,
        Video,
        VideoFormat,
        VideoFormatEnrichmentAttempt,
        VideoSnapshot,
    )
    from app.services.metrics import utc_now
    from app.services.radar_api_budget import BUDGET_KIND_VIDEOS_LIST, budget_day_status, remaining_id_units
    from app.services.unknown_format_enrichment_config import unknown_format_enrichment_settings
    from app.services.video_format_api_verification import load_api_format_confirmed_video_ids

    session = SessionLocal()
    now = _parse_fixed_now(args.fixed_now_utc) or utc_now()

    published_at_pipeline = {
        "chain": [
            "InnerTube published_text",
            "parse_relative_published_date (video_filter_service)",
            "persist_discovered_video (discovered_video_persistence)",
            "videos.list snippet.publishedAt (format enrichment / monitoring capture)",
            "apply_api_published_at (video_published_at) — does not downgrade API",
        ],
        "known_issues_fixed_in_code": [
            "hours/minutes labels previously mapped to age_days=0 → datetime.now()",
            "re-discovery overwrote Video.published_at with InnerTube parse even after API",
        ],
        "precision_storage": "videos.published_at_source: innertube_relative | api_snippet",
    }
    contradiction_examples = _collect_published_at_contradiction_examples(session, limit=20)

    # --- 1. Provenance of "recent published_at" bulk ---
    recent_cutoff = now - timedelta(hours=72)
    recent_published_72h_count = int(
        session.scalar(
            select(func.count())
            .select_from(Video)
            .where(Video.published_at >= recent_cutoff, Video.published_at <= now),
        )
        or 0,
    )
    top_minutes = [
        (row[0], int(row[1]))
        for row in session.execute(
            select(
                func.date_trunc("minute", Video.published_at),
                func.count(),
            )
            .where(Video.published_at >= recent_cutoff)
            .group_by(func.date_trunc("minute", Video.published_at))
            .order_by(func.count().desc())
            .limit(15),
        ).all()
    ]
    top_minutes_fmt = [
        {"minute": ensure_utc(m).strftime("%Y-%m-%dT%H:%M") if m else None, "count": c}
        for m, c in top_minutes
    ]

    snap_sources = dict(
        session.execute(
            select(VideoSnapshot.source, func.count())
            .where(VideoSnapshot.captured_at >= recent_cutoff)
            .group_by(VideoSnapshot.source)
            .order_by(func.count().desc()),
        ).all(),
    )

    run_id_prefixes: Counter[str] = Counter()
    for run_id, cnt in session.execute(
        select(KeywordDiscoveryHit.discovery_run_id, func.count())
        .where(KeywordDiscoveryHit.discovered_at >= recent_cutoff)
        .group_by(KeywordDiscoveryHit.discovery_run_id)
        .order_by(func.count().desc())
        .limit(200),
    ).all():
        rid = run_id or "null"
        if rid.startswith("discovery_"):
            prefix = "discovery_worker"
        elif rid.startswith("expansion_"):
            prefix = "expansion_manual"
        elif rid.startswith("test") or "test" in rid.lower():
            prefix = "test_seed"
        else:
            prefix = rid.split("_")[0][:16]
        run_id_prefixes[prefix] += int(cnt)

    existed_before = session.execute(
        select(KeywordDiscoveryHit.video_existed_before_discovery, func.count())
        .where(KeywordDiscoveryHit.discovered_at >= recent_cutoff)
        .group_by(KeywordDiscoveryHit.video_existed_before_discovery),
    ).all()

    # Videos sharing exact published_at timestamp (restore/backfill signature)
    dup_publish = session.execute(
        select(Video.published_at, func.count())
        .where(Video.published_at >= recent_cutoff)
        .group_by(Video.published_at)
        .having(func.count() >= 50)
        .order_by(func.count().desc())
        .limit(10),
    ).all()

    provenance_buckets: list[ProvenanceBucket] = []
    provenance_examples: list[dict] = []
    if dup_publish:
        ts, cnt = dup_publish[0]
        example_ids = [
            row[0]
            for row in session.execute(
                select(Video.id).where(Video.published_at == ts).limit(5),
            ).all()
        ]
        for eid in example_ids[:3]:
            hit = session.execute(
                select(
                    KeywordDiscoveryHit.discovery_run_id,
                    KeywordDiscoveryHit.discovered_at,
                    KeywordDiscoveryHit.video_existed_before_discovery,
                )
                .where(KeywordDiscoveryHit.video_id == eid)
                .order_by(KeywordDiscoveryHit.discovered_at.asc())
                .limit(1),
            ).first()
            provenance_examples.append(
                {
                    "video_id": eid,
                    "published_at": ts.isoformat() if ts else None,
                    "first_hit": {
                        "discovery_run_id": hit[0] if hit else None,
                        "discovered_at": hit[1].isoformat() if hit and hit[1] else None,
                        "video_existed_before_discovery": hit[2] if hit else None,
                    },
                },
            )
        provenance_buckets.append(
            ProvenanceBucket(
                label="shared_exact_published_at",
                video_count=int(cnt),
                example_video_ids=example_ids,
                notes="Many rows share identical published_at — likely restore/backfill or batch import, not live parse.",
            ),
        )

    test_snap = int(
        session.scalar(
            select(func.count())
            .select_from(VideoSnapshot)
            .where(VideoSnapshot.source == "test"),
        )
        or 0,
    )
    if test_snap:
        provenance_buckets.append(
            ProvenanceBucket(
                label="video_snapshots_source_test",
                video_count=test_snap,
                example_video_ids=[],
                notes="Unit/integration snapshot source=test still in DB.",
            ),
        )

    monitoring_worker_snaps = int(
        session.scalar(
            select(func.count())
            .select_from(VideoSnapshot)
            .where(VideoSnapshot.source == "monitoring_worker"),
        )
        or 0,
    )

    recent_published_subq = (
        select(Video.id)
        .where(Video.published_at >= recent_cutoff, Video.published_at <= now)
        .subquery()
    )
    with_hit_72h = int(
        session.scalar(
            select(func.count(func.distinct(KeywordDiscoveryHit.video_id))).where(
                KeywordDiscoveryHit.video_id.in_(select(recent_published_subq.c.id)),
            ),
        )
        or 0,
    )
    confirmed_recent_72h = int(
        session.scalar(
            select(func.count(func.distinct(VideoFormatEnrichmentAttempt.video_id)))
            .where(
                VideoFormatEnrichmentAttempt.last_outcome == "confirmed_regular",
                VideoFormatEnrichmentAttempt.video_id.in_(select(recent_published_subq.c.id)),
            ),
        )
        or 0,
    )
    attention_touch_72h = with_hit_72h  # same candidate pool as discovery hits

    # --- 2. Continuous observation baseline ---
    first_monitoring = session.scalar(
        select(func.min(VideoSnapshot.captured_at)).where(VideoSnapshot.source == "monitoring_worker"),
    )
    first_scan = session.scalar(select(func.min(KeywordScanRun.started_at)))
    last_scan = session.scalar(select(func.max(KeywordScanRun.started_at)))
    scan_count = session.scalar(select(func.count()).select_from(KeywordScanRun)) or 0
    first_new_discovery = session.scalar(
        select(func.min(KeywordDiscoveryHit.discovered_at)).where(
            KeywordDiscoveryHit.video_existed_before_discovery.is_(False),
        ),
    )
    first_worker_discovery = session.scalar(
        select(func.min(KeywordDiscoveryHit.discovered_at)).where(
            KeywordDiscoveryHit.video_existed_before_discovery.is_(False),
            KeywordDiscoveryHit.discovery_run_id.like("discovery_%"),
        ),
    )

    baseline_start: datetime | None = None
    baseline_source = None
    parts: list[tuple[str, datetime | None]] = [
        ("first_monitoring_worker_snapshot", first_monitoring),
        ("first_new_video_discovery", first_new_discovery),
    ]
    present = [(lbl, ensure_utc(ts)) for lbl, ts in parts if ts is not None]
    if len(present) == 2:
        baseline_start = max(ts for _, ts in present)
        baseline_source = "max(monitoring_worker_start,new_video_discovery_start)"
    elif len(present) == 1:
        baseline_start, baseline_source = present[0][1], present[0][0]

    explicit_start, explicit_source = _measurement_start_from_env(ROOT)
    measurement_start: datetime | None = baseline_start
    measurement_start_source = baseline_source
    if explicit_start is not None:
        measurement_start = explicit_start
        measurement_start_source = explicit_source
    worker_provenance_note = (
        "Cannot distinguish laptop-only worker era from older DB history without "
        "MOMENTUM_MEASUREMENT_START_UTC or artifacts/momentum_measurement_start.json."
        if explicit_start is None
        else None
    )

    negative_publish_discovery_72h = int(
        session.scalar(
            select(func.count(func.distinct(Video.id)))
            .select_from(Video)
            .join(KeywordDiscoveryHit, KeywordDiscoveryHit.video_id == Video.id)
            .where(
                Video.published_at >= recent_cutoff,
                KeywordDiscoveryHit.discovered_at < Video.published_at,
            ),
        )
        or 0,
    )
    if top_minutes and top_minutes[0][1] >= 200:
        provenance_buckets.append(
            ProvenanceBucket(
                label="minute_batch_published_at_spikes",
                video_count=int(top_minutes[0][1]),
                example_video_ids=[],
                notes=(
                    f"Up to {top_minutes[0][1]} videos share the same published_at minute "
                    "(discovery_worker bulk persist / re-scan), not live one-by-one ingest."
                ),
            ),
        )
    if negative_publish_discovery_72h:
        provenance_buckets.append(
            ProvenanceBucket(
                label="discovery_before_stored_published_at",
                video_count=negative_publish_discovery_72h,
                example_video_ids=[],
                notes=(
                    "discovered_at < published_at: stored publish time often slightly after first hit "
                    "(API refresh/backfill), not a trustworthy live publish→discovery SLA on full 72h set."
                ),
            ),
        )

    # --- 3. Budget separation ---
    fmt_daily = unknown_format_enrichment_settings.unknown_format_enrichment_daily_video_limit
    fmt_budget = budget_day_status(session, budget_kind=BUDGET_KIND_VIDEOS_LIST, now=now)
    fmt_remaining = remaining_id_units(
        session,
        budget_kind=BUDGET_KIND_VIDEOS_LIST,
        daily_limit=fmt_daily,
        now=now,
    )
    monitoring_budget_note = (
        "Monitoring captures use ApiBudgetPolicy.max_capture_requests_per_cycle "
        "(monitoring_cycle.allocate_capture_budget), NOT radar_api_budget_daily videos_list."
    )
    confirmed_in_monitoring_pool = session.scalar(
        select(func.count())
        .select_from(Video)
        .where(
            Video.content_format.in_((VideoFormat.MEDIUM, VideoFormat.LONG)),
            Video.id.in_(select(VideoFormatEnrichmentAttempt.video_id).where(
                VideoFormatEnrichmentAttempt.last_outcome == "confirmed_regular",
            )),
        ),
    )
    monitoring_snaps_today = int(
        session.scalar(
            select(func.count())
            .select_from(VideoSnapshot)
            .where(
                VideoSnapshot.source == "monitoring_worker",
                VideoSnapshot.captured_at >= now.replace(hour=0, minute=0, second=0, microsecond=0),
            ),
        )
        or 0,
    )

    # --- 4. Clean cohort: first discovery after baseline, not pre-existing in DB ---
    cohort_rows: list[dict] = []
    latency_publish_discovery: list[float] = []
    latency_discovery_format: list[float] = []
    latency_publish_format: list[float] = []
    latency_publish_first_momentum_snap: list[float] = []
    momentum_snap_in_window = 0

    cohort_worker_rows: list[dict] = []
    post_restore_rows: list[dict] = []
    strict_continuous_rows: list[dict] = []
    latency_discovery_subs: list[float] = []
    strict_publish_discovery: list[float] = []
    strict_publish_format: list[float] = []
    strict_discovery_format: list[float] = []
    strict_momentum_ages: list[float] = []
    post_restore_publish_discovery: list[float] = []
    post_restore_discovery_format: list[float] = []
    post_restore_publish_format: list[float] = []
    post_restore_momentum_ages: list[float] = []
    post_restore_ids: set[str] = set()
    strict_ids: set[str] = set()
    post_restore_format_attempt_n = 0
    post_restore_confirmed_n = 0
    strict_format_attempt_n = 0
    strict_confirmed_n = 0

    effective_start = measurement_start or baseline_start
    invariant_checks: dict = {"all_invariants_pass": False, "note": "cohort not computed"}

    if effective_start is not None:
        from app.models.orm import ChannelSubscriberEnrichmentAttempt

        stmt = (
            select(
                Video.id,
                Video.published_at,
                Video.channel_id,
                func.min(KeywordDiscoveryHit.discovered_at),
            )
            .join(KeywordDiscoveryHit, KeywordDiscoveryHit.video_id == Video.id)
            .where(
                KeywordDiscoveryHit.video_existed_before_discovery.is_(False),
                KeywordDiscoveryHit.discovery_run_id.like("discovery_%"),
            )
            .group_by(Video.id, Video.published_at, Video.channel_id)
            .having(func.min(KeywordDiscoveryHit.discovered_at) >= effective_start)
        )
        cohort_tuples = session.execute(stmt).all()
        cohort_ids = [t[0] for t in cohort_tuples if t[1] and t[3]]

        fmt_by_vid: dict[str, datetime] = {}
        for vid, last_at in session.execute(
            select(
                VideoFormatEnrichmentAttempt.video_id,
                VideoFormatEnrichmentAttempt.last_attempt_at,
            ).where(VideoFormatEnrichmentAttempt.video_id.in_(cohort_ids)),
        ).all():
            if last_at:
                fmt_by_vid[str(vid)] = ensure_utc(last_at)

        confirmed_cohort = load_api_format_confirmed_video_ids(session, cohort_ids) if cohort_ids else frozenset()

        snaps_by_vid: dict[str, list[tuple[datetime, int | None]]] = defaultdict(list)
        for vid, captured_at, views in session.execute(
            select(VideoSnapshot.video_id, VideoSnapshot.captured_at, VideoSnapshot.views).where(
                VideoSnapshot.video_id.in_(cohort_ids),
            ),
        ).all():
            if captured_at:
                snaps_by_vid[str(vid)].append((ensure_utc(captured_at), views))

        channel_ids = {str(t[2]) for t in cohort_tuples if t[2]}
        subs_by_channel: dict[str, datetime] = {}
        for ch_id, last_at in session.execute(
            select(
                ChannelSubscriberEnrichmentAttempt.channel_id,
                ChannelSubscriberEnrichmentAttempt.last_attempt_at,
            ).where(ChannelSubscriberEnrichmentAttempt.channel_id.in_(channel_ids)),
        ).all():
            if last_at:
                subs_by_channel[str(ch_id)] = ensure_utc(last_at)

        for vid, published_at, channel_id, first_disc in cohort_tuples:
            if published_at is None or first_disc is None:
                continue
            pub = ensure_utc(published_at)
            disc = ensure_utc(first_disc)
            fmt_at = fmt_by_vid.get(str(vid))
            first_momentum_snap_age: float | None = None
            for captured_at, views in sorted(snaps_by_vid.get(str(vid), []), key=lambda x: x[0]):
                if views is None:
                    continue
                age = _hours(pub, captured_at)
                if MOMENTUM_MIN_AGE <= age <= MOMENTUM_MAX_AGE:
                    first_momentum_snap_age = age
                    momentum_snap_in_window += 1
                    latency_publish_first_momentum_snap.append(age)
                    break

            pd_h = _hours(pub, disc)
            latency_publish_discovery.append(pd_h)
            if fmt_at:
                latency_discovery_format.append(_hours(disc, fmt_at))
                latency_publish_format.append(_hours(pub, fmt_at))
            sub_at = subs_by_channel.get(str(channel_id)) if channel_id else None
            if sub_at and sub_at >= disc:
                latency_discovery_subs.append(_hours(disc, sub_at))

            row = {
                "video_id": vid,
                "published_at": pub.isoformat(),
                "first_discovered_at": disc.isoformat(),
                "publish_to_discovery_h": pd_h,
                "format_confirmed": vid in confirmed_cohort,
                "first_momentum_snap_age_h": first_momentum_snap_age,
                "provenance": "discovery_worker",
            }
            cohort_worker_rows.append(row)
            cohort_rows.append(row)

            in_post_restore = pub >= effective_start and disc >= effective_start
            if in_post_restore:
                post_restore_ids.add(str(vid))
                post_restore_publish_discovery.append(pd_h)
                if fmt_at:
                    post_restore_format_attempt_n += 1
                    post_restore_discovery_format.append(_hours(disc, fmt_at))
                    post_restore_publish_format.append(_hours(pub, fmt_at))
                if vid in confirmed_cohort:
                    post_restore_confirmed_n += 1
                if first_momentum_snap_age is not None:
                    post_restore_momentum_ages.append(first_momentum_snap_age)
                if len(post_restore_rows) < 20:
                    post_restore_rows.append(row)

            if in_post_restore and disc >= pub:
                strict_ids.add(str(vid))
                strict_publish_discovery.append(pd_h)
                if fmt_at:
                    strict_format_attempt_n += 1
                    strict_discovery_format.append(_hours(disc, fmt_at))
                    strict_publish_format.append(_hours(pub, fmt_at))
                if vid in confirmed_cohort:
                    strict_confirmed_n += 1
                if first_momentum_snap_age is not None:
                    strict_momentum_ages.append(first_momentum_snap_age)
                if len(strict_continuous_rows) < 20:
                    strict_continuous_rows.append(row)

    invariant_checks = {
        "strict_subset_of_post_restore_ids": strict_ids <= post_restore_ids,
        "strict_count_lte_post_restore": len(strict_ids) <= len(post_restore_ids),
        "strict_momentum_snapshots_lte_post_restore": len(strict_momentum_ages)
        <= len(post_restore_momentum_ages),
        "strict_confirmed_lte_post_restore": strict_confirmed_n <= post_restore_confirmed_n,
        "strict_format_attempts_lte_post_restore": strict_format_attempt_n
        <= post_restore_format_attempt_n,
        "all_invariants_pass": (
            strict_ids <= post_restore_ids
            and len(strict_momentum_ages) <= len(post_restore_momentum_ages)
            and strict_confirmed_n <= post_restore_confirmed_n
            and strict_format_attempt_n <= post_restore_format_attempt_n
        ),
    }

    # --- 5. Channel momentum measurable (from offline artifact if present) ---
    offline = ROOT / "artifacts" / "channel_momentum_offline.json"
    momentum_published = None
    if offline.is_file():
        momentum_published = json.loads(offline.read_text(encoding="utf-8")).get("published_signal_count")

    report = {
        "computed_at_utc": now.isoformat(),
        "fixed_now_utc": now.isoformat(),
        "section_0_published_at": {
            "pipeline": published_at_pipeline,
            "contradiction_examples_discovered_before_published": contradiction_examples,
            "impact": {
                "vph": "calc_vph uses Video.published_at — skewed when publish after discovery",
                "monitoring_checkpoints": "age_hours from Video.published_at — wrong checkpoint windows",
                "channel_momentum": "age-aligned VPH requires published_at_source=api_snippet after fix",
            },
        },
        "section_1_provenance": {
            "recent_published_72h_count": recent_published_72h_count,
            "top_published_at_minutes": top_minutes_fmt,
            "provenance_examples": provenance_examples,
            "duplicate_published_at_buckets": [
                {"published_at": ts.isoformat() if ts else None, "count": int(c)} for ts, c in dup_publish
            ],
            "snapshot_sources_since_72h": snap_sources,
            "discovery_run_id_prefix_counts_top": dict(run_id_prefixes.most_common(10)),
            "video_existed_before_discovery_hits_72h": {
                str(k): int(v) for k, v in existed_before
            },
            "provenance_buckets": [asdict(b) for b in provenance_buckets],
            "pipeline_touch_72h_published": {
                "with_keyword_hit": with_hit_72h,
                "format_confirmed_regular": confirmed_recent_72h,
                "attention_candidate_pool_same_as_hits": attention_touch_72h,
                "monitoring_worker_snapshots_total": monitoring_worker_snaps,
            },
            "interpretation": (
                "Large 72h published counts with duplicate exact timestamps and existed_before_discovery=true "
                "indicate DB restore/historical backfill, not only live discovery parsing."
            ),
        },
        "section_2_continuous_baseline": {
            "baseline_start_utc": baseline_start.isoformat() if baseline_start else None,
            "baseline_start_source": baseline_source,
            "measurement_start_utc_for_baseline": (
                measurement_start.isoformat() if measurement_start else None
            ),
            "measurement_start_source": measurement_start_source,
            "worker_provenance_limitation": worker_provenance_note,
            "keyword_scan_runs": {"count": int(scan_count), "first": first_scan, "last": last_scan},
            "first_monitoring_worker_snapshot_utc": first_monitoring,
            "first_new_video_discovery_utc": first_new_discovery,
            "first_discovery_worker_hit_utc": first_worker_discovery,
            "manual_vs_worker": {
                "expansion_hits_72h": int(
                    session.scalar(
                        select(func.count())
                        .select_from(KeywordDiscoveryHit)
                        .where(
                            KeywordDiscoveryHit.discovered_at >= recent_cutoff,
                            KeywordDiscoveryHit.discovery_run_id.like("expansion_%"),
                        ),
                    )
                    or 0,
                ),
                "discovery_worker_hits_72h": int(
                    session.scalar(
                        select(func.count())
                        .select_from(KeywordDiscoveryHit)
                        .where(
                            KeywordDiscoveryHit.discovered_at >= recent_cutoff,
                            KeywordDiscoveryHit.discovery_run_id.like("discovery_%"),
                        ),
                    )
                    or 0,
                ),
            },
            "clean_cohort_loose": {
                "definition": (
                    "video_existed_before_discovery=false, discovery_run_id like discovery_%, "
                    "first_discovered_at>=baseline_start (includes post-restore re-discovery of old corpus)"
                ),
                "video_count": len(cohort_worker_rows),
                "note": "Not used for baseline SLA — see strict_continuous_cohort.",
            },
            "post_restore_worker_cohort": {
                "definition": (
                    "discovery_worker + existed_before=false + min(discovered_at)>=measurement_start "
                    "+ published_at>=measurement_start"
                ),
                "video_count": len(post_restore_ids),
                "format_enrichment_attempt_count": post_restore_format_attempt_n,
                "confirmed_regular_count": post_restore_confirmed_n,
                "momentum_window_snapshot_count": len(post_restore_momentum_ages),
                "sample": post_restore_rows,
                "publish_to_discovery_ordering_valid_count": len(strict_ids),
                "ordering_note": (
                    "first_discovered_at >= published_at required for trustworthy publish→discovery; "
                    "if zero, stored published_at lags behind first hit (API/backfill skew)."
                ),
            },
            "strict_continuous_cohort": {
                "definition": "post_restore_worker_cohort + first_discovered_at>=published_at",
                "video_count": len(strict_ids),
                "format_enrichment_attempt_count": strict_format_attempt_n,
                "confirmed_regular_count": strict_confirmed_n,
                "momentum_window_snapshot_count": len(strict_momentum_ages),
                "sample": strict_continuous_rows,
                "empty_sample_note": (
                    "No videos with first_discovered_at>=published_at after measurement_start — "
                    "publish→discovery SLA sample absent."
                    if len(strict_ids) == 0
                    else None
                ),
            },
            "cohort_invariant_checks": invariant_checks,
            "latencies_hours_post_restore_worker_cohort": {
                "publish_to_discovery": {
                    "n": len(post_restore_publish_discovery),
                    "p50": _pctile(post_restore_publish_discovery, 0.5),
                    "p90": _pctile(post_restore_publish_discovery, 0.9),
                    "note": "Often negative when discovered_at<published_at; do not treat as live SLA.",
                },
                "discovery_to_format_attempt": {
                    "n": len(post_restore_discovery_format),
                    "p50": _pctile(post_restore_discovery_format, 0.5),
                    "p90": _pctile(post_restore_discovery_format, 0.9),
                },
                "publish_to_format_attempt": {
                    "n": len(post_restore_publish_format),
                    "p50": _pctile(post_restore_publish_format, 0.5),
                    "p90": _pctile(post_restore_publish_format, 0.9),
                },
                "publish_to_first_momentum_window_snapshot_age": {
                    "n": len(post_restore_momentum_ages),
                    "p50": _pctile(post_restore_momentum_ages, 0.5),
                    "p90": _pctile(post_restore_momentum_ages, 0.9),
                },
            },
            "latencies_hours_loose_cohort": {
                "publish_to_discovery": {
                    "n": len(latency_publish_discovery),
                    "p50": _pctile(latency_publish_discovery, 0.5),
                    "p90": _pctile(latency_publish_discovery, 0.9),
                },
                "discovery_to_format_attempt": {
                    "n": len(latency_discovery_format),
                    "p50": _pctile(latency_discovery_format, 0.5),
                    "p90": _pctile(latency_discovery_format, 0.9),
                },
                "discovery_to_channel_subscriber_attempt": {
                    "n": len(latency_discovery_subs),
                    "p50": _pctile(latency_discovery_subs, 0.5),
                    "p90": _pctile(latency_discovery_subs, 0.9),
                    "note": "Channel-level subs attempt at or after first discovery (approximate).",
                },
                "publish_to_format_attempt": {
                    "n": len(latency_publish_format),
                    "p50": _pctile(latency_publish_format, 0.5),
                    "p90": _pctile(latency_publish_format, 0.9),
                },
                "publish_to_first_momentum_window_snapshot_age": {
                    "n": len(latency_publish_first_momentum_snap),
                    "p50": _pctile(latency_publish_first_momentum_snap, 0.5),
                    "p90": _pctile(latency_publish_first_momentum_snap, 0.9),
                    "note": "Age at capture within [18,30]h from publish — not discovery-relative SLA.",
                },
                "videos_with_momentum_window_snapshot": momentum_snap_in_window,
            },
            "latencies_hours_strict_continuous_cohort": {
                "publish_to_discovery": {
                    "n": len(strict_publish_discovery),
                    "p50": _pctile(strict_publish_discovery, 0.5),
                    "p90": _pctile(strict_publish_discovery, 0.9),
                },
                "discovery_to_format_attempt": {
                    "n": len(strict_discovery_format),
                    "p50": _pctile(strict_discovery_format, 0.5),
                    "p90": _pctile(strict_discovery_format, 0.9),
                },
                "publish_to_format_attempt": {
                    "n": len(strict_publish_format),
                    "p50": _pctile(strict_publish_format, 0.5),
                    "p90": _pctile(strict_publish_format, 0.9),
                },
                "publish_to_first_momentum_window_snapshot_age": {
                    "n": len(strict_momentum_ages),
                    "p50": _pctile(strict_momentum_ages, 0.5),
                    "p90": _pctile(strict_momentum_ages, 0.9),
                    "note": "Age at capture within [18,30]h from publish — not discovery-relative SLA.",
                },
            },
            "no_cohort_message": (
                "No baseline_start could be inferred from monitoring_worker snapshots or keyword_scan_runs."
                if baseline_start is None
                else None
            ),
        },
        "section_3_budgets": {
            "format_enrichment_ledger": {
                "kind": BUDGET_KIND_VIDEOS_LIST,
                "daily_limit": fmt_daily,
                "reserved_today": int(fmt_budget.id_units_reserved),
                "remaining_today": fmt_remaining,
            },
            "monitoring_capture_budget": monitoring_budget_note,
            "confirmed_regular_video_rows": int(confirmed_in_monitoring_pool or 0),
            "monitoring_worker_snapshots_today_utc": monitoring_snaps_today,
            "format_budget_exhausted_today": fmt_remaining == 0,
            "independence_note": (
                "Format daily cap exhaustion does not block monitoring_worker captures; "
                "monitoring eligibility requires confirmed_regular but uses separate per-cycle cap."
            ),
            "evidence_when_format_exhausted": (
                f"{monitoring_snaps_today} monitoring_worker snapshot(s) today UTC while "
                f"videos_list remaining={fmt_remaining} (reserved={int(fmt_budget.id_units_reserved)})."
            ),
        },
        "section_4_cp24_priority": {
            "planner_within_video": "checkpoint_priority_key: overdue first, then time_to_expiry (snapshot_collection_policy.py)",
            "cycle_budget": (
                "allocate_capture_budget sort: overdue, time_to_momentum_vph_deadline_hours (cp24 only), "
                "checkpoint expiry, tier, checkpoint_age, vph (monitoring_tier_budget_policy.py)"
            ),
            "momentum_deadline_hours_from_publish": MOMENTUM_MAX_AGE,
            "test": "scripts/test_monitoring_tier_budget_policy.py::test_momentum_cp24_deadline_before_tier",
        },
        "section_5_baseline_summary": {
            "measurement_start_utc": (
                measurement_start.isoformat() if measurement_start else None
            ),
            "post_restore_worker_video_count": len(post_restore_ids),
            "strict_continuous_video_count": len(strict_ids),
            "post_restore_format_attempt_count": post_restore_format_attempt_n,
            "post_restore_confirmed_regular_count": post_restore_confirmed_n,
            "strict_format_attempt_count": strict_format_attempt_n,
            "strict_confirmed_regular_count": strict_confirmed_n,
            "momentum_window_snapshots_post_restore": len(post_restore_momentum_ages),
            "momentum_window_snapshots_strict": len(strict_momentum_ages),
            "invariants_pass": invariant_checks.get("all_invariants_pass"),
            "published_momentum_signals_now": momentum_published,
            "recommended_next_step": (
                "Run workers continuously from baseline_start; refresh this script daily without mutating data."
            ),
        },
    }

    out = ROOT / "artifacts" / "momentum_baseline_measurement.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    summary = {
        "written": str(out),
        "baseline_start_utc": report["section_2_continuous_baseline"]["baseline_start_utc"],
        "post_restore_worker_cohort_n": len(post_restore_ids),
        "strict_continuous_cohort_n": len(strict_ids),
        "invariants_pass": invariant_checks.get("all_invariants_pass"),
        "recent_72h_published": recent_published_72h_count,
    }
    print(json.dumps(summary, indent=2))
    session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
