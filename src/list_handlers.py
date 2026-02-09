"""Обработчики для просмотра и управления розыгрышами."""

import logging
import random
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from src.automation import format_announcement_text
from src.database import Database
from src.permissions import admin_only
from config import settings

logger = logging.getLogger(__name__)
DATETIME_INPUT_FORMAT = "%d.%m.%Y %H:%M"


async def _safe_callback_text(query, context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None, parse_mode=None) -> None:
    """
    Безопасно обновляет интерфейс после callback как для text, так и для photo сообщений.
    """
    try:
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
        return
    except Exception:
        pass

    try:
        await query.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
        return
    except Exception:
        pass

    try:
        await query.message.delete()
    except Exception:
        pass

    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode
    )


@admin_only
async def list_giveaways(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Список всех розыгрышей.
    
    Использование: /list_giveaways
    """
    db = Database(settings.DATABASE_URL)
    
    try:
        giveaways = await db.get_all_giveaways()
        
        if not giveaways:
            await update.message.reply_text(
                "📋 Розыгрышей пока нет.\n\n"
                "Создайте первый розыгрыш командой /create_giveaway"
            )
            return
        
        message = f"📋 Всего розыгрышей: {len(giveaways)}\n\n"
        
        for giveaway in giveaways:
            status_emoji = "✅" if giveaway.is_active else "🔴"
            published_emoji = "📢" if giveaway.is_published else "📝"
            
            message += f"{status_emoji} {published_emoji} **#{giveaway.id}** - {giveaway.title}\n"
            
            # Статусы
            statuses = []
            if giveaway.is_active:
                statuses.append("Активен")
            else:
                statuses.append("Неактивен")
            
            if giveaway.is_published:
                statuses.append("Опубликован")
            else:
                statuses.append("Черновик")
            
            message += f"├ Статус: {', '.join(statuses)}\n"
            
            # Даты
            if giveaway.starts_at:
                message += f"├ Начало: {giveaway.starts_at.strftime('%d.%m.%Y %H:%M')}\n"
            if giveaway.ends_at:
                message += f"├ Окончание: {giveaway.ends_at.strftime('%d.%m.%Y %H:%M')}\n"
            
            # Параметры
            message += f"├ Победителей: {giveaway.winners_count}\n"
            
            # Участники (текущие/максимум)
            participants_count = await db.get_participants_count(giveaway.id)
            if giveaway.max_participants:
                message += f"├ 👥 Участников: {participants_count}/{giveaway.max_participants}\n"
            else:
                message += f"├ 👥 Участников: {participants_count} (без ограничений)\n"
            
            # Картинка
            if giveaway.image_file_id:
                message += f"├ 📷 Есть картинка\n"
            
            message += f"└ Создан: {giveaway.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
        
        # Разбиваем на части если сообщение слишком длинное
        if len(message) > 4000:
            parts = []
            current_part = ""
            
            for line in message.split('\n'):
                if len(current_part) + len(line) + 1 > 4000:
                    parts.append(current_part)
                    current_part = line + '\n'
                else:
                    current_part += line + '\n'
            
            if current_part:
                parts.append(current_part)
            
            for part in parts:
                await update.message.reply_text(part)
        else:
            await update.message.reply_text(message)
        
        # Кнопки действий - показываем кнопки для каждого розыгрыша
        keyboard = []
        
        # Добавляем кнопки просмотра для каждого розыгрыша (максимум 10)
        for giveaway in giveaways[:10]:
            status_emoji = "✅" if giveaway.is_active else "🔴"
            published_emoji = "📢" if giveaway.is_published else "📝"
            button_text = f"{status_emoji}{published_emoji} #{giveaway.id}: {giveaway.title[:30]}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"view_giveaway_{giveaway.id}")])
        
        # Кнопка создания нового
        keyboard.append([InlineKeyboardButton("➕ Создать новый розыгрыш", callback_data="create_new_giveaway")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🔍 Выберите розыгрыш для просмотра:",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Error listing giveaways: {e}")
        await update.message.reply_text(
            f"❌ Ошибка при получении списка розыгрышей: {str(e)}"
        )
    finally:
        await db.close()


@admin_only
async def view_giveaway(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Просмотр подробной информации о розыгрыше.
    
    Использование: /view_giveaway <id>
    """
    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            "❌ Использование: /view_giveaway <id>\n"
            "Пример: /view_giveaway 1"
        )
        return
    
    try:
        giveaway_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID розыгрыша должен быть числом.")
        return
    
    db = Database(settings.DATABASE_URL)
    
    try:
        giveaway = await db.get_giveaway_by_id(giveaway_id)
        
        if not giveaway:
            await update.message.reply_text(
                f"❌ Розыгрыш #{giveaway_id} не найден."
            )
            return
        
        # Формируем детальное сообщение
        text = f"🎉 Розыгрыш #{giveaway.id}\n\n"
        text += f"📝 {giveaway.title}\n\n"
        
        if giveaway.description:
            text += f"{giveaway.description}\n\n"
        
        text += f"🏆 Призы: {giveaway.prizes or 'Не указаны'}\n"
        text += f"👥 Победителей: {giveaway.winners_count}\n"
        
        # Получаем количество участников
        participants_count = await db.get_participants_count(giveaway.id)
        if giveaway.max_participants:
            text += f"📊 Участников: {participants_count}/{giveaway.max_participants}\n"
        else:
            text += f"📊 Участников: {participants_count} (без ограничений)\n"
        
        if giveaway.participation_rules:
            text += f"\n📋 Условия участия:\n{giveaway.participation_rules}\n"
        
        text += "\n⏰ Временные рамки:\n"
        if giveaway.starts_at:
            text += f"├ Начало: {giveaway.starts_at.strftime('%d.%m.%Y %H:%M')}\n"
        if giveaway.ends_at:
            text += f"├ Окончание: {giveaway.ends_at.strftime('%d.%m.%Y %H:%M')}\n"
        if giveaway.announce_at:
            text += f"└ Анонс: {giveaway.announce_at.strftime('%d.%m.%Y %H:%M')}\n"
        
        text += f"\n📊 Статус:\n"
        text += f"├ Активен: {'✅ Да' if giveaway.is_active else '❌ Нет'}\n"
        text += f"├ Опубликован: {'✅ Да' if giveaway.is_published else '📝 Черновик'}\n"
        text += f"└ Создан: {giveaway.created_at.strftime('%d.%m.%Y %H:%M')}\n"
        
        # Проверяем есть ли победители
        winners = await db.get_winners(giveaway.id)
        if winners:
            text += f"\n🏆 Победители уже выбраны: {len(winners)}\n"
        
        # Отправляем с картинкой если есть
        if giveaway.image_file_id:
            await update.message.reply_photo(
                photo=giveaway.image_file_id,
                caption=text
            )
        else:
            await update.message.reply_text(text)
        
        # Кнопки управления
        keyboard = []
        
        # Редактирование анонса только для неопубликованных
        if not giveaway.is_published:
            keyboard.append([InlineKeyboardButton("📝 Редактировать анонс", callback_data=f"edit_announcement_{giveaway_id}")])
        
        # Кнопка публикации всегда доступна
        button_text = "📢 Опубликовать" if not giveaway.is_published else "🔄 Опубликовать повторно"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"publish_{giveaway_id}")])
        keyboard.append([InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_{giveaway_id}")])
        
        # Кнопка розыгрыша (если есть участники и еще не выбраны победители)
        if participants_count > 0 and not winners:
            keyboard.append([InlineKeyboardButton("🎲 Провести розыгрыш", callback_data=f"draw_winners_{giveaway_id}")])
        elif winners:
            keyboard.append([InlineKeyboardButton("🔄 Провести заново", callback_data=f"draw_winners_{giveaway_id}")])
            keyboard.append([InlineKeyboardButton("📢 Уведомить победителей", callback_data=f"notify_winners_{giveaway_id}")])
        
        keyboard.append([InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_{giveaway_id}")])
        keyboard.append([InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_{giveaway_id}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "Управление розыгрышем:",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Error viewing giveaway: {e}")
        await update.message.reply_text(
            f"❌ Ошибка при получении информации о розыгрыше: {str(e)}"
        )
    finally:
        await db.close()


def _build_edit_menu(giveaway_id: int) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("🕐 Изменить начало", callback_data=f"edit_field_starts_at_{giveaway_id}")],
        [InlineKeyboardButton("⏰ Изменить окончание", callback_data=f"edit_field_ends_at_{giveaway_id}")],
        [InlineKeyboardButton("📢 Изменить время анонса", callback_data=f"edit_field_announce_at_{giveaway_id}")],
        [InlineKeyboardButton("👥 Кол-во победителей", callback_data=f"edit_field_winners_count_{giveaway_id}")],
        [InlineKeyboardButton("📊 Лимит участников", callback_data=f"edit_field_max_participants_{giveaway_id}")],
        [InlineKeyboardButton("🎯 Целевые чаты", callback_data=f"edit_field_target_chats_{giveaway_id}")],
        [InlineKeyboardButton("📌 Обязательные каналы", callback_data=f"edit_field_required_channels_{giveaway_id}")],
        [InlineKeyboardButton("🟢/🔴 Активность", callback_data=f"toggle_active_{giveaway_id}")],
        [InlineKeyboardButton("✅ Готово", callback_data=f"finish_edit_{giveaway_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)


@admin_only
async def edit_giveaway(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда редактирования розыгрыша: /edit_giveaway <id>."""
    if not context.args:
        await update.message.reply_text("❌ Использование: /edit_giveaway <id>\nПример: /edit_giveaway 5")
        return

    try:
        giveaway_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID розыгрыша должен быть числом.")
        return

    db = Database(settings.DATABASE_URL)
    try:
        giveaway = await db.get_giveaway_by_id(giveaway_id)
        if not giveaway:
            await update.message.reply_text(f"❌ Розыгрыш #{giveaway_id} не найден.")
            return

        await update.message.reply_text(
            f"✏️ Редактирование розыгрыша #{giveaway_id}: {giveaway.title}\n"
            "Выберите параметр для изменения:",
            reply_markup=_build_edit_menu(giveaway_id)
        )
    finally:
        await db.close()


@admin_only
async def view_giveaway_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Просмотр подробной информации о розыгрыше через callback кнопку.
    
    Callback data: view_giveaway_<id>
    """
    query = update.callback_query
    await query.answer()
    
    # Извлекаем ID из callback_data
    try:
        giveaway_id = int(query.data.split('_')[-1])
    except (ValueError, IndexError):
        await query.edit_message_text("❌ Неверный формат ID розыгрыша.")
        return
    
    db = Database(settings.DATABASE_URL)
    
    try:
        giveaway = await db.get_giveaway_by_id(giveaway_id)
        
        if not giveaway:
            await query.edit_message_text(f"❌ Розыгрыш #{giveaway_id} не найден.")
            return
        
        # Формируем детальное сообщение
        text = f"🎉 Розыгрыш #{giveaway.id}\n\n"
        text += f"📝 <b>{giveaway.title}</b>\n\n"
        
        if giveaway.description:
            text += f"{giveaway.description}\n\n"
        
        text += f"🏆 Призы: {giveaway.prizes or 'Не указаны'}\n"
        text += f"👥 Победителей: {giveaway.winners_count}\n"
        
        # Получаем количество участников
        participants_count = await db.get_participants_count(giveaway.id)
        if giveaway.max_participants:
            text += f"📊 Участников: {participants_count}/{giveaway.max_participants}\n"
        else:
            text += f"📊 Участников: {participants_count} (без ограничений)\n"
        
        if giveaway.participation_rules:
            text += f"\n📋 Условия участия:\n{giveaway.participation_rules}\n"
        
        text += "\n⏰ Временные рамки:\n"
        if giveaway.starts_at:
            text += f"├ Начало: {giveaway.starts_at.strftime('%d.%m.%Y %H:%M')}\n"
        if giveaway.ends_at:
            text += f"├ Окончание: {giveaway.ends_at.strftime('%d.%m.%Y %H:%M')}\n"
        if giveaway.announce_at:
            text += f"└ Анонс: {giveaway.announce_at.strftime('%d.%m.%Y %H:%M')}\n"
        
        text += f"\n📊 Статус:\n"
        text += f"├ Активен: {'✅ Да' if giveaway.is_active else '❌ Нет'}\n"
        text += f"├ Опубликован: {'✅ Да' if giveaway.is_published else '📝 Черновик'}\n"
        text += f"└ Создан: {giveaway.created_at.strftime('%d.%m.%Y %H:%M')}\n"
        
        # Проверяем есть ли победители
        winners = await db.get_winners(giveaway.id)
        if winners:
            text += f"\n🏆 Победители уже выбраны: {len(winners)}\n"
        
        # Кнопки управления
        keyboard = []
        
        # Редактирование анонса только для неопубликованных
        if not giveaway.is_published:
            keyboard.append([InlineKeyboardButton("📝 Редактировать анонс", callback_data=f"edit_announcement_{giveaway_id}")])
        
        # Кнопка публикации всегда доступна
        button_text = "📢 Опубликовать" if not giveaway.is_published else "🔄 Опубликовать повторно"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"publish_{giveaway_id}")])
        
        # Кнопка розыгрыша (если есть участники и еще не выбраны победители)
        if participants_count > 0 and not winners:
            keyboard.append([InlineKeyboardButton("🎲 Провести розыгрыш", callback_data=f"draw_winners_{giveaway_id}")])
        elif winners:
            keyboard.append([InlineKeyboardButton("🔄 Провести заново", callback_data=f"draw_winners_{giveaway_id}")])
            keyboard.append([InlineKeyboardButton("📢 Уведомить победителей", callback_data=f"notify_winners_{giveaway_id}")])

        keyboard.append([InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_{giveaway_id}")])
        keyboard.append([InlineKeyboardButton("🔙 Назад к списку", callback_data="back_to_list")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Отправляем с картинкой если есть
        if giveaway.image_file_id:
            # Удаляем старое сообщение и отправляем новое с фото
            await query.message.delete()
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=giveaway.image_file_id,
                caption=text,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        else:
            await query.edit_message_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        
    except Exception as e:
        logger.error(f"Error viewing giveaway callback: {e}")
        await query.edit_message_text(f"❌ Ошибка при получении информации о розыгрыше: {str(e)}")
    finally:
        await db.close()


@admin_only
async def edit_giveaway_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Открыть меню редактирования по кнопке edit_<id>."""
    query = update.callback_query
    await query.answer()

    try:
        giveaway_id = int(query.data.split('_')[-1])
    except (ValueError, IndexError):
        await query.edit_message_text("❌ Неверный формат ID розыгрыша.")
        return

    db = Database(settings.DATABASE_URL)
    try:
        giveaway = await db.get_giveaway_by_id(giveaway_id)
        if not giveaway:
            await query.edit_message_text(f"❌ Розыгрыш #{giveaway_id} не найден.")
            return

        await query.edit_message_text(
            f"✏️ Редактирование розыгрыша #{giveaway_id}: {giveaway.title}\n"
            "Выберите параметр для изменения:",
            reply_markup=_build_edit_menu(giveaway_id)
        )
    finally:
        await db.close()


@admin_only
async def edit_field_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Выбор конкретного поля для редактирования."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_")
    if len(parts) < 5:
        await query.edit_message_text("❌ Неверный формат команды редактирования.")
        return

    field = "_".join(parts[2:-1])  # starts_at / ends_at / announce_at / ...
    try:
        giveaway_id = int(parts[-1])
    except ValueError:
        await query.edit_message_text("❌ Неверный ID розыгрыша.")
        return

    context.user_data["editing_giveaway_field"] = {
        "giveaway_id": giveaway_id,
        "field": field
    }

    prompts = {
        "starts_at": (
            "Введите новое время начала в формате `ДД.ММ.ГГГГ ЧЧ:ММ`\n"
            "Пример: `21.02.2026 12:00`"
        ),
        "ends_at": (
            "Введите новое время окончания в формате `ДД.ММ.ГГГГ ЧЧ:ММ`\n"
            "Пример: `28.02.2026 23:59`"
        ),
        "announce_at": (
            "Введите новое время анонса в формате `ДД.ММ.ГГГГ ЧЧ:ММ`\n"
            "или `none`, чтобы отключить авто-анонс."
        ),
        "winners_count": "Введите новое количество победителей (целое число > 0).",
        "max_participants": "Введите лимит участников (целое число > 0) или `none` для безлимита.",
        "target_chats": "Введите chat_id через запятую. Пример: `-100123,-100456`",
        "required_channels": "Введите обязательные каналы через запятую или `none`.",
    }
    prompt = prompts.get(field, "Введите новое значение:")

    await query.edit_message_text(
        f"✏️ Поле: `{field}`\n\n{prompt}",
        parse_mode="Markdown"
    )


@admin_only
async def toggle_active_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Переключение активности розыгрыша."""
    query = update.callback_query
    await query.answer()

    try:
        giveaway_id = int(query.data.split("_")[-1])
    except (ValueError, IndexError):
        await query.edit_message_text("❌ Неверный формат ID.")
        return

    db = Database(settings.DATABASE_URL)
    try:
        giveaway = await db.get_giveaway_by_id(giveaway_id)
        if not giveaway:
            await query.edit_message_text(f"❌ Розыгрыш #{giveaway_id} не найден.")
            return
        new_state = not giveaway.is_active
        await db.update_giveaway(giveaway_id, is_active=new_state)
        await query.edit_message_text(
            f"✅ Статус розыгрыша #{giveaway_id}: {'Активен' if new_state else 'Неактивен'}",
            reply_markup=_build_edit_menu(giveaway_id)
        )
    finally:
        await db.close()


@admin_only
async def finish_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Завершение режима редактирования."""
    query = update.callback_query
    await query.answer()
    context.user_data.pop("editing_giveaway_field", None)
    await query.edit_message_text(
        "✅ Редактирование завершено.\n"
        "Используйте /view_giveaway <id> для проверки или кнопку публикации для репоста."
    )


@admin_only
async def save_edited_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Сохраняет измененное поле розыгрыша (ввод текстом)."""
    editing = context.user_data.get("editing_giveaway_field")
    if not editing:
        return

    giveaway_id = editing["giveaway_id"]
    field = editing["field"]
    raw_value = (update.message.text or "").strip()

    db = Database(settings.DATABASE_URL)
    try:
        giveaway = await db.get_giveaway_by_id(giveaway_id)
        if not giveaway:
            await update.message.reply_text(f"❌ Розыгрыш #{giveaway_id} не найден.")
            context.user_data.pop("editing_giveaway_field", None)
            return

        update_data = {}

        if field in {"starts_at", "ends_at", "announce_at"}:
            if field == "announce_at" and raw_value.lower() == "none":
                update_data[field] = None
            else:
                try:
                    parsed_dt = datetime.strptime(raw_value, DATETIME_INPUT_FORMAT)
                except ValueError:
                    await update.message.reply_text(
                        "❌ Неверный формат даты.\n"
                        "Используйте: ДД.ММ.ГГГГ ЧЧ:ММ"
                    )
                    return
                update_data[field] = parsed_dt

            starts_at = update_data.get("starts_at", giveaway.starts_at)
            ends_at = update_data.get("ends_at", giveaway.ends_at)
            if starts_at and ends_at and ends_at <= starts_at:
                await update.message.reply_text("❌ Окончание должно быть позже начала.")
                return

        elif field == "winners_count":
            try:
                value = int(raw_value)
                if value < 1:
                    raise ValueError
                update_data[field] = value
            except ValueError:
                await update.message.reply_text("❌ Введите целое число больше 0.")
                return

        elif field == "max_participants":
            if raw_value.lower() == "none":
                update_data[field] = None
            else:
                try:
                    value = int(raw_value)
                    if value < 1:
                        raise ValueError
                    update_data[field] = value
                except ValueError:
                    await update.message.reply_text("❌ Введите целое число больше 0 или `none`.", parse_mode="Markdown")
                    return

        elif field in {"target_chats", "required_channels"}:
            if field == "required_channels" and raw_value.lower() == "none":
                update_data[field] = None
            else:
                try:
                    values = [int(item.strip()) for item in raw_value.split(",") if item.strip()]
                    if not values:
                        raise ValueError
                    update_data[field] = values
                except ValueError:
                    await update.message.reply_text("❌ Введите корректные числовые chat_id через запятую.")
                    return

        else:
            await update.message.reply_text(f"❌ Поле `{field}` пока не поддерживается.", parse_mode="Markdown")
            context.user_data.pop("editing_giveaway_field", None)
            return

        # Если меняем жизненный цикл розыгрыша, делаем его снова активным
        if any(key in update_data for key in ("starts_at", "ends_at")):
            update_data["is_active"] = True
            # При сдвиге периода очищаем победителей прошлой итерации.
            await db.set_winners(giveaway_id, [])

        await db.update_giveaway(giveaway_id, **update_data)

        context.user_data.pop("editing_giveaway_field", None)
        await update.message.reply_text(
            f"✅ Поле `{field}` обновлено для розыгрыша #{giveaway_id}.",
            parse_mode="Markdown"
        )
        await update.message.reply_text(
            "Можно продолжить редактирование:",
            reply_markup=_build_edit_menu(giveaway_id)
        )
    except Exception as e:
        logger.error(f"Error saving edited field for giveaway {giveaway_id}: {e}")
        await update.message.reply_text(f"❌ Ошибка при сохранении: {str(e)}")
    finally:
        await db.close()
@admin_only
async def publish_giveaway(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Публикация розыгрыша в целевые чаты."""
    query = update.callback_query
    await query.answer()
    
    # Получаем ID розыгрыша из callback_data
    giveaway_id = int(query.data.split('_')[1])
    
    db = Database(settings.DATABASE_URL)
    
    try:
        giveaway = await db.get_giveaway(giveaway_id)
        
        if not giveaway:
            await _safe_callback_text(query, context, "❌ Розыгрыш не найден")
            return

        now = datetime.utcnow()
        if giveaway.ends_at and giveaway.ends_at <= now:
            await _safe_callback_text(
                query,
                context,
                "⛔️ Нельзя публиковать завершённый розыгрыш.\n\n"
                f"Окончание розыгрыша: {giveaway.ends_at.strftime('%d.%m.%Y %H:%M')} UTC\n"
                f"Текущее время: {now.strftime('%d.%m.%Y %H:%M')} UTC\n\n"
                "Обновите даты через ✏️ Редактировать (начала/окончания), затем публикуйте снова."
            )
            return

        if giveaway.starts_at and giveaway.ends_at and giveaway.ends_at <= giveaway.starts_at:
            await _safe_callback_text(
                query,
                context,
                "❌ Некорректные даты розыгрыша: окончание должно быть позже начала.\n"
                "Исправьте даты через ✏️ Редактировать."
            )
            return
        
        # Убрали проверку is_published - теперь можно публиковать повторно
        
        if not giveaway.target_chats or len(giveaway.target_chats) == 0:
            await _safe_callback_text(
                query,
                context,
                "⚠️ Не указаны целевые чаты для публикации.\n\n"
                "Отредактируйте розыгрыш и добавьте целевые чаты."
            )
            return
        
        # Формируем текст анонса
        announcement_text = giveaway.announcement_text or _format_announcement_text(giveaway)
        
        # Публикуем в каждый целевой чат
        success_count = 0
        failed_chats = []
        
        # Создаём кнопку для участия
        keyboard = [[InlineKeyboardButton("🎁 Участвовать в розыгрыше", callback_data=f"join_{giveaway_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        for chat_id in giveaway.target_chats:
            try:
                if giveaway.image_file_id:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=giveaway.image_file_id,
                        caption=announcement_text,
                        reply_markup=reply_markup,
                        parse_mode='HTML'
                    )
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=announcement_text,
                        reply_markup=reply_markup,
                        parse_mode='HTML'
                    )
                success_count += 1
                logger.info(f"Published giveaway {giveaway_id} to chat {chat_id}")
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Error publishing to chat {chat_id}: {error_msg}")
                
                # Определяем тип ошибки
                if "bot was kicked" in error_msg.lower():
                    failed_chats.append(f"{chat_id} (бот удален из чата)")
                elif "chat not found" in error_msg.lower():
                    failed_chats.append(f"{chat_id} (чат не найден)")
                elif "not enough rights" in error_msg.lower() or "have no rights" in error_msg.lower():
                    failed_chats.append(f"{chat_id} (нет прав на публикацию)")
                elif "bot is not a member" in error_msg.lower():
                    failed_chats.append(f"{chat_id} (бот не в чате)")
                else:
                    failed_chats.append(f"{chat_id} ({error_msg[:50]})")
        
        # Обновляем статус публикации если хотя бы один чат успешно
        if success_count > 0:
            await db.update_giveaway(giveaway_id, is_published=True)
        
        # Формируем ответ
        # Удаляем старое сообщение (может быть с фото)
        try:
            await query.message.delete()
        except Exception as e:
            logger.warning(f"Could not delete message: {e}")
        
        # Отправляем новое сообщение с результатом
        if success_count == len(giveaway.target_chats):
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"✅ Розыгрыш #{giveaway_id} успешно опубликован!\n\n"
                     f"📢 Опубликовано в {success_count} чат(ов)"
            )
        elif success_count > 0:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"⚠️ Розыгрыш #{giveaway_id} частично опубликован\n\n"
                     f"✅ Успешно: {success_count}/{len(giveaway.target_chats)}\n"
                     f"❌ Ошибки:\n" + "\n".join([f"  • {chat}" for chat in failed_chats]) +
                     f"\n\n💡 Проверьте:\n"
                     f"1. Бот добавлен в чат как администратор\n"
                     f"2. У бота есть права на публикацию\n"
                     f"3. Chat ID указан правильно\n\n"
                     f"📖 Подробности: /help или см. SETUP_CHANNELS.md"
            )
        else:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"❌ Не удалось опубликовать розыгрыш #{giveaway_id}\n\n"
                     f"Ошибки во всех чатах:\n" + "\n".join([f"  • {chat}" for chat in failed_chats]) +
                     f"\n\n💡 Что проверить:\n"
                     f"1. Добавьте бота в канал/группу как администратора\n"
                     f"2. Дайте боту права на публикацию сообщений\n"
                     f"3. Проверьте правильность Chat ID (должен начинаться с `-`)\n"
                     f"4. Для каналов ID должен начинаться с `-100`\n\n"
                     f"📖 Подробная инструкция: SETUP_CHANNELS.md\n"
                     f"🆔 Получить Chat ID: @userinfobot или @getmyid_bot"
            )
    
    except Exception as e:
        logger.error(f"Error publishing giveaway: {e}")
        # Пытаемся удалить и отправить новое сообщение
        try:
            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"❌ Ошибка при публикации: {str(e)}"
            )
        except Exception:
            # Если удаление не удалось, пытаемся редактировать
            await _safe_callback_text(query, context, f"❌ Ошибка при публикации: {str(e)}")
    finally:
        await db.close()


def _format_announcement_text(giveaway) -> str:
    """Совместимость со старым именем функции."""
    return format_announcement_text(giveaway)


@admin_only
async def edit_announcement(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать текущий анонс и предложить редактировать."""
    query = update.callback_query
    await query.answer()
    
    # Получаем ID розыгрыша из callback_data
    giveaway_id = int(query.data.split('_')[2])
    
    db = Database(settings.DATABASE_URL)
    
    try:
        giveaway = await db.get_giveaway(giveaway_id)
        
        if not giveaway:
            # Удаляем старое сообщение (может быть с фото)
            try:
                await query.message.delete()
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="❌ Розыгрыш не найден"
                )
            except Exception:
                await query.edit_message_text("❌ Розыгрыш не найден")
            return
        
        if giveaway.is_published:
            # Удаляем старое сообщение (может быть с фото)
            try:
                await query.message.delete()
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="⚠️ Нельзя редактировать анонс опубликованного розыгрыша"
                )
            except Exception:
                await query.edit_message_text("⚠️ Нельзя редактировать анонс опубликованного розыгрыша")
            return
        
        # Формируем текущий или автоматический текст анонса
        current_announcement = giveaway.announcement_text or _format_announcement_text(giveaway)
        
        # Показываем текущий анонс
        message_text = (
            f"📝 <b>Текущий текст анонса для розыгрыша #{giveaway_id}:</b>\n\n"
            f"{current_announcement}\n\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"Отправьте новый текст анонса или нажмите кнопку ниже:"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔄 Сбросить на автоматический", callback_data=f"reset_announcement_{giveaway_id}")],
            [InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_edit_announcement_{giveaway_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Удаляем старое сообщение (может быть с фото) и отправляем новое
        try:
            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=message_text,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        except Exception:
            # Если удаление не удалось, пытаемся редактировать
            await query.edit_message_text(
                message_text,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        
        # Сохраняем ID в контекст для обработки следующего сообщения
        context.user_data['editing_announcement_for'] = giveaway_id
    
    except Exception as e:
        logger.error(f"Error editing announcement: {e}")
        # Пытаемся удалить и отправить новое сообщение
        try:
            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"❌ Ошибка при редактировании анонса: {str(e)}"
            )
        except Exception:
            # Если удаление не удалось, пытаемся редактировать
            try:
                await query.edit_message_text(f"❌ Ошибка при редактировании анонса: {str(e)}")
            except Exception:
                pass
    finally:
        await db.close()


@admin_only
async def save_new_announcement(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Сохранить новый текст анонса."""
    # Проверяем что пользователь в режиме редактирования анонса
    giveaway_id = context.user_data.get('editing_announcement_for')
    
    if not giveaway_id:
        return
    
    new_text = update.message.text
    
    if not new_text or len(new_text) < 10:
        await update.message.reply_text(
            "⚠️ Текст анонса слишком короткий. Минимум 10 символов."
        )
        return
    
    db = Database(settings.DATABASE_URL)
    
    try:
        giveaway = await db.get_giveaway(giveaway_id)
        
        if not giveaway:
            await update.message.reply_text("❌ Розыгрыш не найден")
            del context.user_data['editing_announcement_for']
            return
        
        if giveaway.is_published:
            await update.message.reply_text("⚠️ Нельзя редактировать анонс опубликованного розыгрыша")
            del context.user_data['editing_announcement_for']
            return
        
        # Обновляем текст анонса
        await db.update_giveaway(giveaway_id, announcement_text=new_text)
        
        await update.message.reply_text(
            f"✅ Текст анонса для розыгрыша #{giveaway_id} обновлен!\n\n"
            f"📝 Новый текст:\n{new_text[:200]}{'...' if len(new_text) > 200 else ''}\n\n"
            f"Используйте /view_giveaway {giveaway_id} для просмотра"
        )
        
        # Очищаем режим редактирования
        del context.user_data['editing_announcement_for']
        
        logger.info(f"Updated announcement for giveaway {giveaway_id}")
    
    except Exception as e:
        logger.error(f"Error saving announcement: {e}")
        await update.message.reply_text(
            f"❌ Ошибка при сохранении анонса: {str(e)}"
        )
    finally:
        await db.close()


@admin_only
async def reset_announcement(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Сбросить анонс на автоматически сгенерированный."""
    query = update.callback_query
    await query.answer()
    
    # Получаем ID розыгрыша из callback_data
    giveaway_id = int(query.data.split('_')[2])
    
    db = Database(settings.DATABASE_URL)
    
    try:
        giveaway = await db.get_giveaway(giveaway_id)
        
        if not giveaway:
            # Удаляем старое сообщение и отправляем новое
            try:
                await query.message.delete()
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="❌ Розыгрыш не найден"
                )
            except Exception:
                await query.edit_message_text("❌ Розыгрыш не найден")
            return
        
        if giveaway.is_published:
            # Удаляем старое сообщение и отправляем новое
            try:
                await query.message.delete()
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="⚠️ Нельзя редактировать анонс опубликованного розыгрыша"
                )
            except Exception:
                await query.edit_message_text("⚠️ Нельзя редактировать анонс опубликованного розыгрыша")
            return
        
        # Сбрасываем кастомный текст (будет использован автоматический)
        await db.update_giveaway(giveaway_id, announcement_text=None)
        
        # Генерируем автоматический текст для показа
        auto_text = _format_announcement_text(giveaway)
        
        message_text = (
            f"✅ Текст анонса сброшен на автоматический!\n\n"
            f"📝 Будет использован такой текст:\n\n{auto_text}\n\n"
            f"Используйте /view_giveaway {giveaway_id} для просмотра"
        )
        
        # Удаляем старое сообщение и отправляем новое
        try:
            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=message_text
            )
        except Exception:
            await query.edit_message_text(message_text)
        
        # Очищаем режим редактирования
        if 'editing_announcement_for' in context.user_data:
            del context.user_data['editing_announcement_for']
        
        logger.info(f"Reset announcement for giveaway {giveaway_id}")
    
    except Exception as e:
        logger.error(f"Error resetting announcement: {e}")
        # Пытаемся удалить и отправить новое сообщение
        try:
            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"❌ Ошибка при сбросе анонса: {str(e)}"
            )
        except Exception:
            try:
                await query.edit_message_text(f"❌ Ошибка при сбросе анонса: {str(e)}")
            except Exception:
                pass
    finally:
        await db.close()


@admin_only
async def cancel_edit_announcement(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отменить редактирование анонса."""
    query = update.callback_query
    await query.answer()
    
    # Очищаем режим редактирования
    if 'editing_announcement_for' in context.user_data:
        del context.user_data['editing_announcement_for']
    
    message_text = (
        "❌ Редактирование анонса отменено.\n\n"
        "Используйте /list_giveaways для просмотра списка розыгрышей."
    )
    
    # Удаляем старое сообщение и отправляем новое
    try:
        await query.message.delete()
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=message_text
        )
    except Exception:
        await query.edit_message_text(message_text)


@admin_only
async def back_to_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Возврат к списку розыгрышей."""
    query = update.callback_query
    await query.answer()
    
    db = Database(settings.DATABASE_URL)
    
    try:
        giveaways = await db.get_all_giveaways()
        
        if not giveaways:
            await query.edit_message_text(
                "📋 Розыгрышей пока нет.\n\n"
                "Создайте первый розыгрыш командой /create_giveaway"
            )
            return
        
        message = f"📋 Всего розыгрышей: {len(giveaways)}\n\n"
        
        for giveaway in giveaways[:5]:  # Показываем первые 5 в тексте
            status_emoji = "✅" if giveaway.is_active else "🔴"
            published_emoji = "📢" if giveaway.is_published else "📝"
            
            message += f"{status_emoji} {published_emoji} <b>#{giveaway.id}</b> - {giveaway.title}\n"
            
            # Участники
            participants_count = await db.get_participants_count(giveaway.id)
            if giveaway.max_participants:
                message += f"└ 👥 {participants_count}/{giveaway.max_participants}\n\n"
            else:
                message += f"└ 👥 {participants_count}\n\n"
        
        # Кнопки для каждого розыгрыша
        keyboard = []
        
        for giveaway in giveaways[:10]:
            status_emoji = "✅" if giveaway.is_active else "🔴"
            published_emoji = "📢" if giveaway.is_published else "📝"
            button_text = f"{status_emoji}{published_emoji} #{giveaway.id}: {giveaway.title[:30]}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"view_giveaway_{giveaway.id}")])
        
        keyboard.append([InlineKeyboardButton("➕ Создать новый розыгрыш", callback_data="create_new_giveaway")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        list_text = message + "\n🔍 Выберите розыгрыш для просмотра:"

        # Если callback пришел из сообщения с фото/подписью, edit_message_text может не сработать.
        # В этом случае удаляем текущее сообщение и отправляем новое с текстом списка.
        try:
            await query.edit_message_text(
                list_text,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        except Exception:
            try:
                await query.message.delete()
            except Exception:
                pass
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=list_text,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        
    except Exception as e:
        logger.error(f"Error in back_to_list: {e}")
        await query.edit_message_text(f"❌ Ошибка: {str(e)}")
    finally:
        await db.close()


@admin_only
async def delete_giveaway_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запрос подтверждения удаления розыгрыша по кнопке."""
    query = update.callback_query
    await query.answer()

    try:
        giveaway_id = int(query.data.split('_')[-1])
    except (ValueError, IndexError):
        await _safe_callback_text(query, context, "❌ Неверный формат ID розыгрыша.")
        return

    keyboard = [
        [InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_delete_{giveaway_id}")],
        [InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_delete_{giveaway_id}")]
    ]
    await _safe_callback_text(
        query,
        context,
        f"⚠️ Вы уверены, что хотите удалить розыгрыш #{giveaway_id}?\n"
        "Будут удалены и все записи об участниках.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


@admin_only
async def confirm_delete_giveaway(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Подтверждение удаления розыгрыша по кнопке."""
    query = update.callback_query
    await query.answer()

    try:
        giveaway_id = int(query.data.split('_')[-1])
    except (ValueError, IndexError):
        await _safe_callback_text(query, context, "❌ Неверный формат ID розыгрыша.")
        return

    db = Database(settings.DATABASE_URL)
    try:
        deleted, participants_deleted = await db.delete_giveaway(giveaway_id)
        if not deleted:
            await _safe_callback_text(query, context, f"❌ Розыгрыш #{giveaway_id} не найден.")
            return

        await _safe_callback_text(
            query,
            context,
            f"🗑 Розыгрыш #{giveaway_id} удалён.\n"
            f"Удалено участников: {participants_deleted}"
        )
    except Exception as e:
        logger.error(f"Error deleting giveaway {giveaway_id}: {e}")
        await _safe_callback_text(query, context, f"❌ Ошибка при удалении: {str(e)}")
    finally:
        await db.close()


@admin_only
async def cancel_delete_giveaway(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отмена удаления розыгрыша по кнопке."""
    query = update.callback_query
    await query.answer("Удаление отменено")
    await _safe_callback_text(query, context, "❌ Удаление отменено.")


@admin_only
async def delete_giveaways(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Удаление одного или нескольких розыгрышей по ID.

    Использование:
    - /delete_giveaway <id>
    - /delete_giveaways <id1,id2,id3>
    """
    if not context.args:
        await update.message.reply_text(
            "❌ Использование:\n"
            "/delete_giveaway <id>\n"
            "/delete_giveaways <id1,id2,...>"
        )
        return

    raw = " ".join(context.args).replace(" ", "")
    try:
        ids = [int(item) for item in raw.split(",") if item]
    except ValueError:
        await update.message.reply_text("❌ ID должны быть числами. Пример: /delete_giveaways 3,5,8")
        return

    if not ids:
        await update.message.reply_text("❌ Не переданы ID для удаления.")
        return

    db = Database(settings.DATABASE_URL)
    try:
        deleted_ids = []
        not_found_ids = []
        participants_deleted_total = 0

        for giveaway_id in ids:
            deleted, participants_deleted = await db.delete_giveaway(giveaway_id)
            if deleted:
                deleted_ids.append(giveaway_id)
                participants_deleted_total += participants_deleted
            else:
                not_found_ids.append(giveaway_id)

        lines = []
        if deleted_ids:
            lines.append(f"🗑 Удалены розыгрыши: {', '.join(map(str, deleted_ids))}")
            lines.append(f"👥 Удалено записей участия: {participants_deleted_total}")
        if not_found_ids:
            lines.append(f"⚠️ Не найдены: {', '.join(map(str, not_found_ids))}")

        await update.message.reply_text("\n".join(lines) if lines else "⚠️ Нечего удалять.")
    except Exception as e:
        logger.error(f"Error deleting giveaways: {e}")
        await update.message.reply_text(f"❌ Ошибка при удалении: {str(e)}")
    finally:
        await db.close()


@admin_only
async def draw_winners(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Провести розыгрыш и выбрать победителей.
    
    Использование: /draw_winners <id>
    """
    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            "❌ Использование: /draw_winners <id>\n"
            "Пример: /draw_winners 1"
        )
        return

    try:
        giveaway_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID розыгрыша должен быть числом.")
        return

    await _run_draw_command(
        update=update,
        context=context,
        giveaway_id=giveaway_id,
        allow_less=False,
        redraw=False
    )


@admin_only
async def draw_winners_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Провести розыгрыш через callback кнопку."""
    query = update.callback_query
    await query.answer()
    
    # Извлекаем ID из callback_data
    try:
        giveaway_id = int(query.data.split('_')[-1])
    except (ValueError, IndexError):
        await query.edit_message_text("❌ Неверный формат ID розыгрыша.")
        return
    
    db = Database(settings.DATABASE_URL)

    try:
        result = await _draw_winners_core(
            db=db,
            giveaway_id=giveaway_id,
            allow_less=False,
            redraw=False
        )
        if not result["ok"]:
            await query.edit_message_text(result["message"])
            return

        text = await _build_winners_text(
            db=db,
            giveaway=result["giveaway"],
            participants_count=result["participants_count"],
            winners=result["winners"]
        )

        keyboard = [
            [InlineKeyboardButton("📢 Уведомить победителей", callback_data=f"notify_winners_{giveaway_id}")],
            [InlineKeyboardButton("🔙 Назад к списку", callback_data="back_to_list")]
        ]
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Error drawing winners callback: {e}")
        await query.edit_message_text(f"❌ Ошибка: {str(e)}")
    finally:
        await db.close()


@admin_only
async def notify_winners(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправить уведомления победителям."""
    query = update.callback_query
    await query.answer()
    
    # Извлекаем ID из callback_data
    try:
        giveaway_id = int(query.data.split('_')[-1])
    except (ValueError, IndexError):
        await query.edit_message_text("❌ Неверный формат ID розыгрыша.")
        return
    
    db = Database(settings.DATABASE_URL)

    try:
        giveaway = await db.get_giveaway_by_id(giveaway_id)
        if not giveaway:
            await query.edit_message_text(f"❌ Розыгрыш #{giveaway_id} не найден.")
            return

        winners = await db.get_winners(giveaway_id)
        if not winners:
            await query.edit_message_text(
                f"❌ Победители еще не выбраны!\n"
                f"Используйте /draw_winners {giveaway_id}"
            )
            return

        success_count, failed_count = await _notify_winners_direct(
            bot=context.bot,
            db=db,
            giveaway=giveaway,
            winners=winners
        )
        text = f"✅ Уведомления отправлены!\n\n📤 Успешно: {success_count}"
        if failed_count > 0:
            text += f"\n❌ Не удалось: {failed_count}"
        await query.edit_message_text(text)
    except Exception as e:
        logger.error(f"Error notifying winners: {e}")
        await query.edit_message_text(f"❌ Ошибка: {str(e)}")
    finally:
        await db.close()


@admin_only
async def force_draw(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Принудительный розыгрыш: если участников меньше, выбирает всех."""
    if not context.args:
        await update.message.reply_text("❌ Использование: /force_draw <id>\nПример: /force_draw 1")
        return
    try:
        giveaway_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID розыгрыша должен быть числом.")
        return
    await _run_draw_command(update, context, giveaway_id, allow_less=True, redraw=False)


@admin_only
async def redraw_winners(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Повторный розыгрыш с перезаписью победителей."""
    if not context.args:
        await update.message.reply_text("❌ Использование: /redraw_winners <id>\nПример: /redraw_winners 1")
        return
    try:
        giveaway_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID розыгрыша должен быть числом.")
        return
    await _run_draw_command(update, context, giveaway_id, allow_less=True, redraw=True)


@admin_only
async def force_draw_legacy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Совместимость с подсказкой формата /force_draw_<id>."""
    text = (update.message.text or "").split("@")[0]
    try:
        giveaway_id = int(text.split("_")[-1])
    except ValueError:
        await update.message.reply_text("❌ Неверный формат. Используйте /force_draw <id>")
        return
    await _run_draw_command(update, context, giveaway_id, allow_less=True, redraw=False)


async def _run_draw_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    giveaway_id: int,
    allow_less: bool,
    redraw: bool
) -> None:
    db = Database(settings.DATABASE_URL)
    try:
        result = await _draw_winners_core(
            db=db,
            giveaway_id=giveaway_id,
            allow_less=allow_less,
            redraw=redraw
        )
        if not result["ok"]:
            await update.message.reply_text(result["message"])
            return

        text = await _build_winners_text(
            db=db,
            giveaway=result["giveaway"],
            participants_count=result["participants_count"],
            winners=result["winners"]
        )
        await update.message.reply_text(text, parse_mode='HTML')

        keyboard = [[InlineKeyboardButton("📢 Уведомить победителей", callback_data=f"notify_winners_{giveaway_id}")]]
        await update.message.reply_text(
            "Хотите отправить уведомления победителям?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error("Error in draw command: %s", e, exc_info=True)
        await update.message.reply_text(f"❌ Ошибка при проведении розыгрыша: {e}")
    finally:
        await db.close()


async def _draw_winners_core(
    db: Database,
    giveaway_id: int,
    allow_less: bool,
    redraw: bool
):
    giveaway = await db.get_giveaway_by_id(giveaway_id)
    if not giveaway:
        return {"ok": False, "message": f"❌ Розыгрыш #{giveaway_id} не найден."}

    if giveaway.ends_at and giveaway.ends_at > datetime.utcnow():
        return {
            "ok": False,
            "message": (
                "⚠️ Розыгрыш еще не завершен!\n"
                f"Окончание: {giveaway.ends_at.strftime('%d.%m.%Y %H:%M')}"
            ),
        }

    participants = await db.get_participants(giveaway_id)
    if not participants:
        return {"ok": False, "message": f"❌ В розыгрыше #{giveaway_id} нет участников."}

    existing_winners = await db.get_winners(giveaway_id)
    if existing_winners and not redraw:
        return {
            "ok": False,
            "message": (
                "⚠️ Победители уже были выбраны!\n"
                f"Для повторного розыгрыша используйте: /redraw_winners {giveaway_id}"
            ),
        }

    if len(participants) < giveaway.winners_count and not allow_less:
        return {
            "ok": False,
            "message": (
                "⚠️ Недостаточно участников!\n"
                f"Участников: {len(participants)}\n"
                f"Нужно победителей: {giveaway.winners_count}\n\n"
                f"Выполнить принудительно: /force_draw {giveaway_id}"
            ),
        }

    winners_count = min(giveaway.winners_count, len(participants)) if allow_less else giveaway.winners_count
    winners = random.sample(participants, winners_count)
    await db.set_winners(giveaway_id, [item.user_id for item in winners])
    await db.update_giveaway(giveaway_id, is_active=False)

    return {
        "ok": True,
        "giveaway": giveaway,
        "participants_count": len(participants),
        "winners": winners,
    }


async def _build_winners_text(db: Database, giveaway, participants_count: int, winners) -> str:
    text = f"🎉 <b>Розыгрыш завершен!</b>\n\n"
    text += f"📝 {giveaway.title}\n"
    text += f"👥 Участников: {participants_count}\n"
    text += f"🏆 Победителей: {len(winners)}\n\n"
    text += "<b>🎊 Победители:</b>\n"

    for i, winner in enumerate(winners, 1):
        user = await db.get_user_by_id(winner.user_id)
        if not user:
            text += f"{i}. ID пользователя: {winner.user_id}\n"
            continue
        if user.username:
            text += f"{i}. @{user.username}\n"
        else:
            name = " ".join(filter(None, [user.first_name, user.last_name])).strip() or "Без имени"
            text += f"{i}. {name} (ID: {user.telegram_id})\n"
    return text


async def _notify_winners_direct(bot, db: Database, giveaway, winners):
    success_count = 0
    failed_count = 0
    for winner in winners:
        user = await db.get_user_by_id(winner.user_id)
        if not user:
            failed_count += 1
            continue
        try:
            message = (
                "🎉 <b>Поздравляем!</b>\n\n"
                "Вы стали победителем в розыгрыше:\n"
                f"📝 <b>{giveaway.title}</b>\n\n"
            )
            if giveaway.prizes:
                message += f"🏆 Ваш приз: {giveaway.prizes}\n\n"
            message += "Для получения приза свяжитесь с организатором."
            await bot.send_message(
                chat_id=user.telegram_id,
                text=message,
                parse_mode='HTML'
            )
            success_count += 1
        except Exception as e:
            logger.error(f"Failed to notify winner {user.telegram_id}: {e}")
            failed_count += 1
    return success_count, failed_count
