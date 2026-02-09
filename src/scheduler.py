"""Фоновый планировщик для автоматических действий по розыгрышам."""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from config import settings
from src.automation import publish_giveaway, run_automatic_draw
from src.database import Database

logger = logging.getLogger(__name__)


class GiveawayScheduler:
    """Периодически проверяет розыгрыши и запускает автодействия."""

    def __init__(self, bot, interval_seconds: int = 30):
        self.bot = bot
        self.interval_seconds = interval_seconds
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="giveaway_scheduler")
        logger.info("Giveaway scheduler started")

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop_event.set()
        try:
            await self._task
        finally:
            self._task = None
        logger.info("Giveaway scheduler stopped")

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._tick()
            except Exception as exc:
                logger.error("Scheduler tick failed: %s", exc, exc_info=True)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                pass

    async def _tick(self) -> None:
        db = Database(settings.DATABASE_URL)
        try:
            now = datetime.utcnow()
            giveaways = await db.get_all_giveaways()
        finally:
            await db.close()

        for giveaway in giveaways:
            # Автопубликация по announce_at
            if giveaway.announce_at and not giveaway.is_published and giveaway.announce_at <= now:
                publish_result = await publish_giveaway(giveaway.id, self.bot)
                logger.info(
                    "Auto publish giveaway #%s: %s/%s",
                    giveaway.id,
                    publish_result.get("success_count", 0),
                    publish_result.get("total", 0),
                )

            # Автозавершение по ends_at (если вручную не проведено)
            if giveaway.is_active and giveaway.ends_at and giveaway.ends_at <= now:
                draw_result = await run_automatic_draw(giveaway.id, self.bot)
                logger.info("Auto draw giveaway #%s result: %s", giveaway.id, draw_result)
