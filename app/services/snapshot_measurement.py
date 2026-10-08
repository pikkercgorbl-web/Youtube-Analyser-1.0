"""Derived snapshot / discovery measurements (read path; does not mutate persisted snapshots)."""



from __future__ import annotations



from dataclasses import dataclass

from datetime import datetime

from typing import Sequence



from app.models.orm import KeywordDiscoveryHit, Video, VideoSnapshot

from app.services.metrics import ensure_utc

from app.services.snapshot_collection_policy import compute_video_age_hours

from app.services.video_published_at import (

    PUBLISHED_AT_SOURCE_API,

    published_at_source_rank,

)

from app.services.video_snapshot_storage import derive_snapshot_metrics





@dataclass(frozen=True, slots=True)

class SnapshotMeasurement:

    views: int | None

    measured_at: datetime | None

    age_hours_at_measurement: float | None

    average_vph: float | None

    published_at_used: datetime | None

    published_at_approximate: bool

    source: str  # snapshot | discovery | unavailable





def published_at_for_measurement(

    *,

    video: Video,

    snapshot: VideoSnapshot | None,

) -> tuple[datetime | None, bool]:

    """

    Prefer Video.published_at when API snippet; else snapshot.published_at at capture;

    else Video with approximate flag when not API.

    """

    video_pub = getattr(video, "published_at", None)

    video_source = getattr(video, "published_at_source", None)

    if video_pub is not None and published_at_source_rank(video_source) >= published_at_source_rank(

        PUBLISHED_AT_SOURCE_API,

    ):

        return ensure_utc(video_pub), False



    if snapshot is not None and snapshot.published_at is not None:

        return ensure_utc(snapshot.published_at), True



    if video_pub is not None:

        approximate = published_at_source_rank(video_source) < published_at_source_rank(

            PUBLISHED_AT_SOURCE_API,

        )

        return ensure_utc(video_pub), approximate



    return None, False





def derive_measurement_at_snapshot(*, video: Video, snapshot: VideoSnapshot) -> SnapshotMeasurement:

    views = snapshot.views

    measured_at = ensure_utc(snapshot.captured_at)

    published_at, approximate = published_at_for_measurement(video=video, snapshot=snapshot)

    age_hours, vph, _ = derive_snapshot_metrics(

        views=views,

        published_at=published_at,

        captured_at=measured_at,

        subscribers=None,

    )

    return SnapshotMeasurement(

        views=views,

        measured_at=measured_at,

        age_hours_at_measurement=age_hours,

        average_vph=vph,

        published_at_used=published_at,

        published_at_approximate=approximate,

        source="snapshot",

    )





def select_discovery_hit_for_measurement(

    *,

    video: Video,

    hits: Sequence[KeywordDiscoveryHit],

) -> KeywordDiscoveryHit | None:

    """

    Earliest hit with views_at_discovery (including 0) and discovered_at strictly after API published_at.

    Skips hits that predate trustworthy publication time.

    """

    published_at, _ = published_at_for_measurement(video=video, snapshot=None)

    if published_at is None:

        return None

    pub = ensure_utc(published_at)

    valid: list[KeywordDiscoveryHit] = []

    for hit in hits:

        if hit.discovered_at is None or hit.views_at_discovery is None:

            continue

        disc = ensure_utc(hit.discovered_at)

        if disc <= pub:

            continue

        valid.append(hit)

    if not valid:

        return None

    return min(valid, key=lambda row: ensure_utc(row.discovered_at))





def _discovery_measurement(

    *,

    video: Video,

    hits: Sequence[KeywordDiscoveryHit],

) -> SnapshotMeasurement | None:

    hit = select_discovery_hit_for_measurement(video=video, hits=hits)

    if hit is None:

        return None

    measured_at = ensure_utc(hit.discovered_at)

    views = int(hit.views_at_discovery)

    published_at, approximate = published_at_for_measurement(video=video, snapshot=None)

    age_hours, vph, _ = derive_snapshot_metrics(

        views=views,

        published_at=published_at,

        captured_at=measured_at,

        subscribers=None,

    )

    if age_hours is None or age_hours <= 0:

        return None

    return SnapshotMeasurement(

        views=views,

        measured_at=measured_at,

        age_hours_at_measurement=age_hours,

        average_vph=vph,

        published_at_used=published_at,

        published_at_approximate=approximate,

        source="discovery",

    )





def derive_latest_measurement(

    *,

    video: Video,

    latest_snapshot: VideoSnapshot | None,

    discovery_hits: Sequence[KeywordDiscoveryHit] | None = None,

    compute_before: datetime | None = None,

) -> SnapshotMeasurement:

    cutoff = ensure_utc(compute_before) if compute_before is not None else None

    snap = latest_snapshot

    if snap is not None and cutoff is not None and ensure_utc(snap.captured_at) > cutoff:

        snap = None

    if snap is not None:

        return derive_measurement_at_snapshot(video=video, snapshot=snap)

    discovery = _discovery_measurement(video=video, hits=discovery_hits or ())

    if discovery is not None:

        if cutoff is not None and discovery.measured_at and discovery.measured_at > cutoff:

            discovery = None

    if discovery is not None:

        return discovery

    return SnapshotMeasurement(

        views=None,

        measured_at=None,

        age_hours_at_measurement=None,

        average_vph=None,

        published_at_used=None,

        published_at_approximate=False,

        source="unavailable",

    )





def current_video_age_hours(*, video: Video, now: datetime) -> float | None:

    published_at, _ = published_at_for_measurement(video=video, snapshot=None)

    if published_at is None:

        return None

    return compute_video_age_hours(published_at, now)





def vph_series_from_snapshots(

    *,

    video: Video,

    snapshots: Sequence[VideoSnapshot],

    compute_before: datetime,

) -> list[float | None]:

    """Non-null average VPH at each capture, sorted by captured_at, excluding future observations."""

    cutoff = ensure_utc(compute_before)

    ordered = sorted(

        (snap for snap in snapshots if ensure_utc(snap.captured_at) <= cutoff),

        key=lambda snap: ensure_utc(snap.captured_at),

    )

    series: list[float | None] = []

    for snap in ordered:

        measurement = derive_measurement_at_snapshot(video=video, snapshot=snap)

        series.append(measurement.average_vph)

    return series


