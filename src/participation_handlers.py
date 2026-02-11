"""Обработчики участия в розыгрышах."""

import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler

from src.database import Database
from src.permissions import is_admin, is_owner
from config import settings

logger = logging.getLogger(__name__)


def _is_current_active_giveaway(giveaway) -> bool:
    """Проверка, что розыгрыш сейчас активен по флагу и времени."""
    if not giveaway or not giveaway.is_active:
        return False

    now = datetime.utcnow()
    if giveaway.starts_at and giveaway.starts_at > now:
        return False
    if giveaway.ends_at and giveaway.ends_at <= now:
        return False
    return True


def _build_participation_status_text(giveaway, is_participating: bool, participation) -> str:
    """Формирует текст статуса участия пользователя в розыгрыше."""
    if is_participating:
        participated_at = participation.participated_at.strftime("%d.%m.%Y %H:%M") if participation else "неизвестно"
        winner_mark = "🏆 Да" if participation and participation.is_winner else "❌ Нет"
        return (
            f"🎉 <b>{giveaway.title}</b>\n\n"
            f"✅ Статус участия: <b>Участвуете</b>\n"
            f"🕐 Дата регистрации: {participated_at}\n"
            f"🏅 Победитель: {winner_mark}\n"
            f"⏰ Окончание: {giveaway.ends_at.strftime('%d.%m.%Y %H:%M') if giveaway.ends_at else 'не указано'}"
        )
    return (
        f"🎉 <b>{giveaway.title}</b>\n\n"
        f"❌ Статус участия: <b>Не участвуете</b>\n"
        f"ℹ️ Чтобы участвовать, нажмите кнопку участия под анонсом розыгрыша."
    )


async def _send_active_giveaways_choice(update: Update, context: ContextTypes.DEFAULT_TYPE, message_target) -> None:
    """Показывает список текущих активных розыгрышей для выбора."""
    db = Database(settings.DATABASE_URL)
    try:
        giveaways = await db.get_active_giveaways()
        current_giveaways = [g for g in giveaways if _is_current_active_giveaway(g)]
    finally:
        await db.close()

    if not current_giveaways:
        text = "ℹ️ Сейчас нет активных розыгрышей для проверки."
        if hasattr(message_target, "reply_text"):
            await message_target.reply_text(text)
        else:
            await message_target.edit_message_text(text)
        return

    if len(current_giveaways) == 1:
        giveaway = current_giveaways[0]
        await _send_participation_result(update, context, giveaway.id, message_target)
        return

    keyboard = [
        [InlineKeyboardButton(f"🎉 {g.title[:45]}", callback_data=f"check_participation_{g.id}")]
        for g in current_giveaways[:20]
    ]
    text = "📋 Выберите розыгрыш, в котором хотите проверить своё участие:"
    if hasattr(message_target, "reply_text"):
        await message_target.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await message_target.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def _send_participation_result(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    giveaway_id: int,
    message_target,
) -> None:
    """Отправляет результат проверки участия пользователя в выбранном розыгрыше."""
    user_tg_id = update.effective_user.id
    db = Database(settings.DATABASE_URL)
    try:
        giveaway = await db.get_giveaway_by_id(giveaway_id)
        if not giveaway or not _is_current_active_giveaway(giveaway):
            text = "❌ Этот розыгрыш неактивен или уже завершён."
            if hasattr(message_target, "reply_text"):
                await message_target.reply_text(text)
            else:
                await message_target.edit_message_text(text)
            return

        user = await db.get_user_by_telegram_id(user_tg_id)
        participation = await db.get_participation(user.id, giveaway_id) if user else None
        is_participating = participation is not None
        text = _build_participation_status_text(giveaway, is_participating, participation)

        keyboard = [[InlineKeyboardButton("⬅️ К списку розыгрышей", callback_data="check_participation_list")]]
        if hasattr(message_target, "reply_text"):
            await message_target.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await message_target.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    finally:
        await db.close()


async def check_my_participation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда: проверить участие пользователя в текущих активных розыгрышах."""
    await _send_active_giveaways_choice(update, context, update.message)


async def check_my_participation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback выбора розыгрыша для проверки участия."""
    query = update.callback_query
    await query.answer()
    giveaway_id = int(query.data.split("_")[-1])
    await _send_participation_result(update, context, giveaway_id, query)


async def check_my_participation_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback возврата к списку активных розыгрышей для проверки участия."""
    query = update.callback_query
    await query.answer()
    await _send_active_giveaways_choice(update, context, query)


async def _notify_admins_max_participants(
    giveaway,
    participants_count: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Отправляет уведомление админам/владельцу о достижении лимита участников."""
    db = Database(settings.DATABASE_URL)
    try:
        admins = await db.get_all_admins()
    finally:
        await db.close()

    if not admins:
        return

    text = (
        "⚠️ <b>Достигнут максимум участников</b>\n\n"
        f"🎉 <b>{giveaway.title}</b>\n"
        f"🆔 Розыгрыш: <b>#{giveaway.id}</b>\n"
        f"👥 Участников: <b>{participants_count}/{giveaway.max_participants}</b>\n\n"
        "Выберите действие:"
    )
    keyboard = [
        [
            InlineKeyboardButton("📣 Анонсировать", callback_data=f"max_participants_announce_{giveaway.id}"),
            InlineKeyboardButton("⏭ Пропустить", callback_data=f"max_participants_skip_{giveaway.id}"),
        ]
    ]

    for admin in admins:
        try:
            await context.bot.send_message(
                chat_id=admin.telegram_id,
                text=text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        except Exception as exc:
            logger.error(
                "Failed to notify admin %s about max participants in giveaway %s: %s",
                admin.telegram_id,
                giveaway.id,
                exc,
            )


async def _broadcast_max_participants_to_target_chats(
    giveaway,
    context: ContextTypes.DEFAULT_TYPE,
) -> tuple[int, int]:
    """Отправляет в целевые чаты сообщение о достижении лимита участников."""
    if not giveaway.target_chats:
        return 0, 0

    text = (
        "⚠️ <b>Набор участников завершён</b>\n\n"
        f"🎉 <b>{giveaway.title}</b>\n"
        f"👥 Достигнут максимум участников: <b>{giveaway.max_participants}</b>\n"
        "Спасибо всем за участие! Ожидайте результаты розыгрыша."
    )

    success = 0
    failed = 0
    for chat_id in giveaway.target_chats:
        try:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
            success += 1
        except Exception as exc:
            failed += 1
            logger.error(
                "Failed to broadcast max-participants message for giveaway %s to chat %s: %s",
                giveaway.id,
                chat_id,
                exc,
            )
    return success, failed


async def announce_max_participants(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка админа: отправить в целевые чаты анонс о достижении лимита участников."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await query.answer("⛔️ Только администратор может выполнить это действие.", show_alert=True)
        return

    giveaway_id = int(query.data.split("_")[-1])
    db = Database(settings.DATABASE_URL)
    try:
        giveaway = await db.get_giveaway_by_id(giveaway_id)
    finally:
        await db.close()

    if not giveaway:
        await query.edit_message_text("❌ Розыгрыш не найден.")
        return

    success, failed = await _broadcast_max_participants_to_target_chats(giveaway, context)
    await query.edit_message_text(
        "✅ Анонс о достижении лимита отправлен.\n\n"
        f"🎉 {giveaway.title}\n"
        f"📢 Успешно отправлено: {success}\n"
        f"❌ Ошибок отправки: {failed}"
    )


async def skip_max_participants_announce(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка админа: пропустить анонс о достижении лимита участников."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await query.answer("⛔️ Только администратор может выполнить это действие.", show_alert=True)
        return

    giveaway_id = int(query.data.split("_")[-1])
    await query.edit_message_text(
        f"⏭ Анонс о достижении лимита для розыгрыша #{giveaway_id} пропущен."
    )


async def join_giveaway(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Участие в розыгрыше."""
    query = update.callback_query
    
    # Получаем ID розыгрыша из callback_data
    giveaway_id = int(query.data.split('_')[1])
    user_id = update.effective_user.id

    # Администраторы не участвуют в розыгрышах (владельцу разрешено для тестов)
    if await is_admin(user_id) and not await is_owner(user_id):
        await query.answer(
            "⛔️ Администраторы не могут участвовать в розыгрышах.",
            show_alert=True
        )
        return
    
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
        if giveaway.max_participants and participants_count == giveaway.max_participants:
            await _notify_admins_max_participants(giveaway, participants_count, context)
        
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
        CommandHandler("my_participation", check_my_participation),
        CallbackQueryHandler(check_my_participation_callback, pattern=r"^check_participation_\d+$"),
        CallbackQueryHandler(check_my_participation_back, pattern=r"^check_participation_list$"),
        CallbackQueryHandler(announce_max_participants, pattern=r"^max_participants_announce_\d+$"),
        CallbackQueryHandler(skip_max_participants_announce, pattern=r"^max_participants_skip_\d+$"),
        CallbackQueryHandler(join_giveaway, pattern="^join_"),
        CallbackQueryHandler(close_message, pattern="^close_message$"),
        CallbackQueryHandler(cancel_join, pattern="^cancel_join$")
    ]
