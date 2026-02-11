"""Точка входа для запуска бота."""

import asyncio
import logging
import sys
from config import settings
from src.logging_security import setup_secure_logging


async def main():
    """Главная функция."""
    setup_secure_logging(logging.INFO)

    from src.bot import GiveawayBot
    from src.database import Database
    from src.scheduler import GiveawayScheduler

    # Валидация настроек
    if not settings.validate():
        sys.exit(1)
    
    # Инициализация базы данных
    db = Database(settings.DATABASE_URL)
    await db.init_db()
    
    # Автоматическая установка владельца при первом запуске
    if settings.OWNER_ID:
        owner = await db.get_user_by_telegram_id(settings.OWNER_ID)
        if not owner:
            owner = await db.create_user(telegram_id=settings.OWNER_ID)
        await db.set_owner_status(settings.OWNER_ID, is_owner=True)
        print(f"✅ Владелец бота: {settings.OWNER_ID}")
    
    # Создание и запуск бота
    bot = GiveawayBot(settings.TELEGRAM_BOT_TOKEN)
    application = bot.build()
    scheduler = GiveawayScheduler(application.bot)
    
    try:
        await application.initialize()
        await application.start()
        await bot.setup_bot_commands()
        await application.updater.start_polling()
        scheduler.start()
        
        # Ожидание остановки
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        print("\nОстановка бота...")
    finally:
        await scheduler.stop()
        if application.updater and application.updater.running:
            await application.updater.stop()
        await application.stop()
        await application.shutdown()
        await db.close()


if __name__ == '__main__':
    asyncio.run(main())
