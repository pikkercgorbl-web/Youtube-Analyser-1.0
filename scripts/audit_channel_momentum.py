#!/usr/bin/env python3
"""Read-only Channel Momentum audit (local DB). No API/algorithm/DB writes."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import load_dotenv


@dataclass
class VideoAudit:
    video_id: str
    in_db: bool = True
    published_at: str | None = None
    content_format: str | None = None
    window: str | None = None
    radar_eligible: bool | None = None
    format_confirmed: bool | None = None
    format_reject_reason: str | None = None
    vph: float | None = None
    vph_source: str | None = None
    age_hours_at_compute: float | None = None
    breakout_eligible: bool | None = None
    delayed_outcome_72h: str | None = None
    delayed_growth: int | None = None


@dataclass
class ChannelAudit:
    channel_id: str
    channel_title: str
    subs: int | None
    videos_in_lookback: int
    recent_before_format: int
    previous_before_format: int
    recent_after_radar: int
    previous_after_radar: int
    recent_after_format: int
    previous_after_format: int
    passes_min_recent: bool
    breakout_n: int = 0
    confirmed_n: int = 0
    ratio: float | None = None
    growth_ok: bool = False
    reason_codes: list[str] = field(default_factory=list)
    final_pass_with_gate: bool = False
    final_pass_no_gate: bool = False
    reject_stage: str | None = None
    supporting_videos: list[VideoAudit] = field(default_factory=list)


def main() -> int:
    load_dotenv(ROOT / ".env")
    from app.models.db import SessionLocal
    from app.models.orm import Video, VideoFormat
    from app.services.attention_channel_momentum import (
        MIN_COMPARABLE_VPH,
        MIN_RECENT_VIDEOS,
        _breakout_eligible,
        _eligible_channel_video,
        _in_window,
        _subscriber_growth,
        _vph_for,
        build_channel_momentum,
    )
    from app.services.attention_delayed_outcome import delayed_outcome_for_video
    from app.services.attention_engine_service import compute_attention_engine
    from app.services.attention_engine_types import AttentionEngineConfig
    from app.services.attention_evidence import load_attention_evidence
    from app.services.metrics import utc_now
    from app.services.radar_target_eligibility import (
        RADAR_MAX_CHANNEL_SUBSCRIBERS,
        radar_target_eligible,
        radar_target_rejection_reason,
        resolve_known_subscribers,
    )
    from app.services.video_format_api_verification import load_api_format_confirmed_video_ids

    session = SessionLocal()
    now = utc_now()
    cfg = AttentionEngineConfig()
    end = now
    recent_start = end - timedelta(days=cfg.channel_recent_days)
    previous_start = recent_start - timedelta(days=cfg.channel_previous_days)
    lookback_start = previous_start
    ws, we = end - timedelta(hours=cfg.window_hours), end
    lb = we - timedelta(days=cfg.channel_recent_days + cfg.channel_previous_days)
    bundle = load_attention_evidence(session, window_start=ws, window_end=we, channel_lookback_start=lb)
    confirmed = load_api_format_confirmed_video_ids(session, list(bundle.records.keys()))

    built_gate = {r.channel_id: r for r in build_channel_momentum(bundle, cfg, now=end, publishable_confirmed_ids=confirmed)}
    built_no = {r.channel_id: r for r in build_channel_momentum(bundle, cfg, now=end, publishable_confirmed_ids=None)}

    candidates_gate: list[str] = []
    candidates_no: list[str] = []

    for channel_id, videos in bundle.extra_channel_videos.items():
        ch = bundle.channels_by_id.get(channel_id)
        subs = resolve_known_subscribers(channel=ch, latest_snapshot=None)
        if subs is None or subs > RADAR_MAX_CHANNEL_SUBSCRIBERS:
            continue
        recent_radar = []
        prev_radar = []
        recent_fmt = []
        prev_fmt = []
        for v in videos:
            if not _in_window(v.published_at, recent_start, end) and not _in_window(
                v.published_at, previous_start, recent_start
            ):
                continue
            win = "recent" if _in_window(v.published_at, recent_start, end) else "previous"
            rec = bundle.records.get(v.id)
            ch2 = rec.channel if rec else ch
            snap = rec.latest_snapshot if rec else bundle.extra_latest_snapshots.get(v.id)
            vv = rec.video if rec else v
            if radar_target_eligible(video=vv, channel=ch2, latest_snapshot=snap):
                if win == "recent":
                    recent_radar.append(v)
                else:
                    prev_radar.append(v)
            if _eligible_channel_video(bundle, v, publishable_confirmed_ids=confirmed):
                if win == "recent":
                    recent_fmt.append(v)
                else:
                    prev_fmt.append(v)
        if len(recent_fmt) >= MIN_RECENT_VIDEOS:
            candidates_gate.append(channel_id)
        recent_no = [v for v in videos if _eligible_channel_video(bundle, v, publishable_confirmed_ids=None) and _in_window(v.published_at, recent_start, end)]
        if len(recent_no) >= MIN_RECENT_VIDEOS and channel_id not in candidates_gate:
            if channel_id in {c for c, vids in bundle.extra_channel_videos.items() if len([x for x in vids if _eligible_channel_video(bundle, x, publishable_confirmed_ids=None) and _in_window(x.published_at, recent_start, end)]) >= 2}:
                pass
        if len(recent_no) >= MIN_RECENT_VIDEOS:
            candidates_no.append(channel_id)

    candidates_no = list(dict.fromkeys([c for c, vids in bundle.extra_channel_videos.items()
        if len([v for v in vids if _eligible_channel_video(bundle, v, publishable_confirmed_ids=None) and _in_window(v.published_at, recent_start, end)]) >= MIN_RECENT_VIDEOS
        and (resolve_known_subscribers(channel=bundle.channels_by_id.get(c), latest_snapshot=None) or 999999) <= RADAR_MAX_CHANNEL_SUBSCRIBERS]))

    candidates_gate = list(dict.fromkeys(candidates_gate))

    def audit_channel(channel_id: str) -> ChannelAudit:
        videos = bundle.extra_channel_videos.get(channel_id, [])
        ch = bundle.channels_by_id.get(channel_id)
        title = ch.title if ch else channel_id
        subs = resolve_known_subscribers(channel=ch, latest_snapshot=None)

        all_recent = [v for v in videos if _in_window(v.published_at, recent_start, end)]
        all_prev = [v for v in videos if _in_window(v.published_at, previous_start, recent_start)]

        recent_radar = [v for v in all_recent if _eligible_channel_video(bundle, v, publishable_confirmed_ids=None) and radar_target_eligible(
            video=(bundle.records.get(v.id).video if bundle.records.get(v.id) else v),
            channel=(bundle.records.get(v.id).channel if bundle.records.get(v.id) else ch),
            latest_snapshot=(bundle.records.get(v.id).latest_snapshot if bundle.records.get(v.id) else bundle.extra_latest_snapshots.get(v.id)),
        )]
        # simplify eligibility passes
        def fmt_ok(v, with_gate: bool):
            return _eligible_channel_video(
                bundle, v, publishable_confirmed_ids=confirmed if with_gate else None
            )

        recent_after_fmt = [v for v in all_recent if fmt_ok(v, True)]
        prev_after_fmt = [v for v in all_prev if fmt_ok(v, True)]
        recent_radar_only = [v for v in all_recent if fmt_ok(v, False)]
        prev_radar_only = [v for v in all_prev if fmt_ok(v, False)]

        ca = ChannelAudit(
            channel_id=channel_id,
            channel_title=title,
            subs=subs,
            videos_in_lookback=len(videos),
            recent_before_format=len(all_recent),
            previous_before_format=len(all_prev),
            recent_after_radar=len(recent_radar_only),
            previous_after_radar=len(prev_radar_only),
            recent_after_format=len(recent_after_fmt),
            previous_after_format=len(prev_after_fmt),
            passes_min_recent=len(recent_after_fmt) >= MIN_RECENT_VIDEOS,
        )

        if len(recent_after_fmt) < MIN_RECENT_VIDEOS:
            ca.reject_stage = "min_recent_after_format_gate"
            return ca

        recent_vph = [x for x in (_vph_for(bundle, v) for v in recent_after_fmt) if x is not None]
        prev_vph = [x for x in (_vph_for(bundle, v) for v in prev_after_fmt) if x is not None]
        r_med = float(median(recent_vph)) if len(recent_vph) >= MIN_COMPARABLE_VPH else None
        p_med = float(median(prev_vph)) if len(prev_vph) >= MIN_COMPARABLE_VPH else None
        ratio = round(r_med / p_med, 4) if r_med and p_med and p_med > 0 else None
        ca.ratio = ratio
        ca.breakout_n = sum(1 for v in recent_after_fmt if _breakout_eligible(bundle, v))
        for v in recent_after_fmt:
            rec = bundle.records.get(v.id)
            snaps = bundle.extra_snapshots_by_video.get(v.id, [])
            hits = bundle.extra_hits_by_video.get(v.id, rec.hits if rec else [])
            st, gr = delayed_outcome_for_video(
                video_id=v.id, hits=hits, snapshots=snaps if snaps else (rec.snapshots if rec else []), now=end
            )
            if st == "confirmed":
                ca.confirmed_n += 1
        growth_ok, g_abs, _, _ = _subscriber_growth(
            bundle.channel_snapshots.get(channel_id, []), lookback_start=lookback_start, now=end
        )
        ca.growth_ok = bool(growth_ok and g_abs and g_abs > 0)

        codes = []
        if ca.breakout_n >= 2:
            codes.append("multi_breakout")
        if ratio is not None and ratio >= 1.5:
            codes.append("vph_ratio")
        if ca.confirmed_n >= 2:
            codes.append("confirmed72h_cluster")
        if ca.growth_ok:
            codes.append("subscriber_growth")
        ca.reason_codes = codes

        if not codes:
            ca.reject_stage = "no_reason_branch"
        elif len(prev_after_fmt) < MIN_RECENT_VIDEOS and ratio is None and not ca.growth_ok:
            ca.reject_stage = "thin_previous_no_ratio_no_subs"
        else:
            ca.reject_stage = None

        ca.final_pass_with_gate = channel_id in built_gate
        ca.final_pass_no_gate = channel_id in built_no

        for v in recent_after_fmt + prev_after_fmt:
            rec = bundle.records.get(v.id)
            chx = rec.channel if rec else ch
            snap = rec.latest_snapshot if rec else bundle.extra_latest_snapshots.get(v.id)
            vx = rec.video if rec else v
            rej = radar_target_rejection_reason(content_format=vx.content_format, channel=chx, latest_snapshot=snap)
            in_conf = v.id in confirmed
            fmt_issue = None
            if vx.content_format in (VideoFormat.MEDIUM, VideoFormat.LONG) and not in_conf:
                fmt_issue = "format_not_api_confirmed"
            elif vx.content_format == VideoFormat.UNKNOWN:
                fmt_issue = "unknown_format"
            vph = _vph_for(bundle, v)
            src = "record.vph" if rec and rec.vph is not None else "extra_state.raw_vph"
            st, gr = delayed_outcome_for_video(
                video_id=v.id,
                hits=bundle.extra_hits_by_video.get(v.id, rec.hits if rec else []),
                snapshots=bundle.extra_snapshots_by_video.get(v.id, rec.snapshots if rec else []),
                now=end,
            )
            state = bundle.extra_video_states.get(v.id)
            ca.supporting_videos.append(
                VideoAudit(
                    video_id=v.id,
                    published_at=v.published_at.isoformat() if v.published_at else None,
                    content_format=vx.content_format.value if vx.content_format else None,
                    window="recent" if v in recent_after_fmt else "previous",
                    radar_eligible=rej is None,
                    format_confirmed=in_conf if vx.content_format in (VideoFormat.MEDIUM, VideoFormat.LONG) else None,
                    format_reject_reason=fmt_issue,
                    vph=vph,
                    vph_source=src,
                    age_hours_at_compute=state.age_hours if state else (rec.state.age_hours if rec else None),
                    breakout_eligible=_breakout_eligible(bundle, v),
                    delayed_outcome_72h=st,
                    delayed_growth=gr,
                ),
            )
        return ca

    report = {
        "computed_at": end.isoformat(),
        "windows": {
            "recent_days": cfg.channel_recent_days,
            "previous_days": cfg.channel_previous_days,
            "attention_window_hours": cfg.window_hours,
        },
        "counts": {
            "candidates_recent2_with_format_gate": len(candidates_gate),
            "candidates_recent2_without_format_gate": len(candidates_no),
            "momentum_rows_with_gate": len(built_gate),
            "momentum_rows_without_gate": len(built_no),
        },
        "channels_with_format_gate": [asdict(audit_channel(cid)) for cid in candidates_gate[:20]],
        "extra_momentum_no_gate_only": [
            asdict(audit_channel(cid)) for cid in built_no if cid not in built_gate
        ],
    }

    out = ROOT / "artifacts" / "channel_momentum_audit.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"written": str(out), "counts": report["counts"]}, indent=2))
    session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
