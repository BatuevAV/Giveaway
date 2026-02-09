"""Обработчики участия в розыгрышах."""

import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

from src.database import Database
from config import settings

logger = logging.getLogger(__name__)


async def join_giveaway(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Участие в розыгрыше."""
    query = update.callback_query
    
    # Получаем ID розыгрыша из callback_data
    giveaway_id = int(query.data.split('_')[1])
    user_id = update.effective_user.id
    
    db = Database(settings.DATABASE_URL)
    
    try:
        # Получаем розыгрыш
        giveaway = await db.get_giveaway_by_id(giveaway_id)
        
        if not giveaway:
            await query.answer("❌ Розыгрыш не найден", show_alert=True)
            return
        
        if not giveaway.is_active:
            await query.answer("❌ Розыгрыш неактивен", show_alert=True)
            return

        now = datetime.utcnow()
        if giveaway.starts_at and giveaway.starts_at > now:
            await query.answer(
                f"⏳ Розыгрыш еще не начался. Старт: {giveaway.starts_at.strftime('%d.%m.%Y %H:%M')}",
                show_alert=True
            )
            return

        if giveaway.ends_at and giveaway.ends_at <= now:
            await query.answer(
                f"⛔️ Розыгрыш уже завершен ({giveaway.ends_at.strftime('%d.%m.%Y %H:%M')})",
                show_alert=True
            )
            return
        
        # Проверяем обязательные подписки
        if giveaway.required_channels:
            not_subscribed = []
            
            for chat_id in giveaway.required_channels:
                is_member = await db.check_user_membership(
                    user_id=user_id,
                    chat_id=chat_id,
                    bot=context.bot
                )
                
                if not is_member:
                    try:
                        chat = await context.bot.get_chat(chat_id)
                        chat_title = chat.title or "Канал"
                        
                        # Пытаемся получить ссылку на канал
                        if chat.username:
                            chat_link = f"https://t.me/{chat.username}"
                        elif chat.invite_link:
                            chat_link = chat.invite_link
                        else:
                            chat_link = f"Chat ID: {chat_id}"
                        
                        not_subscribed.append(f"• [{chat_title}]({chat_link})")
                    except Exception as e:
                        logger.error(f"Error getting chat info for {chat_id}: {e}")
                        not_subscribed.append(f"• Chat ID: {chat_id}")
            
            # Если есть неподписанные каналы
            if not_subscribed:
                await query.answer()
                
                keyboard = [
                    [InlineKeyboardButton("✅ Я подписался, проверить снова", callback_data=f"join_{giveaway_id}")],
                    [InlineKeyboardButton("❌ Закрыть", callback_data="close_message")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Отправляем личное сообщение пользователю
                await context.bot.send_message(
                    chat_id=user_id,
                    text="❌ Для участия необходимо подписаться на следующие каналы:\n\n"
                    + "\n".join(not_subscribed) + 
                    "\n\n✅ Подпишитесь и нажмите кнопку для проверки.",
                    reply_markup=reply_markup,
                    parse_mode='Markdown',
                    disable_web_page_preview=True
                )
                return
        
        # Проверяем максимальное количество участников
        if giveaway.max_participants:
            current_count = await db.get_participants_count(giveaway_id)
            if current_count >= giveaway.max_participants:
                await query.answer("❌ Достигнуто максимальное количество участников", show_alert=True)
                return
        
        # Проверяем, не участвует ли уже
        existing = await db.get_participation(user_id, giveaway_id)
        if existing:
            await query.answer("ℹ️ Вы уже участвуете в этом розыгрыше!", show_alert=True)
            return
        
        # Получаем или создаём пользователя
        user = await db.get_user_by_telegram_id(user_id)
        if not user:
            user = await db.create_user(
                telegram_id=user_id,
                username=update.effective_user.username,
                first_name=update.effective_user.first_name,
                last_name=update.effective_user.last_name
            )
        
        # Добавляем участника
        await db.add_participant(user.id, giveaway_id)
        
        # Получаем обновлённое количество участников
        participants_count = await db.get_participants_count(giveaway_id)
        
        max_text = f"/{giveaway.max_participants}" if giveaway.max_participants else ""
        
        # Отвечаем на callback (убирает часики на кнопке)
        await query.answer("✅ Вы успешно зарегистрированы!", show_alert=False)
        
        # Отправляем подробное сообщение пользователю
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ <b>Вы успешно зарегистрированы в розыгрыше!</b>\n\n"
                 f"🎉 <b>{giveaway.title}</b>\n"
                 f"👥 Участников: {participants_count}{max_text}\n"
                 f"🏆 Победителей будет выбрано: {giveaway.winners_count}\n"
                 f"⏰ Окончание: {giveaway.ends_at.strftime('%d.%m.%Y %H:%M') if giveaway.ends_at else 'не указано'}\n\n"
                 f"🍀 Удачи в розыгрыше!",
            parse_mode='HTML'
        )
        
        logger.info(f"User {user_id} joined giveaway {giveaway_id}")
        
    except Exception as e:
        logger.error(f"Error joining giveaway: {e}", exc_info=True)
        await query.answer("❌ Произошла ошибка. Попробуйте позже.", show_alert=True)
        
        # Пытаемся отправить детали в личку
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"❌ <b>Ошибка при участии в розыгрыше</b>\n\n"
                     f"Детали: {str(e)}\n\n"
                     f"Попробуйте позже или обратитесь к администратору.",
                parse_mode='HTML'
            )
        except:
            pass
    finally:
        await db.close()


async def close_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Закрытие сообщения."""
    query = update.callback_query
    await query.answer()
    await query.message.delete()


async def cancel_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отмена участия."""
    query = update.callback_query
    await query.answer()
    await query.message.delete()


def get_participation_handlers():
    """Возвращает обработчики для участия в розыгрышах."""
    return [
        CallbackQueryHandler(join_giveaway, pattern="^join_"),
        CallbackQueryHandler(close_message, pattern="^close_message$"),
        CallbackQueryHandler(cancel_join, pattern="^cancel_join$")
    ]
