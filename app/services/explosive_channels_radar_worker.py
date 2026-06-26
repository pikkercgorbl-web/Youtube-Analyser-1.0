"""Manual on/off radar loop for explosive channel discovery."""

from __future__ import annotations

import asyncio
import logging
import random

from app.integrations.youtube.client import YouTubeApiError, get_radar_search_results
from app.models.db import SessionLocal
from app.services.explosive_channels_service import (
    DEFAULT_UPLOAD_PERIOD,
    ExplosiveChannelsService,
    UPLOAD_PERIOD_LABELS,
    RadarChannelHit,
)
from app.services.target_keywords_service import DEFAULT_BATCH_SIZE, TargetKeywordsService

logger = logging.getLogger(__name__)

is_radar_running = False
radar_upload_period = DEFAULT_UPLOAD_PERIOD
_radar_blacklist_words: list[str] = []
_radar_loop_task: asyncio.Task[None] | None = None
_shared_worker: ExplosiveChannelsRadarWorker | None = None

BATCH_SIZE = DEFAULT_BATCH_SIZE
THROTTLE_SECONDS = 2
RADAR_CYCLE_PAUSE_MIN_SECONDS = 30
RADAR_CYCLE_PAUSE_MAX_SECONDS = 60
MANUAL_RADAR_MAX_PAGES = 8


def radar_log(message: str) -> None:
    """Write radar progress to terminal and application logs."""
    print(message, flush=True)
    logger.info(message)


def set_radar_blacklist_words(words: list[str] | None) -> None:
    global _radar_blacklist_words
    _radar_blacklist_words = [word.strip() for word in (words or []) if word.strip()]


def get_radar_blacklist_words() -> list[str]:
    return list(_radar_blacklist_words)


def get_radar_status() -> dict[str, bool | str]:
    global radar_upload_period
    db = SessionLocal()
    try:
        radar_upload_period = ExplosiveChannelsService().get_upload_period(db)
    finally:
        db.close()
    return {"is_running": is_radar_running, "upload_period": radar_upload_period}


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
        f"(до {MANUAL_RADAR_MAX_PAGES} страниц выдачи)",
    )
    try:
        await worker.run_manual_scan(search_query)
    except Exception as exc:
        radar_log(f"❌ [РАДАР] Ошибка ручного поиска: {exc}")
        logger.exception("Manual radar scan failed")
    finally:
        is_radar_running = False
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
        max_results: int = 30,
        batch_size: int = BATCH_SIZE,
        throttle_seconds: float = THROTTLE_SECONDS,
    ) -> None:
        self._max_results = max_results
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
        """Scan a single user-provided keyword across several result pages."""
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
                    max_pages=MANUAL_RADAR_MAX_PAGES,
                )
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
                if not is_radar_running:
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

                total_hits += await self._scan_keyword(
                    db,
                    keyword,
                    upload_period=upload_period,
                    label=f"{index}/{len(batch)}",
                )

            radar_log(
                f"✅ [РАДАР] Пакет из {len(batch)} слов обработан "
                f"(каналов сохранено: {total_hits})",
            )
        finally:
            db.close()

    async def _scan_keyword(
        self,
        db,
        keyword: str,
        *,
        upload_period: str,
        label: str,
        max_pages: int | None = None,
    ) -> int:
        """Fetch videos for one keyword and ingest qualifying channels."""
        try:
            videos = await get_radar_search_results(
                keyword,
                max_results=self._max_results,
                max_pages=max_pages,
                sort_by_upload_date=True,
            )
        except YouTubeApiError as exc:
            radar_log(f"❌ [РАДАР] '{keyword}': ошибка YouTube — {exc}")
            logger.exception("Radar scan failed for keyword=%r", keyword)
            return 0

        pages_note = f", до {max_pages} стр." if max_pages else ""
        radar_log(
            f"⏳ [РАДАР] '{keyword}' ({label}): найдено {len(videos)} видео{pages_note}. "
            "Проверяю каналы...",
        )

        hits = await self._explosive_channels.process_radar_videos(
            db,
            videos,
            log_rejections=True,
            filter_title_language=True,
            upload_period=upload_period,
            blacklist_words=get_radar_blacklist_words(),
        )
        self._log_hits(hits)

        if hits:
            radar_log(
                f"✅ [РАДАР] '{keyword}': сохранено каналов {len(hits)} "
                f"(видео: {len(videos)})",
            )
        else:
            radar_log(
                f"ℹ️ [РАДАР] '{keyword}': взрывных каналов не найдено "
                f"(видео: {len(videos)})",
            )

        if is_radar_running:
            radar_log(
                f"⏸️ [РАДАР] Пауза {self._throttle_seconds:g} сек. "
                "после запроса к YouTube...",
            )
            await asyncio.sleep(self._throttle_seconds)

        return len(hits)

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
