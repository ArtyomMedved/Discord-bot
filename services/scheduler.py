"""Фоновые задачи: завершение АФК, месяц Soul-Coins, резервные копии БД."""
from __future__ import annotations

import asyncio
import logging
import time

import config
from database import db
from utils import validators

logger = logging.getLogger(__name__)

BACKUP_INTERVAL_SECONDS = 24 * 3600


class Scheduler:
    def __init__(
        self,
        service,
        soul_service=None,
        interval: int = config.CHECK_INTERVAL_SECONDS,
    ) -> None:
        self.service = service
        self.soul_service = soul_service
        self.interval = max(15, interval)
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._last_backup = 0.0

    def start(self) -> None:
        if self._task is None:
            self._stop = asyncio.Event()
            self._task = asyncio.create_task(self._loop())
            logger.info("Scheduler запущен, интервал %d сек", self.interval)

    def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._check_expired()
            except Exception:
                logger.exception("Ошибка при проверке завершённых АФК")
            if self.soul_service is not None:
                try:
                    await self.soul_service.finalize_month()
                except Exception:
                    logger.exception("Ошибка при проверке месяца Soul-Coins")
                try:
                    await self.soul_service.maybe_warn()
                except Exception:
                    logger.exception("Ошибка при предупреждении Soul-Coins")
            try:
                await self._refresh_tables()
            except Exception:
                logger.exception("Ошибка при автообновлении таблиц")
            try:
                await self._maybe_backup()
            except Exception:
                logger.exception("Ошибка при резервном копировании БД")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                continue

    async def _check_expired(self) -> None:
        now = validators.now_utc()
        approved = await db.list_approved_afks()
        for afk in approved:
            try:
                end = validators.parse_iso(afk["end_time"])
            except (TypeError, ValueError):
                continue
            if end <= now:
                logger.info("Завершаем АФК #%s (пользователь %s)", afk["id"], afk["user_id"])
                await self.service.expire_afk(afk["id"])

    async def _maybe_backup(self) -> None:
        """Раз в 24 часа — резервная копия БД (защита от порчи файла)."""
        now = time.monotonic()
        if now - self._last_backup >= BACKUP_INTERVAL_SECONDS:
            await db.backup_now()
            self._last_backup = now

    async def _refresh_tables(self) -> None:
        """Каждую минуту пересобираем таблицы: вступление/выход игроков,
        смена никнеймов, изменения балансов."""
        if self.service is not None:
            await self.service.update_status_table()
        if self.soul_service is not None:
            await self.soul_service.update_table()
