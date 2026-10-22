"""Comparable exploration pass fingerprints (Stage 6)."""

from __future__ import annotations

import hashlib

from app.services.attention_title_normalization import normalize_title


def single_pass_comparable_key(
    *,
    query_id: str,
    query_text: str,
    pages_requested: int,
    pages_scanned: int,
    settings_version: str,
    status: str,
) -> str:
    """
    Fingerprint for one query execution. Failed passes differ from ok passes and are not
    treated as zero-volume comparable observations.
    """
    q_norm = normalize_title(query_text)
    body = "|".join(
        [
            query_id,
            q_norm,
            str(pages_requested),
            str(pages_scanned),
            settings_version,
            status,
        ],
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:20]


def cycle_pass_fingerprint(
    pass_keys: tuple[str, ...],
) -> str:
    """Combined fingerprint for a discovery cycle preview (sorted ok pass keys)."""
    if not pass_keys:
        return "exploration_cycle:empty"
    digest = hashlib.sha256("|".join(sorted(pass_keys)).encode("utf-8")).hexdigest()[:16]
    return f"exploration_cycle:{digest}"


def exploration_pass_fingerprint_from_summaries(scans: tuple) -> str:
    """Build cycle fingerprint from TopicExplorationScanSummary rows."""
    keys: list[str] = []
    for scan in scans:
        if getattr(scan, "status", "failed") != "ok":
            continue
        key = getattr(scan, "pass_fingerprint", None)
        if key:
            keys.append(str(key))
            continue
        keys.append(
            single_pass_comparable_key(
                query_id=scan.query_id,
                query_text=scan.query_text,
                pages_requested=getattr(scan, "pages_requested", scan.max_pages),
                pages_scanned=scan.max_pages,
                settings_version=getattr(scan, "settings_version", "unknown"),
                status=scan.status,
            ),
        )
    return cycle_pass_fingerprint(tuple(keys))
