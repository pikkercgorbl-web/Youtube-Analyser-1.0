"""Manual on/off radar loop for explosive channel discovery."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from dataclasses import dataclass

from app.integrations.youtube.client import (
    RadarContentFormatFilters,
    YouTubeApiError,
    filter_radar_videos_by_format,
    iter_radar_search_pages,
)
from app.integrations.youtube.innertube_metrics import InnerTubeMetrics
from app.services.radar_candidate import (
    DISCOVERY_SOURCE_HTML_FALLBACK,
    DISCOVERY_SOURCE_INNERTUBE,
    RadarCandidate,
    apply_signal_snapshot,
    apply_subscriber_enrichment,
    apply_video_outcomes,
    build_candidate_summary,
)
from app.services.radar_candidate_distribution import build_candidate_distribution
from app.services.radar_filter_metrics import RadarFilterMetrics
from app.models.db import SessionLocal
from app.services.explosive_channels_service import (
    DEFAULT_UPLOAD_PERIOD,
    ExplosiveChannelsService,
    UPLOAD_PERIOD_LABELS,
    RadarChannelHit,
)
from app.services.target_keywords_service import (
    DEFAULT_BATCH_SIZE,
    WORKER_STATUS_IDLE,
    WORKER_STATUS_RUNNING,
    WORKER_STATUS_STOPPED,
    TargetKeywordsService,
)

logger = logging.getLogger(__name__)

is_radar_running = False
radar_upload_period = DEFAULT_UPLOAD_PERIOD
_radar_blacklist_words: list[str] = []
_radar_content_filters = RadarContentFormatFilters()
_radar_loop_task: asyncio.Task[None] | None = None
_shared_worker: ExplosiveChannelsRadarWorker | None = None

BATCH_SIZE = DEFAULT_BATCH_SIZE
THROTTLE_SECONDS = 2
RADAR_CYCLE_PAUSE_MIN_SECONDS = 30
RADAR_CYCLE_PAUSE_MAX_SECONDS = 60
TARGET_VIDEOS_COUNT = 60
MAX_PAGES = 100
SEARCH_PAGE_DELAY_SECONDS = 2


@dataclass(frozen=True, slots=True)
class AnalysisScanResult:
    keyword: str
    candidates: list[RadarCandidate]
    pages_scanned: int
    min_views: int
    min_viral_coeff: float
    upload_period: str


def radar_log(message: str) -> None:
    """Write radar progress to terminal and application logs."""
    print(message, flush=True)
    logger.info(message)


def set_radar_blacklist_words(words: list[str] | None) -> None:
    global _radar_blacklist_words
    _radar_blacklist_words = [word.strip() for word in (words or []) if word.strip()]


def get_radar_blacklist_words() -> list[str]:
    return list(_radar_blacklist_words)


def set_radar_content_filters(
    *,
    exclude_streams: bool = False,
    exclude_shorts: bool = False,
    exclude_videos: bool = False,
) -> None:
    global _radar_content_filters
    _radar_content_filters = RadarContentFormatFilters(
        exclude_streams=exclude_streams,
        exclude_shorts=exclude_shorts,
        exclude_videos=exclude_videos,
    )


def get_radar_content_filters() -> RadarContentFormatFilters:
    return _radar_content_filters


def get_radar_status() -> dict[str, bool | str]:
    global radar_upload_period
    db = SessionLocal()
    try:
        radar_upload_period = ExplosiveChannelsService().get_upload_period(db)
        worker_status = TargetKeywordsService().get_worker_status(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return {
        "is_running": is_radar_running,
        "upload_period": radar_upload_period,
        "worker_status": worker_status,
    }


def stop_radar_search() -> dict[str, bool | str]:
    """Stop the active paginated keyword search immediately."""
    global is_radar_running

    is_radar_running = False
    db = SessionLocal()
    try:
        TargetKeywordsService().set_worker_status(db, WORKER_STATUS_STOPPED)
    finally:
        db.close()
    radar_log("🛑 [РАДАР] Получен запрос на остановку поиска")
    return get_radar_status()


def save_radar_upload_period(upload_period: str) -> str:
    global radar_upload_period
    db = SessionLocal()
    try:
        radar_upload_period = ExplosiveChannelsService().update_upload_period(db, upload_period)
    finally:
        db.close()
    return radar_upload_period


def get_shared_worker() -> ExplosiveChannelsRadarWorker:
    global _shared_worker
    if _shared_worker is None:
        _shared_worker = ExplosiveChannelsRadarWorker()
    return _shared_worker


def apply_radar_toggle(upload_period: str | None = None) -> dict[str, bool | str]:
    """Flip radar state without starting the scan loop (fast HTTP response)."""
    global is_radar_running

    if upload_period is not None:
        save_radar_upload_period(upload_period)

    is_radar_running = not is_radar_running

    if is_radar_running:
        radar_log("🟢 [РАДАР] Ручной запуск включён")
    else:
        radar_log("🛑 [РАДАР] Ручной запуск выключен — цикл завершится после текущей итерации")

    return get_radar_status()


async def start_radar_loop_background() -> None:
    """Start the long-running radar loop after the HTTP response is sent."""
    global _radar_loop_task

    if not is_radar_running:
        return

    await _cancel_radar_task()
    _radar_loop_task = asyncio.create_task(run_radar_loop())


async def start_manual_radar_scan_background(search_query: str) -> None:
    """Run a one-shot manual keyword scan, then stop the radar."""
    global _radar_loop_task

    if not is_radar_running:
        return

    await _cancel_radar_task()
    _radar_loop_task = asyncio.create_task(_run_manual_scan_and_stop(search_query))


async def _cancel_radar_task() -> None:
    global _radar_loop_task

    if _radar_loop_task is None or _radar_loop_task.done():
        _radar_loop_task = None
        return

    _radar_loop_task.cancel()
    try:
        await _radar_loop_task
    except asyncio.CancelledError:
        pass
    _radar_loop_task = None


async def _run_manual_scan_and_stop(search_query: str) -> None:
    global is_radar_running

    worker = get_shared_worker()
    radar_log(
        f"🎯 [РАДАР] Ручной поиск по запросу «{search_query}» "
        f"(до {TARGET_VIDEOS_COUNT} видео / {MAX_PAGES} страниц)",
    )
    try:
        await worker.run_manual_scan(search_query)
    except Exception as exc:
        radar_log(f"❌ [РАДАР] Ошибка ручного поиска: {exc}")
        logger.exception("Manual radar scan failed")
    finally:
        is_radar_running = False
        db = SessionLocal()
        try:
            service = TargetKeywordsService()
            if not service.is_worker_stopped(db):
                service.set_worker_status(db, WORKER_STATUS_IDLE)
        finally:
            db.close()
        radar_log("🛑 [РАДАР] Ручной поиск завершён — радар остановлен")


async def toggle_radar(upload_period: str | None = None) -> dict[str, bool | str]:
    """Flip radar state and start the background loop when enabled."""
    state = apply_radar_toggle(upload_period=upload_period)
    if state["is_running"]:
        await start_radar_loop_background()
    return state


async def stop_radar() -> None:
    """Stop the radar loop gracefully (used on application shutdown)."""
    global is_radar_running

    is_radar_running = False
    await _cancel_radar_task()


def _should_stop_scan(db) -> bool:
    if not is_radar_running:
        return True
    return TargetKeywordsService().is_worker_stopped(db)


async def run_radar_loop() -> None:
    """Continuously scan keyword batches while ``is_radar_running`` is True."""
    worker = get_shared_worker()
    radar_log(
        f"🟢 [РАДАР] Цикл запущен (пакет {worker._batch_size} слов, "
        f"пауза между циклами {RADAR_CYCLE_PAUSE_MIN_SECONDS}–{RADAR_CYCLE_PAUSE_MAX_SECONDS} сек.)",
    )

    try:
        while is_radar_running:
            try:
                await worker.run_once()
            except Exception as exc:
                radar_log(f"❌ [РАДАР] Ошибка цикла: {exc}")
                logger.exception("Radar loop iteration failed")

            if not is_radar_running:
                break

            pause_time = random.randint(RADAR_CYCLE_PAUSE_MIN_SECONDS, RADAR_CYCLE_PAUSE_MAX_SECONDS)
            print(f"😴 [РАДАР] Цикл завершен. Имитация человека: пауза {pause_time} сек...")
            await asyncio.sleep(pause_time)
    finally:
        radar_log("🛑 [РАДАР] Цикл остановлен")


class ExplosiveChannelsRadarWorker:
    """Scan target keywords in batches and ingest qualifying channels."""

    def __init__(
        self,
        *,
        batch_size: int = BATCH_SIZE,
        throttle_seconds: float = THROTTLE_SECONDS,
    ) -> None:
        self._batch_size = batch_size
        self._throttle_seconds = throttle_seconds
        self._scan_lock = asyncio.Lock()
        self._target_keywords = TargetKeywordsService()
        self._explosive_channels = ExplosiveChannelsService()

    async def run_once(self) -> None:
        async with self._scan_lock:
            await self._execute_scan()

    async def run_force_scan(self) -> None:
        radar_log("⚡ [РАДАР] Принудительный запуск по API...")
        await self.run_once()

    async def run_manual_scan(self, search_query: str) -> None:
        """Scan a single user-provided keyword across paginated InnerTube results."""
        keyword = search_query.strip()
        if not keyword:
            radar_log("⚠️ [РАДАР] Пустой ручной запрос — сканирование пропущено")
            return

        async with self._scan_lock:
            db = SessionLocal()
            try:
                thresholds = self._explosive_channels.get_thresholds(db)
                upload_period = self._explosive_channels.get_upload_period(db)
                period_label = UPLOAD_PERIOD_LABELS.get(upload_period, upload_period)
                radar_log(
                    "📊 [РАДАР] Пороги: "
                    f"просмотры ≥ {thresholds.min_views:,}, "
                    f"виральность ≥ {thresholds.min_viral_coeff:.1f}×, "
                    f"период видео: {period_label}",
                )
                await self._scan_keyword(
                    db,
                    keyword,
                    upload_period=upload_period,
                    label="ручной запрос",
                )
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

    async def run_analysis_scan(self, search_query: str) -> AnalysisScanResult:
        """Dry-run keyword scan: collect candidates without explosive_channels registration."""
        keyword = search_query.strip()
        if not keyword:
            radar_log("⚠️ [РАДАР] Пустой analysis запрос — сканирование пропущено")
            return AnalysisScanResult(
                keyword=keyword,
                candidates=[],
                pages_scanned=0,
                min_views=0,
                min_viral_coeff=0.0,
                upload_period="all",
            )

        async with self._scan_lock:
            db = SessionLocal()
            try:
                thresholds = self._explosive_channels.get_thresholds(db)
                upload_period = self._explosive_channels.get_upload_period(db)
                period_label = UPLOAD_PERIOD_LABELS.get(upload_period, upload_period)
                radar_log(
                    "📊 [РАДАР] Analysis scan (no DB registration): "
                    f"просмотры ≥ {thresholds.min_views:,}, "
                    f"виральность ≥ {thresholds.min_viral_coeff:.1f}×, "
                    f"период видео: {period_label}",
                )
                _, candidates, pages_scanned = await self._scan_keyword(
                    db,
                    keyword,
                    upload_period=upload_period,
                    label="analysis scan",
                    register_channels=False,
                )
                db.commit()
                return AnalysisScanResult(
                    keyword=keyword,
                    candidates=candidates,
                    pages_scanned=pages_scanned,
                    min_views=thresholds.min_views,
                    min_viral_coeff=thresholds.min_viral_coeff,
                    upload_period=upload_period,
                )
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

    async def _execute_scan(self) -> None:
        db = SessionLocal()
        try:
            batch = self._target_keywords.pick_due_batch(db, batch_size=self._batch_size)
            if not batch:
                keyword_count = len(self._target_keywords.list_all(db))
                if keyword_count == 0:
                    radar_log("🚨 БАЗА КЛЮЧЕЙ ПУСТА!")
                else:
                    radar_log("⚠️ [РАДАР] Нет ключевых слов в базе. Цикл пропущен.")
                return

            prior_checks = {
                record.id: record.last_checked
                for record in batch
            }
            keyword_ids = [record.id for record in batch]
            self._target_keywords.mark_checked(db, keyword_ids)
            radar_log(
                f"🕒 [РАДАР] Отметил {len(keyword_ids)} слов как взятые в работу "
                f"(last_checked обновлён)",
            )

            thresholds = self._explosive_channels.get_thresholds(db)
            upload_period = self._explosive_channels.get_upload_period(db)
            period_label = UPLOAD_PERIOD_LABELS.get(upload_period, upload_period)
            radar_log(f"🟢 [РАДАР] Запуск цикла. Взято слов: {len(batch)}")
            radar_log(
                "📊 [РАДАР] Пороги: "
                f"просмотры ≥ {thresholds.min_views:,}, "
                f"виральность ≥ {thresholds.min_viral_coeff:.1f}×, "
                f"период видео: {period_label}",
            )

            total_hits = 0
            for index, keyword_record in enumerate(batch, start=1):
                if _should_stop_scan(db):
                    radar_log("🛑 [РАДАР] Остановка по запросу — прерываю текущий пакет")
                    break

                keyword = keyword_record.keyword
                previous_check = prior_checks.get(keyword_record.id)
                last_checked_label = (
                    "никогда"
                    if previous_check is None
                    else previous_check.isoformat()
                )
                radar_log(
                    f"🔎 [РАДАР] [{index}/{len(batch)}] Сканирую: "
                    f"'{keyword}' (последняя проверка: {last_checked_label})",
                )

                hits, _, _ = await self._scan_keyword(
                    db,
                    keyword,
                    upload_period=upload_period,
                    label=f"{index}/{len(batch)}",
                )
                total_hits += hits

            radar_log(
                f"✅ [РАДАР] Пакет из {len(batch)} слов обработан "
                f"(каналов сохранено: {total_hits})",
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def _scan_keyword(
        self,
        db,
        keyword: str,
        *,
        upload_period: str,
        label: str,
        register_channels: bool = True,
    ) -> tuple[int, list[RadarCandidate], int]:
        """Fetch paginated InnerTube results and ingest qualifying channels."""
        self._target_keywords.set_worker_status(db, WORKER_STATUS_RUNNING)

        passed_total = 0
        total_hits = 0
        pages_fetched = 0
        skipped_by_format_total = 0
        skipped_by_filters_total = 0
        parse_errors_total = 0
        subscriber_cache: dict[str, int | None] = {}
        stopped_early = False
        innertube_metrics = InnerTubeMetrics.empty()
        filter_metrics = RadarFilterMetrics.empty()
        keyword_candidates: list[RadarCandidate] = []

        try:
            try:
                async for page_batch in iter_radar_search_pages(
                    keyword,
                    sort_by_upload_date=True,
                    max_pages=MAX_PAGES,
                    innertube_metrics=innertube_metrics,
                ):
                    if _should_stop_scan(db):
                        radar_log("🛑 [РАДАР] Поиск остановлен — прерываю листание страниц")
                        stopped_early = True
                        break

                    pages_fetched += 1
                    page_videos = page_batch.videos
                    renderer_counts = page_batch.renderer_counts
                    filter_metrics.record_discovered(len(page_videos))
                    if renderer_counts.get("htmlFallback", 0) > 0:
                        filter_metrics.record_html_fallback()
                    content_filters = get_radar_content_filters()
                    filtered_videos = filter_radar_videos_by_format(page_videos, content_filters)
                    skipped_by_format = len(page_videos) - len(filtered_videos)
                    skipped_by_format_total += skipped_by_format
                    filter_metrics.record_format_skip(skipped_by_format)
                    radar_log(
                        f"📄 [РАДАР] '{keyword}' ({label}): страница {pages_fetched}/{MAX_PAGES}, "
                        f"videoRenderer={renderer_counts.get('videoRenderer', 0)}, "
                        f"lockupViewModel={renderer_counts.get('lockupViewModel', 0)}, "
                        f"richItemRenderer={renderer_counts.get('richItemRenderer', 0)}, "
                        f"reelItemRenderer={renderer_counts.get('reelItemRenderer', 0)}, "
                        f"playlistVideoRenderer={renderer_counts.get('playlistVideoRenderer', 0)}, "
                        f"htmlFallback={renderer_counts.get('htmlFallback', 0)}, "
                        f"continuationItemRenderer={renderer_counts.get('continuationItemRenderer', 0)}, "
                        f"распознано видео: {len(page_videos)}"
                        + (
                            f", пропущено по формату: {skipped_by_format}"
                            if skipped_by_format
                            else ""
                        ),
                    )

                    if not filtered_videos:
                        if pages_fetched >= MAX_PAGES:
                            radar_log(
                                f"⚠️ [РАДАР] '{keyword}': достигнут лимит страниц ({MAX_PAGES})",
                            )
                            break
                        if _should_stop_scan(db):
                            radar_log("🛑 [РАДАР] Поиск остановлен — прерываю листание страниц")
                            stopped_early = True
                            break
                        await asyncio.sleep(SEARCH_PAGE_DELAY_SECONDS)
                        continue

                    discovery_source = (
                        DISCOVERY_SOURCE_HTML_FALLBACK
                        if renderer_counts.get("htmlFallback", 0) > 0
                        else DISCOVERY_SOURCE_INNERTUBE
                    )
                    page_candidates = [
                        RadarCandidate.from_video_search(
                            video,
                            keyword=keyword,
                            discovery_source=discovery_source,
                        )
                        for video in filtered_videos
                    ]
                    for candidate in page_candidates:
                        apply_signal_snapshot(candidate)

                    result = await self._explosive_channels.process_radar_videos(
                        db,
                        filtered_videos,
                        log_rejections=False,
                        filter_title_language=True,
                        upload_period=upload_period,
                        blacklist_words=get_radar_blacklist_words(),
                        subscriber_cache=subscriber_cache,
                        filter_metrics=filter_metrics,
                        collect_video_outcomes=True,
                        register_channels=register_channels,
                    )
                    apply_video_outcomes(page_candidates, list(result.video_outcomes))
                    apply_subscriber_enrichment(page_candidates, subscriber_cache)
                    keyword_candidates.extend(page_candidates)
                    skipped_by_filters_total += result.skipped_count
                    parse_errors_total += result.parse_error_count
                    self._log_hits(result.hits)

                    passed_total += result.passed_count
                    total_hits += len(result.hits)

                    radar_log(
                        f"📈 [РАДАР] '{keyword}': прошло фильтры {passed_total}/{TARGET_VIDEOS_COUNT}, "
                        f"сохранено каналов {total_hits}"
                        + (
                            f", пропущено по фильтрам на странице: {result.skipped_count}"
                            if result.skipped_count
                            else ""
                        )
                        + (
                            f", ошибок обработки: {result.parse_error_count}"
                            if result.parse_error_count
                            else ""
                        ),
                    )

                    if passed_total >= TARGET_VIDEOS_COUNT:
                        radar_log(
                            f"🎯 [РАДАР] '{keyword}': достигнут лимит "
                            f"{TARGET_VIDEOS_COUNT} видео после фильтров",
                        )
                        break

                    if pages_fetched >= MAX_PAGES:
                        radar_log(
                            f"⚠️ [РАДАР] '{keyword}': достигнут лимит страниц ({MAX_PAGES})",
                        )
                        break

                    if _should_stop_scan(db):
                        radar_log("🛑 [РАДАР] Поиск остановлен — прерываю листание страниц")
                        stopped_early = True
                        break

                    await asyncio.sleep(SEARCH_PAGE_DELAY_SECONDS)

            except YouTubeApiError as exc:
                radar_log(f"❌ [РАДАР] '{keyword}': ошибка YouTube — {exc}")
                logger.exception("Radar scan failed for keyword=%r", keyword)
                return total_hits, keyword_candidates, pages_fetched

            if total_hits:
                radar_log(
                    f"✅ [РАДАР] '{keyword}': сохранено каналов {total_hits} "
                    f"(страниц: {pages_fetched}, прошло фильтры: {passed_total}, "
                    f"пропущено по формату: {skipped_by_format_total}, "
                    f"пропущено по фильтрам: {skipped_by_filters_total}, "
                    f"ошибок обработки: {parse_errors_total})",
                )
            elif not stopped_early:
                radar_log(
                    f"ℹ️ [РАДАР] '{keyword}': взрывных каналов не найдено "
                    f"(страниц: {pages_fetched}, пропущено по формату: {skipped_by_format_total}, "
                    f"пропущено по фильтрам: {skipped_by_filters_total}, "
                    f"ошибок обработки: {parse_errors_total})",
                )

            if is_radar_running and not self._target_keywords.is_worker_stopped(db):
                radar_log(
                    f"⏸️ [РАДАР] Пауза {self._throttle_seconds:g} сек. "
                    "после запроса к YouTube...",
                )
                await asyncio.sleep(self._throttle_seconds)

            return total_hits, keyword_candidates, pages_fetched
        finally:
            radar_log(
                "[RADAR_INNERTUBE_METRICS] "
                + json.dumps(
                    {
                        "keyword": keyword,
                        **innertube_metrics.to_summary_dict(),
                    },
                    ensure_ascii=False,
                ),
            )
            radar_log(
                "[RADAR_FILTER_METRICS] "
                + json.dumps(
                    {
                        "keyword": keyword,
                        **filter_metrics.to_summary_dict(),
                    },
                    ensure_ascii=False,
                ),
            )
            radar_log(
                "[RADAR_CANDIDATE_SUMMARY] "
                + json.dumps(
                    build_candidate_summary(keyword, keyword_candidates),
                    ensure_ascii=False,
                ),
            )
            radar_log(
                "[RADAR_CANDIDATE_DISTRIBUTION] "
                + json.dumps(
                    build_candidate_distribution(keyword, keyword_candidates),
                    ensure_ascii=False,
                ),
            )
            if not self._target_keywords.is_worker_stopped(db):
                self._target_keywords.set_worker_status(db, WORKER_STATUS_IDLE)

    @staticmethod
    def _log_hits(hits: list[RadarChannelHit]) -> None:
        for hit in hits:
            channel_label = hit.channel_name.strip() or "Unknown"
            if not channel_label.startswith("@"):
                channel_label = f"@{channel_label}"
            radar_log(
                "🔥 [РАДАР] НАЙДЕН ВЗРЫВНОЙ КАНАЛ: "
                f"{channel_label} (Виральность {hit.viral_coefficient:.1f}). "
                "Сохраняю в БД!",
            )
