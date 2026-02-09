"""Обработчики команд для управления администраторами."""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from src.database import Database
from src.permissions import owner_only
from config import settings

logger = logging.getLogger(__name__)


@owner_only
async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Добавление администратора по Telegram ID.
    
    Использование: /add_admin <telegram_id>
    """
    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            "❌ Использование: /add_admin <telegram_id>\n"
            "Пример: /add_admin 123456789"
        )
        return
    
    try:
        telegram_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Telegram ID должен быть числом.")
        return
    
    db = Database(settings.DATABASE_URL)
    
    try:
        # Получаем или создаём пользователя
        user = await db.get_user_by_telegram_id(telegram_id)
        
        if not user:
            # Создаём нового пользователя как админа
            user = await db.create_user(telegram_id=telegram_id)
        
        # Назначаем права администратора
        await db.set_admin_status(telegram_id, is_admin=True)
        
        await update.message.reply_text(
            f"✅ Пользователь {telegram_id} назначен администратором."
        )
        logger.info(f"User {telegram_id} promoted to admin by {update.effective_user.id}")
        
    except Exception as e:
        logger.error(f"Error adding admin: {e}")
        await update.message.reply_text(
            f"❌ Ошибка при добавлении администратора: {str(e)}"
        )
    finally:
        await db.close()


@owner_only
async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Удаление прав администратора.
    
    Использование: /remove_admin <telegram_id>
    """
    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            "❌ Использование: /remove_admin <telegram_id>\n"
            "Пример: /remove_admin 123456789"
        )
        return
    
    try:
        telegram_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Telegram ID должен быть числом.")
        return
    
    db = Database(settings.DATABASE_URL)
    
    try:
        user = await db.get_user_by_telegram_id(telegram_id)
        
        if not user:
            await update.message.reply_text(
                f"❌ Пользователь {telegram_id} не найден в базе данных."
            )
            return
        
        if user.is_owner:
            await update.message.reply_text(
                "❌ Невозможно снять права с владельца бота."
            )
            return
        
        await db.set_admin_status(telegram_id, is_admin=False)
        
        await update.message.reply_text(
            f"✅ Права администратора сняты с пользователя {telegram_id}."
        )
        logger.info(f"Admin rights removed from {telegram_id} by {update.effective_user.id}")
        
    except Exception as e:
        logger.error(f"Error removing admin: {e}")
        await update.message.reply_text(
            f"❌ Ошибка при удалении администратора: {str(e)}"
        )
    finally:
        await db.close()


@owner_only
async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Список всех администраторов.
    
    Использование: /list_admins
    """
    db = Database(settings.DATABASE_URL)
    
    try:
        admins = await db.get_all_admins()
        
        if not admins:
            await update.message.reply_text("📋 Администраторов нет.")
            return
        
        message = "👥 Список администраторов:\n\n"
        
        for admin in admins:
            status = "👑 Владелец" if admin.is_owner else "👤 Администратор"
            username = f"@{admin.username}" if admin.username else "—"
            name = admin.first_name or "Без имени"
            
            message += f"{status}\n"
            message += f"├ ID: {admin.telegram_id}\n"
            message += f"├ Имя: {name}\n"
            message += f"└ Username: {username}\n\n"
        
        await update.message.reply_text(message)
        
    except Exception as e:
        logger.error(f"Error listing admins: {e}")
        await update.message.reply_text(
            f"❌ Ошибка при получении списка администраторов: {str(e)}"
        )
    finally:
        await db.close()
