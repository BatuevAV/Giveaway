"""Декораторы и middleware для проверки прав доступа."""

import functools
import logging
from typing import Callable
from telegram import Update
from telegram.ext import ContextTypes

from src.database import Database
from config import settings

logger = logging.getLogger(__name__)


async def is_owner(telegram_id: int) -> bool:
    """
    Проверка, является ли пользователь владельцем бота.
    
    Args:
        telegram_id: Telegram ID пользователя
    
    Returns:
        True если пользователь владелец
    """
    db = Database(settings.DATABASE_URL)
    user = await db.get_user_by_telegram_id(telegram_id)
    await db.close()
    
    if user and user.is_owner:
        return True
    
    # Проверка через OWNER_ID из конфига
    return telegram_id == getattr(settings, 'OWNER_ID', None)


async def is_admin(telegram_id: int) -> bool:
    """
    Проверка, является ли пользователь администратором.
    
    Args:
        telegram_id: Telegram ID пользователя
    
    Returns:
        True если пользователь администратор или владелец
    """
    # Владелец автоматически администратор
    if await is_owner(telegram_id):
        return True
    
    db = Database(settings.DATABASE_URL)
    user = await db.get_user_by_telegram_id(telegram_id)
    await db.close()
    
    return user and user.is_admin


def owner_only(func: Callable) -> Callable:
    """
    Декоратор для ограничения доступа только для владельца бота.
    
    Args:
        func: Функция-обработчик
    
    Returns:
        Обёрнутая функция
    """
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        
        if not await is_owner(user.id):
            await update.message.reply_text(
                "⛔️ Эта команда доступна только владельцу бота."
            )
            logger.warning(f"Unauthorized owner access attempt by user {user.id}")
            return
        
        return await func(update, context, *args, **kwargs)
    
    return wrapper


def admin_only(func: Callable) -> Callable:
    """
    Декоратор для ограничения доступа только для администраторов.
    
    Args:
        func: Функция-обработчик
    
    Returns:
        Обёрнутая функция
    """
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        
        if not await is_admin(user.id):
            await update.message.reply_text(
                "⛔️ Эта команда доступна только администраторам."
            )
            logger.warning(f"Unauthorized admin access attempt by user {user.id}")
            return
        
        return await func(update, context, *args, **kwargs)
    
    return wrapper
