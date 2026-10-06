"""Discovery cycle performance profiling (Stage 1.20E.5). Read-only instrumentation."""

from __future__ import annotations

import logging
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterator

from sqlalchemy import event
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

SLOW_NETWORK_SECONDS = 10.0
SLOW_SQL_SECONDS = 2.0
SLOW_KEYWORD_SECONDS = 60.0
SLOW_PHASE_SECONDS = 30.0
_SQL_TRUNCATE = 240

_active_profiler: ContextVar[DiscoveryProfiler | None] = ContextVar(
    "discovery_profiler",
    default=None,
)


def active_profiler() -> DiscoveryProfiler | None:
    return _active_profiler.get()


def set_active_profiler(profiler: DiscoveryProfiler | None) -> None:
    _active_profiler.set(profiler)


@dataclass
class SqlRecord:
    duration_seconds: float
    statement_prefix: str


@dataclass
class KeywordProfile:
    keyword_id: int
    keyword: str
    started_at: datetime
    duration_seconds: float = 0.0
    fetch_seconds: float = 0.0
    parse_seconds: float = 0.0
    qualification_seconds: float = 0.0
    channel_enrichment_seconds: float = 0.0
    database_seconds: float = 0.0
    other_seconds: float = 0.0
    raw_candidates: int = 0
    parsed_candidates: int = 0
    unique_candidates: int = 0
    format_passed: int = 0
    qualification_passed: int = 0
    qualification_rejected: int = 0
    unique_channels: int = 0
    html_fallback_count: int = 0
    http_innertube: int = 0
    http_html_fallback: int = 0
    http_channel_homepage: int = 0
    http_total: int = 0
    status: str = "ok"
    errors: tuple[str, ...] = ()


@dataclass
class DiscoveryProfiler:
    enabled: bool = True
    cycle_phases_seconds: dict[str, float] = field(default_factory=dict)
    keyword_profiles: list[KeywordProfile] = field(default_factory=list)
    innertube_requests: int = 0
    html_fallback_requests: int = 0
    channel_homepage_requests: int = 0
    youtube_data_api_requests: int = 0
    sql_records: list[SqlRecord] = field(default_factory=list)
    slowest_network_seconds: float = 0.0
    slowest_network_label: str = ""
    _engine: Engine | None = field(default=None, repr=False)
    _sql_handlers: tuple[Any, Any] | None = field(default=None, repr=False)
    _keyword_stack: list[tuple[str, float]] = field(default_factory=list, repr=False)

    def attach_sql_listener(self, engine: Engine) -> None:
        if self._sql_handlers is not None:
            return
        self._engine = engine
        t_stack: list[float] = []

        def before2(_conn, _cursor, statement, *_a, **_k) -> None:
            t_stack.append(time.perf_counter())
            self.sql_records.append(
                SqlRecord(duration_seconds=0.0, statement_prefix=_truncate_sql(statement)),
            )

        def after2(_conn, _cursor, _statement, *_a, **_k) -> None:
            if not t_stack or not self.sql_records:
                return
            elapsed = time.perf_counter() - t_stack.pop()
            self.sql_records[-1].duration_seconds = elapsed
            if elapsed >= SLOW_SQL_SECONDS:
                _log_slow("sql", phase=self.sql_records[-1].statement_prefix[:80], duration=elapsed)

        event.listen(engine, "before_cursor_execute", before2)
        event.listen(engine, "after_cursor_execute", after2)
        self._sql_handlers = (before2, after2)

    def detach_sql_listener(self) -> None:
        if self._engine is None or self._sql_handlers is None:
            return
        before2, after2 = self._sql_handlers
        event.remove(self._engine, "before_cursor_execute", before2)
        event.remove(self._engine, "after_cursor_execute", after2)
        self._sql_handlers = None

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            self.cycle_phases_seconds[name] = self.cycle_phases_seconds.get(name, 0.0) + elapsed
            if elapsed >= SLOW_PHASE_SECONDS:
                _log_slow("phase", phase=name, duration=elapsed)

    def add_phase(self, name: str, seconds: float) -> None:
        self.cycle_phases_seconds[name] = self.cycle_phases_seconds.get(name, 0.0) + seconds
        if seconds >= SLOW_PHASE_SECONDS:
            _log_slow("phase", phase=name, duration=seconds)

    @contextmanager
    def keyword_phase(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            self._keyword_stack.append((name, elapsed))

    def consume_keyword_phases(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for name, sec in self._keyword_stack:
            out[name] = out.get(name, 0.0) + sec
        self._keyword_stack.clear()
        return out

    def record_http_innertube(self, count: int, *, max_duration_ms: float = 0.0) -> None:
        self.innertube_requests += count
        if max_duration_ms / 1000.0 >= SLOW_NETWORK_SECONDS:
            self.slowest_network_seconds = max(self.slowest_network_seconds, max_duration_ms / 1000.0)
            self.slowest_network_label = "innertube"

    def record_http_html_fallback(self, count: int) -> None:
        self.html_fallback_requests += count

    def record_http_channel(self, count: int) -> None:
        self.channel_homepage_requests += count

    def record_keyword_profile(self, profile: KeywordProfile) -> None:
        self.keyword_profiles.append(profile)
        if profile.duration_seconds >= SLOW_KEYWORD_SECONDS:
            _log_slow(
                "keyword",
                keyword=profile.keyword,
                phase="total",
                duration=profile.duration_seconds,
            )

    def sql_statement_count(self) -> int:
        return len(self.sql_records)

    def sql_total_seconds(self) -> float:
        return round(sum(r.duration_seconds for r in self.sql_records), 4)

    def slowest_sql(self) -> SqlRecord | None:
        if not self.sql_records:
            return None
        return max(self.sql_records, key=lambda r: r.duration_seconds)

    def print_summary(self, *, total_cycle_seconds: float) -> None:
        phases = self.cycle_phases_seconds
        network = phases.get("network_fetch", 0.0) + phases.get("per_keyword_fetch", 0.0)
        parsing = phases.get("parsing", 0.0) + phases.get("per_keyword_parse", 0.0)
        qualification = phases.get("qualification", 0.0) + phases.get("per_keyword_qualification", 0.0)
        channel = phases.get("channel_enrichment", 0.0) + phases.get("per_keyword_channel", 0.0)
        db = phases.get("database", 0.0) + phases.get("per_keyword_database", 0.0) + self.sql_total_seconds()
        other = max(
            0.0,
            total_cycle_seconds
            - phases.get("cycle_bootstrap", 0.0)
            - phases.get("keyword_selection", 0.0)
            - network
            - parsing
            - qualification
            - channel
            - db
            - phases.get("cycle_summary", 0.0)
            - phases.get("db_flush_commit", 0.0),
        )

        print("\nDISCOVERY PROFILE\n")
        print(f"Total cycle: {total_cycle_seconds:.1f}s\n")
        print(f"Keyword selection: {phases.get('keyword_selection', 0.0):.1f}s")
        print(f"Network fetch: {network:.1f}s")
        print(f"Parsing: {parsing:.1f}s")
        print(f"Qualification: {qualification:.1f}s")
        print(f"Channel enrichment: {channel:.1f}s")
        print(f"DB: {db:.1f}s")
        print(f"Other: {other:.1f}s\n")
        print("External requests:")
        print(f"InnerTube: {self.innertube_requests}")
        print(f"HTML fallback: {self.html_fallback_requests}")
        print(f"Channel/homepage: {self.channel_homepage_requests}")
        print(f"YouTube Data API: {self.youtube_data_api_requests}")
        total_http = (
            self.innertube_requests
            + self.html_fallback_requests
            + self.channel_homepage_requests
            + self.youtube_data_api_requests
        )
        print(f"Total: {total_http}\n")
        print("SQL:")
        print(f"statements: {self.sql_statement_count()}")
        print(f"total SQL time: {self.sql_total_seconds():.1f}s")
        slow = self.slowest_sql()
        if slow:
            print(f"slowest query: {slow.duration_seconds:.2f}s — {slow.statement_prefix}\n")
        else:
            print("slowest query: n/a\n")
        if self.slowest_network_seconds > 0:
            print(
                f"Slowest network sample: {self.slowest_network_seconds:.1f}s ({self.slowest_network_label})\n",
            )
        print("Per-keyword:")
        for row in sorted(self.keyword_profiles, key=lambda r: r.duration_seconds, reverse=True):
            print(f'  "{row.keyword}" (id={row.keyword_id}) — {row.duration_seconds:.1f}s')
            print(
                f"    fetch={row.fetch_seconds:.1f}s parse={row.parse_seconds:.1f}s "
                f"qual={row.qualification_seconds:.1f}s channel={row.channel_enrichment_seconds:.1f}s "
                f"db={row.database_seconds:.1f}s other={row.other_seconds:.1f}s",
            )
            print(
                f"    raw={row.raw_candidates} unique={row.unique_candidates} "
                f"qual_pass={row.qualification_passed} qual_reject={row.qualification_rejected} "
                f"http={row.http_total}",
            )


def _truncate_sql(statement: str) -> str:
    text = re.sub(r"\s+", " ", str(statement)).strip()
    if len(text) > _SQL_TRUNCATE:
        return text[: _SQL_TRUNCATE - 3] + "..."
    return text


def _log_slow(kind: str, *, duration: float, phase: str = "", keyword: str = "") -> None:
    parts = [f"[discovery:slow] kind={kind} duration={duration:.1f}s"]
    if keyword:
        parts.append(f'keyword="{keyword}"')
    if phase:
        parts.append(f'phase="{phase}"')
    message = " ".join(parts)
    logger.warning(message)
    print(message)


def build_keyword_profile(
    *,
    keyword_id: int,
    keyword: str,
    started_at: datetime,
    duration_seconds: float,
    phase_seconds: dict[str, float],
    raw_candidates: int,
    unique_candidates: int,
    format_passed: int,
    qualification_passed: int,
    qualification_rejected: int,
    unique_channels: int,
    html_fallback_count: int,
    innertube_requests: int,
    status: str = "ok",
    errors: tuple[str, ...] = (),
) -> KeywordProfile:
    fetch = phase_seconds.get("fetch", 0.0)
    parse = phase_seconds.get("parse", 0.0)
    qual = phase_seconds.get("qualification", 0.0)
    channel = phase_seconds.get("channel_enrichment", 0.0)
    db = phase_seconds.get("database", 0.0)
    other = max(0.0, duration_seconds - fetch - parse - qual - channel - db)
    http_total = innertube_requests + html_fallback_count
    return KeywordProfile(
        keyword_id=keyword_id,
        keyword=keyword,
        started_at=started_at,
        duration_seconds=round(duration_seconds, 3),
        fetch_seconds=round(fetch, 3),
        parse_seconds=round(parse, 3),
        qualification_seconds=round(qual, 3),
        channel_enrichment_seconds=round(channel, 3),
        database_seconds=round(db, 3),
        other_seconds=round(other, 3),
        raw_candidates=raw_candidates,
        parsed_candidates=format_passed,
        unique_candidates=unique_candidates,
        format_passed=format_passed,
        qualification_passed=qualification_passed,
        qualification_rejected=qualification_rejected,
        unique_channels=unique_channels,
        html_fallback_count=html_fallback_count,
        http_innertube=innertube_requests,
        http_html_fallback=html_fallback_count,
        http_total=http_total,
        status=status,
        errors=errors,
    )
