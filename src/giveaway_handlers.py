"""Обработчики для создания и управления розыгрышами."""

import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters
)
from telegram_bot_calendar import DetailedTelegramCalendar, LSTEP

from src.database import Database
from src.ollama_client import OllamaClient
from src.permissions import admin_only
from config import settings

logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
(
    MODE_SELECT,
    AI_BRIEF,
    AI_REVIEW,
    AI_FEEDBACK,
    TITLE,
    DESCRIPTION,
    PRIZES,
    TARGET_CHATS,
    IMAGE,
    WINNERS_COUNT,
    MAX_PARTICIPANTS,
    RULES,
    START_DATE,
    START_TIME,
    END_DATE,
    END_TIME,
    ANNOUNCE_DATE,
    ANNOUNCE_TIME,
    ANNOUNCEMENT_TEXT,
    PREVIEW,
    CONFIRM
) = range(21)


def _creation_mode_markup() -> InlineKeyboardMarkup:
    """Клавиатура выбора режима создания."""
    keyboard = [
        [InlineKeyboardButton("🧩 Самостоятельно", callback_data="creation_manual")],
        [InlineKeyboardButton("🤖 Автоматическое создание (AI)", callback_data="creation_ai")]
    ]
    return InlineKeyboardMarkup(keyboard)


@admin_only
async def create_giveaway_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало создания розыгрыша."""
    # Инициализируем данные розыгрыша в контексте
    context.user_data['giveaway'] = {}
    context.user_data.pop('ai_brief', None)
    context.user_data.pop('ai_draft', None)
    await update.message.reply_text(
        "🎉 Создание нового розыгрыша\n\n"
        "Выберите режим создания:",
        reply_markup=_creation_mode_markup()
    )
    return MODE_SELECT


@admin_only
async def start_create_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Старт создания розыгрыша по кнопке из /start-меню."""
    query = update.callback_query
    await query.answer()

    context.user_data['giveaway'] = {}
    context.user_data.pop('ai_brief', None)
    context.user_data.pop('ai_draft', None)

    await query.edit_message_text(
        "🎉 Создание нового розыгрыша\n\n"
        "Выберите режим создания:",
        reply_markup=_creation_mode_markup()
    )
    return MODE_SELECT


def _format_ai_draft(draft: dict) -> str:
    """Форматирование AI-черновика для согласования."""
    text = "🤖 AI подготовил черновик:\n\n"
    text += f"📝 Название:\n{draft.get('title', '')}\n\n"
    text += f"📄 Описание:\n{draft.get('description', '')}\n\n"
    text += f"🏆 Призы:\n{draft.get('prizes', '')}\n\n"
    text += f"📋 Условия участия:\n{draft.get('participation_rules', '')}\n"
    return text


async def _generate_ai_draft(context: ContextTypes.DEFAULT_TYPE, revision_request: str = None) -> dict:
    """Генерация/перегенерация черновика через Ollama."""
    if not settings.OLLAMA_ENABLED:
        raise RuntimeError("AI-режим отключен. Включите OLLAMA_ENABLED=true в .env")

    brief = context.user_data.get('ai_brief')
    if not brief:
        raise RuntimeError("Не найден brief для генерации")

    client = OllamaClient(
        base_url=settings.OLLAMA_BASE_URL,
        model=settings.OLLAMA_MODEL,
        timeout_seconds=settings.OLLAMA_TIMEOUT_SECONDS
    )

    current_draft = context.user_data.get('ai_draft')
    draft = await client.generate_giveaway_draft(
        brief=brief,
        revision_request=revision_request,
        current_draft=current_draft if revision_request else None
    )
    context.user_data['ai_draft'] = draft
    return draft


async def handle_creation_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбор режима создания розыгрыша."""
    query = update.callback_query
    await query.answer()

    if query.data == "creation_manual":
        await query.edit_message_text(
            "🧩 Самостоятельное создание выбрано.\n\n"
            "Шаг 1/11: Введите название розыгрыша:"
        )
        return TITLE

    if not settings.OLLAMA_ENABLED:
        await query.edit_message_text(
            "❌ AI-режим сейчас отключен (OLLAMA_ENABLED=false).\n\n"
            "Переключаемся на самостоятельное создание.\n"
            "Шаг 1/11: Введите название розыгрыша:"
        )
        return TITLE

    await query.edit_message_text(
        "🤖 Автоматическое создание выбрано.\n\n"
        "Опишите коротко задачу для AI:\n"
        "- тема/идея розыгрыша\n"
        "- что разыгрываем\n"
        "- целевая аудитория/тон\n\n"
        "Пример: \"Розыгрыш для подписчиков канала о маркетинге, приз: консультация и гайд, стиль дружелюбный\""
    )
    return AI_BRIEF


async def receive_ai_brief(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получение brief и первая генерация черновика."""
    brief = update.message.text.strip()
    if len(brief) < 12:
        await update.message.reply_text("❌ Слишком короткое описание. Добавьте больше деталей.")
        return AI_BRIEF

    context.user_data['ai_brief'] = brief
    await update.message.reply_text(
        f"⏳ Генерирую черновик через AI.\n"
        f"Это может занять до {settings.OLLAMA_TIMEOUT_SECONDS} секунд..."
    )

    try:
        draft = await _generate_ai_draft(context)
    except Exception as e:
        logger.error(f"AI draft generation failed: {e}")
        await update.message.reply_text(
            "❌ Не удалось сгенерировать черновик через AI.\n"
            f"Причина: {str(e)}\n\n"
            "Можно продолжить вручную: введите название розыгрыша."
        )
        return TITLE

    keyboard = [
        [InlineKeyboardButton("✅ Принять черновик", callback_data="accept_ai_draft")],
        [InlineKeyboardButton("🔁 Сгенерировать заново", callback_data="regenerate_ai_draft")],
        [InlineKeyboardButton("✍️ Внести правки через AI", callback_data="revise_ai_draft")],
        [InlineKeyboardButton("🧩 Перейти в ручной режим", callback_data="switch_manual")]
    ]
    await update.message.reply_text(
        _format_ai_draft(draft),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return AI_REVIEW


async def handle_ai_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Согласование AI-черновика."""
    query = update.callback_query
    await query.answer()

    if query.data == "switch_manual":
        await query.edit_message_text(
            "🧩 Переход в ручной режим.\n\n"
            "Шаг 1/11: Введите название розыгрыша:"
        )
        return TITLE

    if query.data == "accept_ai_draft":
        draft = context.user_data.get('ai_draft')
        if not draft:
            await query.edit_message_text("❌ Черновик не найден. Отправьте brief заново.")
            return AI_BRIEF

        context.user_data['giveaway']['title'] = draft.get('title')
        context.user_data['giveaway']['description'] = draft.get('description')
        context.user_data['giveaway']['prizes'] = draft.get('prizes')
        context.user_data['giveaway']['participation_rules'] = draft.get('participation_rules')

        await query.edit_message_text(
            "✅ Черновик принят и применён.\n\n"
            "Шаг 4/11: Введите ID каналов и чатов для публикации анонса.\n"
            "Формат: chat_id через запятую.\n"
            "Например: -1001234567890, -1009876543210"
        )
        return TARGET_CHATS

    if query.data == "regenerate_ai_draft":
        await query.edit_message_text(
            f"⏳ Перегенерирую черновик через AI.\n"
            f"Это может занять до {settings.OLLAMA_TIMEOUT_SECONDS} секунд..."
        )
        try:
            draft = await _generate_ai_draft(context)
        except Exception as e:
            logger.error(f"AI regenerate failed: {e}")
            await query.edit_message_text(
                "❌ Не удалось перегенерировать черновик.\n"
                f"Причина: {str(e)}\n\n"
                "Нажмите /create_giveaway и попробуйте снова."
            )
            return ConversationHandler.END

        keyboard = [
            [InlineKeyboardButton("✅ Принять черновик", callback_data="accept_ai_draft")],
            [InlineKeyboardButton("🔁 Сгенерировать заново", callback_data="regenerate_ai_draft")],
            [InlineKeyboardButton("✍️ Внести правки через AI", callback_data="revise_ai_draft")],
            [InlineKeyboardButton("🧩 Перейти в ручной режим", callback_data="switch_manual")]
        ]
        await query.edit_message_text(
            _format_ai_draft(draft),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return AI_REVIEW

    await query.edit_message_text(
        "✍️ Напишите, что именно нужно исправить в тексте/условиях.\n"
        "Пример: \"Сделай текст короче, добавь пункт о подписке на канал и дедлайн\""
    )
    return AI_FEEDBACK


async def receive_ai_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Применение правок администратора к AI-черновику."""
    revision_request = update.message.text.strip()
    if len(revision_request) < 5:
        await update.message.reply_text("❌ Слишком короткий запрос на правки. Уточните, что изменить.")
        return AI_FEEDBACK

    await update.message.reply_text(
        f"⏳ Применяю ваши правки через AI.\n"
        f"Это может занять до {settings.OLLAMA_TIMEOUT_SECONDS} секунд..."
    )

    try:
        draft = await _generate_ai_draft(context, revision_request=revision_request)
    except Exception as e:
        logger.error(f"AI revise failed: {e}")
        await update.message.reply_text(
            "❌ Не удалось применить правки через AI.\n"
            f"Причина: {str(e)}\n\n"
            "Напишите правки еще раз или переключитесь в ручной режим."
        )
        return AI_FEEDBACK

    keyboard = [
        [InlineKeyboardButton("✅ Принять черновик", callback_data="accept_ai_draft")],
        [InlineKeyboardButton("🔁 Сгенерировать заново", callback_data="regenerate_ai_draft")],
        [InlineKeyboardButton("✍️ Внести правки через AI", callback_data="revise_ai_draft")],
        [InlineKeyboardButton("🧩 Перейти в ручной режим", callback_data="switch_manual")]
    ]
    await update.message.reply_text(
        _format_ai_draft(draft),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return AI_REVIEW


async def set_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Установка названия розыгрыша."""
    title = update.message.text.strip()
    
    if len(title) < 3:
        await update.message.reply_text("❌ Название должно быть не менее 3 символов. Попробуйте снова:")
        return TITLE
    
    context.user_data['giveaway']['title'] = title
    
    keyboard = [[InlineKeyboardButton("➡️ Далее", callback_data="next_to_description")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"✅ Название: {title}\n\n"
        "Шаг 2/11: Введите описание розыгрыша:",
        reply_markup=reply_markup
    )
    
    return DESCRIPTION


async def set_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Установка описания розыгрыша."""
    description = update.message.text.strip()
    context.user_data['giveaway']['description'] = description
    
    keyboard = [
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_title")],
        [InlineKeyboardButton("➡️ Далее", callback_data="next_to_prizes")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"✅ Описание сохранено\n\n"
        "Шаг 3/11: Опишите призы (что получит победитель):",
        reply_markup=reply_markup
    )
    
    return PRIZES


async def set_prizes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Установка призов."""
    prizes = update.message.text.strip()
    context.user_data['giveaway']['prizes'] = prizes
    
    keyboard = [
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_description")],
        [InlineKeyboardButton("➡️ Далее", callback_data="next_to_target_chats")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "✅ Призы сохранены\n\n"
        "Шаг 4/11: Введите ID каналов и чатов для публикации анонса.\n"
        "Формат: укажите chat_id через запятую.\n"
        "Например: -1001234567890, -1009876543210\n\n"
        "Чтобы узнать chat_id:\n"
        "1. Для каналов: добавьте бота в канал как администратора\n"
        "2. Используйте @userinfobot для получения ID\n\n"
        "Или нажмите Далее для перехода к следующему шагу:",
        reply_markup=reply_markup
    )
    
    return TARGET_CHATS


async def set_target_chats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Установка целевых чатов для публикации."""
    text = update.message.text.strip()
    
    # Парсим chat_id
    try:
        chat_ids = [int(chat_id.strip()) for chat_id in text.split(',')]
        context.user_data['giveaway']['target_chats'] = chat_ids
        
        keyboard = [
            [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_prizes")],
            [InlineKeyboardButton("📷 Загрузить картинку", callback_data="upload_image")],
            [InlineKeyboardButton("⏭ Пропустить картинку", callback_data="skip_image")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"✅ Сохранено {len(chat_ids)} чат(ов)\n\n"
            "Шаг 5/11: Хотите добавить картинку к розыгрышу?",
            reply_markup=reply_markup
        )
        
        return IMAGE
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат!\n\n"
            "Введите ID чатов через запятую (числа).\n"
            "Например: -1001234567890, -1009876543210"
        )
        return TARGET_CHATS


async def handle_image_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора загрузки картинки."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "skip_image":
        await query.edit_message_text(
            "⏭ Картинка пропущена\n\n"
            "Шаг 6/11: Введите **количество победителей** (число):"
        )
        return WINNERS_COUNT
    
    await query.edit_message_text(
        "📷 Отправьте картинку для розыгрыша:"
    )
    return IMAGE


async def set_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохранение картинки."""
    if update.message.photo:
        try:
            # Берём самое большое разрешение
            photo = update.message.photo[-1]
            
            # Проверяем размер (Telegram ограничивает 10MB для фото)
            file = await context.bot.get_file(photo.file_id)
            file_size_mb = file.file_size / (1024 * 1024)
            
            if file_size_mb > 10:
                await update.message.reply_text(
                    f"❌ Картинка слишком большая ({file_size_mb:.1f} MB).\n"
                    "Максимальный размер: 10 MB\n\n"
                    "Пожалуйста, отправьте картинку меньшего размера или нажмите кнопку 'Пропустить'."
                )
                return IMAGE
            
            context.user_data['giveaway']['image_file_id'] = photo.file_id
            
            keyboard = [
                [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_target_chats")],
                [InlineKeyboardButton("➡️ Далее", callback_data="next_to_winners")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"✅ Картинка сохранена (размер: {file_size_mb:.1f} MB)\n\n"
                "Шаг 6/11: Введите количество победителей (число):",
                reply_markup=reply_markup
            )
            return WINNERS_COUNT
            
        except Exception as e:
            logger.error(f"Error processing image: {e}")
            await update.message.reply_text(
                f"❌ Ошибка при обработке картинки: {str(e)}\n\n"
                "Попробуйте отправить другую картинку или нажмите 'Пропустить'."
            )
            return IMAGE
    else:
        await update.message.reply_text(
            "❌ Пожалуйста, отправьте картинку или используйте кнопку 'Пропустить'."
        )
        return IMAGE


async def set_winners_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Установка количества победителей."""
    try:
        winners_count = int(update.message.text.strip())
        if winners_count < 1:
            raise ValueError
        
        context.user_data['giveaway']['winners_count'] = winners_count
        
        keyboard = [
            [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_image")],
            [InlineKeyboardButton("♾ Без ограничений", callback_data="unlimited_participants")],
            [InlineKeyboardButton("📝 Указать число", callback_data="set_max_participants")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"✅ Количество победителей: {winners_count}\n\n"
            "Шаг 7/11: Установить максимальное количество участников?",
            reply_markup=reply_markup
        )
        
        return MAX_PARTICIPANTS
        
    except ValueError:
        await update.message.reply_text(
            "❌ Пожалуйста, введите корректное число (больше 0):"
        )
        return WINNERS_COUNT


async def handle_max_participants_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора максимального количества участников."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "unlimited_participants":
        context.user_data['giveaway']['max_participants'] = None
        
        keyboard = [
            [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_winners")],
            [InlineKeyboardButton("➡️ Далее", callback_data="next_to_rules")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "✅ Без ограничений по участникам\n\n"
            "Шаг 8/11: Введите условия участия (например: 'Подписаться на канал @channel'):",
            reply_markup=reply_markup
        )
        return RULES
    
    await query.edit_message_text(
        "Введите максимальное количество участников (число):"
    )
    return MAX_PARTICIPANTS


async def set_max_participants(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Установка максимального количества участников."""
    try:
        max_participants = int(update.message.text.strip())
        if max_participants < 1:
            raise ValueError
        
        context.user_data['giveaway']['max_participants'] = max_participants
        
        keyboard = [
            [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_winners")],
            [InlineKeyboardButton("➡️ Далее", callback_data="next_to_rules")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"✅ Максимум участников: {max_participants}\n\n"
            "Шаг 8/11: Введите условия участия (например: 'Подписаться на канал @channel'):",
            reply_markup=reply_markup
        )
        
        return RULES
        
    except ValueError:
        await update.message.reply_text(
            "❌ Пожалуйста, введите корректное число (больше 0):"
        )
        return MAX_PARTICIPANTS


async def set_rules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Установка условий участия."""
    rules = update.message.text.strip()
    context.user_data['giveaway']['participation_rules'] = rules
    
    keyboard = [
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_max_participants")],
        [InlineKeyboardButton("➕ Добавить обязательные каналы", callback_data="add_required_channels")],
        [InlineKeyboardButton("⏭ Пропустить", callback_data="skip_required_channels")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "✅ Условия участия сохранены\n\n"
        "Хотите добавить обязательные каналы для подписки?\n\n"
        "Если выберете 'Добавить', отправьте chat_id каналов через запятую.\n"
        "Например: -1001234567890, -1009876543210",
        reply_markup=reply_markup
    )
    
    return RULES


async def handle_required_channels_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора обязательных каналов."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "skip_required_channels":
        context.user_data['giveaway']['required_channels'] = None
        
        keyboard = [
            [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_rules")],
            [InlineKeyboardButton("🕐 Сейчас", callback_data="start_now")],
            [InlineKeyboardButton("📅 Указать дату и время", callback_data="set_start_date")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "⏭ Обязательные каналы не указаны\n\n"
            "Шаг 9/11: Когда начнётся розыгрыш?",
            reply_markup=reply_markup
        )
        return START_DATE
    
    await query.edit_message_text(
        "Отправьте chat_id каналов через запятую\n\n"
        "Пример: -1001234567890, -1009876543210\n\n"
        "💡 Как узнать chat_id канала:\n"
        "1. Добавьте бота в канал как администратора\n"
        "2. Перешлите любое сообщение из канала боту @userinfobot\n"
        "3. Он покажет вам Originating Chat ID"
    )
    return RULES


async def set_required_channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохранение обязательных каналов."""
    channels_str = update.message.text.strip()
    
    try:
        # Парсим список chat_id
        channels = [int(ch.strip()) for ch in channels_str.split(',')]
        context.user_data['giveaway']['required_channels'] = channels
        
        keyboard = [
            [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_rules")],
            [InlineKeyboardButton("🕐 Сейчас", callback_data="start_now")],
            [InlineKeyboardButton("📅 Указать дату и время", callback_data="set_start_date")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"✅ Добавлено обязательных каналов: {len(channels)}\n\n"
            "Шаг 9/11: Когда начнётся розыгрыш?",
            reply_markup=reply_markup
        )
        return START_DATE
        
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат. Введите числовые chat_id через запятую\n"
            "Пример: -1001234567890, -1009876543210"
        )
        return RULES


async def handle_start_date_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора даты начала."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "start_now":
        context.user_data['giveaway']['starts_at'] = datetime.utcnow()
        
        # Показываем календарь для даты окончания
        calendar, step = DetailedTelegramCalendar(min_date=datetime.now().date()).build()
        await query.edit_message_text(
            "✅ Розыгрыш начнётся сразу\n\n"
            "Шаг 10/11: Выберите дату окончания розыгрыша:",
            reply_markup=calendar
        )
        return END_DATE
    
    # Показываем календарь для даты начала
    calendar, step = DetailedTelegramCalendar(min_date=datetime.now().date()).build()
    await query.edit_message_text(
        "📅 Выберите дату начала розыгрыша:",
        reply_markup=calendar
    )
    return START_DATE


async def set_start_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка календаря для даты начала."""
    query = update.callback_query
    await query.answer()
    
    result, key, step = DetailedTelegramCalendar(min_date=datetime.now().date()).process(query.data)
    
    if not result and key:
        await query.edit_message_text(
            f"📅 Выберите {LSTEP[step]} начала розыгрыша:",
            reply_markup=key
        )
        return START_DATE
    elif result:
        context.user_data['giveaway']['start_date_selected'] = result
        
        # Создаем клавиатуру для выбора времени
        keyboard = []
        hours = ["00:00", "06:00", "09:00", "12:00", "15:00", "18:00", "21:00", "23:59"]
        for i in range(0, len(hours), 2):
            row = [InlineKeyboardButton(hours[i], callback_data=f"start_time_{hours[i]}")]
            if i + 1 < len(hours):
                row.append(InlineKeyboardButton(hours[i+1], callback_data=f"start_time_{hours[i+1]}"))
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("⌨️ Ввести своё время", callback_data="start_time_custom")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"✅ Дата начала: {result.strftime('%d.%m.%Y')}\n\n"
            "🕐 Выберите время начала:",
            reply_markup=reply_markup
        )
        return START_TIME
    
    return START_DATE


async def set_start_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Установка времени начала."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "start_time_custom":
        await query.edit_message_text(
            "⌨️ Введите время начала в формате ЧЧ:ММ\n"
            "Пример: 14:30"
        )
        return START_TIME
    
    time_str = query.data.replace("start_time_", "")
    selected_date = context.user_data['giveaway']['start_date_selected']
    hour, minute = map(int, time_str.split(':'))
    
    start_datetime = datetime.combine(selected_date, datetime.min.time()).replace(hour=hour, minute=minute)
    
    if start_datetime < datetime.now():
        await query.edit_message_text(
            "❌ Дата и время начала не могут быть в прошлом.\n\n"
            "Пожалуйста, выберите другую дату."
        )
        return START_DATE
    
    context.user_data['giveaway']['starts_at'] = start_datetime
    
    # Показываем календарь для даты окончания
    min_date = start_datetime.date() + timedelta(days=1)
    calendar, step = DetailedTelegramCalendar(min_date=min_date).build()
    await query.edit_message_text(
        f"✅ Дата начала: {start_datetime.strftime('%d.%m.%Y %H:%M')}\n\n"
        "📅 Выберите дату окончания розыгрыша:",
        reply_markup=calendar
    )
    return END_DATE


async def set_start_time_custom(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Установка кастомного времени начала."""
    time_str = update.message.text.strip()
    
    try:
        hour, minute = map(int, time_str.split(':'))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
        
        selected_date = context.user_data['giveaway']['start_date_selected']
        start_datetime = datetime.combine(selected_date, datetime.min.time()).replace(hour=hour, minute=minute)
        
        if start_datetime < datetime.now():
            await update.message.reply_text(
                "❌ Дата и время начала не могут быть в прошлом.\n\n"
                "Введите другое время:"
            )
            return START_TIME
        
        context.user_data['giveaway']['starts_at'] = start_datetime
        
        # Показываем календарь для даты окончания
        min_date = start_datetime.date() + timedelta(days=1)
        calendar, step = DetailedTelegramCalendar(min_date=min_date).build()
        await update.message.reply_text(
            f"✅ Дата начала: {start_datetime.strftime('%d.%m.%Y %H:%M')}\n\n"
            "📅 Выберите дату окончания розыгрыша:",
            reply_markup=calendar
        )
        return END_DATE
        
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат времени. Используйте ЧЧ:ММ\n"
            "Пример: 14:30"
        )
        return START_TIME


async def set_end_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка календаря для даты окончания."""
    query = update.callback_query
    await query.answer()
    
    start_date = context.user_data['giveaway'].get('starts_at', datetime.now())
    min_date = start_date.date() + timedelta(days=1)
    
    result, key, step = DetailedTelegramCalendar(min_date=min_date).process(query.data)
    
    if not result and key:
        await query.edit_message_text(
            f"📅 Выберите {LSTEP[step]} окончания розыгрыша:",
            reply_markup=key
        )
        return END_DATE
    elif result:
        context.user_data['giveaway']['end_date_selected'] = result
        
        # Создаем клавиатуру для выбора времени
        keyboard = []
        hours = ["00:00", "06:00", "09:00", "12:00", "15:00", "18:00", "21:00", "23:59"]
        for i in range(0, len(hours), 2):
            row = [InlineKeyboardButton(hours[i], callback_data=f"end_time_{hours[i]}")]
            if i + 1 < len(hours):
                row.append(InlineKeyboardButton(hours[i+1], callback_data=f"end_time_{hours[i+1]}"))
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("⌨️ Ввести своё время", callback_data="end_time_custom")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"✅ Дата окончания: {result.strftime('%d.%m.%Y')}\n\n"
            "🕐 Выберите время окончания:",
            reply_markup=reply_markup
        )
        return END_TIME
    
    return END_DATE


async def set_end_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Установка времени окончания."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "end_time_custom":
        await query.edit_message_text(
            "⌨️ Введите время окончания в формате ЧЧ:ММ\n"
            "Пример: 23:59"
        )
        return END_TIME
    
    time_str = query.data.replace("end_time_", "")
    selected_date = context.user_data['giveaway']['end_date_selected']
    hour, minute = map(int, time_str.split(':'))
    
    end_datetime = datetime.combine(selected_date, datetime.min.time()).replace(hour=hour, minute=minute)
    start_datetime = context.user_data['giveaway'].get('starts_at', datetime.now())
    
    if end_datetime <= start_datetime:
        await query.edit_message_text(
            "❌ Дата и время окончания должны быть позже даты начала.\n\n"
            "Пожалуйста, выберите другое время."
        )
        return END_TIME
    
    context.user_data['giveaway']['ends_at'] = end_datetime
    
    keyboard = [
        [InlineKeyboardButton("📢 Сейчас", callback_data="announce_now")],
        [InlineKeyboardButton("📅 Указать дату и время", callback_data="set_announce_date")],
        [InlineKeyboardButton("⏭ Без анонса", callback_data="skip_announce")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"✅ Дата окончания: {end_datetime.strftime('%d.%m.%Y %H:%M')}\n\n"
        "Шаг 11/11: Когда опубликовать **анонс** розыгрыша?",
        reply_markup=reply_markup
    )
    
    return ANNOUNCE_DATE


async def set_end_time_custom(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Установка кастомного времени окончания."""
    time_str = update.message.text.strip()
    
    try:
        hour, minute = map(int, time_str.split(':'))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
        
        selected_date = context.user_data['giveaway']['end_date_selected']
        end_datetime = datetime.combine(selected_date, datetime.min.time()).replace(hour=hour, minute=minute)
        start_datetime = context.user_data['giveaway'].get('starts_at', datetime.now())
        
        if end_datetime <= start_datetime:
            await update.message.reply_text(
                "❌ Дата и время окончания должны быть позже даты начала.\n\n"
                "Введите другое время:"
            )
            return END_TIME
        
        context.user_data['giveaway']['ends_at'] = end_datetime
        
        keyboard = [
            [InlineKeyboardButton("📢 Сейчас", callback_data="announce_now")],
            [InlineKeyboardButton("📅 Указать дату и время", callback_data="set_announce_date")],
            [InlineKeyboardButton("⏭ Без анонса", callback_data="skip_announce")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"✅ Дата окончания: {end_datetime.strftime('%d.%m.%Y %H:%M')}\n\n"
            "Шаг 11/11: Когда опубликовать **анонс** розыгрыша?",
            reply_markup=reply_markup
        )
        
        return ANNOUNCE_DATE
        
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат времени. Используйте ЧЧ:ММ\n"
            "Пример: 23:59"
        )
        return END_TIME


async def handle_announce_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора даты анонса."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "announce_now":
        context.user_data['giveaway']['announce_at'] = datetime.utcnow()
        await query.edit_message_text(
            "✅ Анонс будет опубликован сразу\n\n"
            "Хотите добавить **кастомный текст анонса**?\n"
            "Отправьте текст или /skip для использования автоматического текста:"
        )
        return ANNOUNCEMENT_TEXT
    elif query.data == "skip_announce":
        context.user_data['giveaway']['announce_at'] = None
        await query.edit_message_text(
            "✅ Анонс не будет опубликован автоматически\n\n"
            "Хотите добавить **кастомный текст анонса**?\n"
            "Отправьте текст или /skip для использования автоматического текста:"
        )
        return ANNOUNCEMENT_TEXT
    
    # Показываем календарь для даты анонса
    calendar, step = DetailedTelegramCalendar(min_date=datetime.now().date()).build()
    await query.edit_message_text(
        "📅 Выберите дату публикации анонса:",
        reply_markup=calendar
    )
    return ANNOUNCE_DATE


async def set_announce_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка календаря для даты анонса."""
    query = update.callback_query
    await query.answer()
    
    result, key, step = DetailedTelegramCalendar(min_date=datetime.now().date()).process(query.data)
    
    if not result and key:
        await query.edit_message_text(
            f"📅 Выберите {LSTEP[step]} публикации анонса:",
            reply_markup=key
        )
        return ANNOUNCE_DATE
    elif result:
        context.user_data['giveaway']['announce_date_selected'] = result
        
        # Создаем клавиатуру для выбора времени
        keyboard = []
        hours = ["00:00", "06:00", "09:00", "12:00", "15:00", "18:00", "21:00", "23:59"]
        for i in range(0, len(hours), 2):
            row = [InlineKeyboardButton(hours[i], callback_data=f"announce_time_{hours[i]}")]
            if i + 1 < len(hours):
                row.append(InlineKeyboardButton(hours[i+1], callback_data=f"announce_time_{hours[i+1]}"))
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("⌨️ Ввести своё время", callback_data="announce_time_custom")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"✅ Дата анонса: {result.strftime('%d.%m.%Y')}\n\n"
            "🕐 Выберите время публикации:",
            reply_markup=reply_markup
        )
        return ANNOUNCE_TIME
    
    return ANNOUNCE_DATE


async def set_announce_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Установка времени анонса."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "announce_time_custom":
        await query.edit_message_text(
            "⌨️ Введите время публикации анонса в формате ЧЧ:ММ\n"
            "Пример: 10:00"
        )
        return ANNOUNCE_TIME
    
    time_str = query.data.replace("announce_time_", "")
    selected_date = context.user_data['giveaway']['announce_date_selected']
    hour, minute = map(int, time_str.split(':'))
    
    announce_datetime = datetime.combine(selected_date, datetime.min.time()).replace(hour=hour, minute=minute)
    
    if announce_datetime < datetime.now():
        await query.edit_message_text(
            "❌ Дата и время анонса не могут быть в прошлом.\n\n"
            "Пожалуйста, выберите другую дату."
        )
        return ANNOUNCE_DATE
    
    context.user_data['giveaway']['announce_at'] = announce_datetime
    
    await query.edit_message_text(
        f"✅ Дата анонса: {announce_datetime.strftime('%d.%m.%Y %H:%M')}\n\n"
        "Хотите добавить **кастомный текст анонса**?\n"
        "Отправьте текст или /skip для использования автоматического текста:"
    )
    
    return ANNOUNCEMENT_TEXT


async def set_announce_time_custom(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Установка кастомного времени анонса."""
    time_str = update.message.text.strip()
    
    try:
        hour, minute = map(int, time_str.split(':'))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
        
        selected_date = context.user_data['giveaway']['announce_date_selected']
        announce_datetime = datetime.combine(selected_date, datetime.min.time()).replace(hour=hour, minute=minute)
        
        if announce_datetime < datetime.now():
            await update.message.reply_text(
                "❌ Дата и время анонса не могут быть в прошлом.\n\n"
                "Введите другое время:"
            )
            return ANNOUNCE_TIME
        
        context.user_data['giveaway']['announce_at'] = announce_datetime
        
        await update.message.reply_text(
            f"✅ Дата анонса: {announce_datetime.strftime('%d.%m.%Y %H:%M')}\n\n"
            "Хотите добавить **кастомный текст анонса**?\n"
            "Отправьте текст или /skip для использования автоматического текста:"
        )
        
        return ANNOUNCEMENT_TEXT
        
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат времени. Используйте ЧЧ:ММ\n"
            "Пример: 10:00"
        )
        return ANNOUNCE_TIME


async def set_announcement_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Установка текста анонса."""
    if update.message.text == "/skip":
        context.user_data['giveaway']['announcement_text'] = None
        await update.message.reply_text("✅ Будет использован автоматический текст анонса")
    else:
        announcement_text = update.message.text.strip()
        context.user_data['giveaway']['announcement_text'] = announcement_text
        await update.message.reply_text("✅ Кастомный текст анонса сохранён")
    
    # Показываем превью
    await show_preview(update, context)
    
    return PREVIEW


async def show_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показ превью розыгрыша."""
    giveaway = context.user_data['giveaway']
    
    # Формируем текст анонса
    if giveaway.get('announcement_text'):
        text = giveaway['announcement_text']
    else:
        text = f"🎉 {giveaway['title']}\n\n"
        text += f"{giveaway.get('description', '')}\n\n"
        text += f"🏆 Призы: {giveaway.get('prizes', 'Не указаны')}\n"
        text += f"👥 Победителей: {giveaway.get('winners_count', 1)}\n"
        
        if giveaway.get('max_participants'):
            text += f"📊 Максимум участников: {giveaway['max_participants']}\n"
        
        if giveaway.get('target_chats'):
            chat_count = len(giveaway['target_chats'])
            text += f"📢 Чатов для публикации: {chat_count}\n"
        
        if giveaway.get('participation_rules'):
            text += f"\n📋 Условия участия:\n{giveaway['participation_rules']}\n"
        
        starts_at = giveaway.get('starts_at')
        ends_at = giveaway.get('ends_at')
        
        if starts_at:
            text += f"\n🕐 Начало: {starts_at.strftime('%d.%m.%Y %H:%M')}\n"
        if ends_at:
            text += f"⏰ Окончание: {ends_at.strftime('%d.%m.%Y %H:%M')}\n"
    
    keyboard = [
        [InlineKeyboardButton("✅ Подтвердить и сохранить", callback_data="confirm_giveaway")],
        [InlineKeyboardButton("❌ Отменить", callback_data="cancel_giveaway")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Отправляем превью
    if giveaway.get('image_file_id'):
        await update.message.reply_photo(
            photo=giveaway['image_file_id'],
            caption=f"📋 ПРЕВЬЮ АНОНСА\n\n{text}",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            f"📋 ПРЕВЬЮ АНОНСА\n\n{text}",
            reply_markup=reply_markup
        )


async def confirm_giveaway(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Подтверждение и сохранение розыгрыша."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_giveaway":
        await query.edit_message_caption(
            caption="❌ Создание розыгрыша отменено.",
            reply_markup=None
        ) if query.message.photo else await query.edit_message_text(
            "❌ Создание розыгрыша отменено.",
            reply_markup=None
        )
        context.user_data.clear()
        return ConversationHandler.END
    
    # Сохраняем розыгрыш в БД
    giveaway_data = context.user_data['giveaway']
    db = Database(settings.DATABASE_URL)
    
    # Фильтруем только валидные поля модели Giveaway
    valid_fields = {
        'title', 'description', 'prizes', 'winners_count', 'max_participants',
        'participation_rules', 'image_file_id', 'image_url', 'target_chats',
        'required_channels', 'starts_at', 'ends_at', 'announce_at', 'announcement_text'
    }
    filtered_data = {k: v for k, v in giveaway_data.items() if k in valid_fields}
    
    try:
        giveaway = await db.create_giveaway(
            creator_id=update.effective_user.id,
            **filtered_data
        )
        
        await query.edit_message_caption(
            caption=f"✅ Розыгрыш #{giveaway.id} успешно создан и сохранён!",
            reply_markup=None
        ) if query.message.photo else await query.edit_message_text(
            f"✅ Розыгрыш #{giveaway.id} успешно создан и сохранён!",
            reply_markup=None
        )
        
        logger.info(f"Giveaway {giveaway.id} created by {update.effective_user.id}")
        
    except Exception as e:
        logger.error(f"Error creating giveaway: {e}")
        await query.message.reply_text(
            f"❌ Ошибка при создании розыгрыша: {str(e)}"
        )
    finally:
        await db.close()
        context.user_data.clear()
    
    return ConversationHandler.END


async def cancel_giveaway_creation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена создания розыгрыша."""
    await update.message.reply_text("❌ Создание розыгрыша отменено.")
    context.user_data.clear()
    return ConversationHandler.END


# Обработчики навигационных кнопок
async def navigation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка навигационных кнопок Назад/Далее."""
    query = update.callback_query
    await query.answer()
    
    action = query.data
    giveaway = context.user_data.get('giveaway', {})
    
    # Назад к названию
    if action == "back_to_title":
        await query.edit_message_text(
            "Шаг 1/11: Введите название розыгрыша:"
        )
        return TITLE
    
    # Далее к описанию
    elif action == "next_to_description":
        if not giveaway.get('title'):
            await query.edit_message_text(
                "❌ Сначала введите название розыгрыша:"
            )
            return TITLE
        await query.edit_message_text(
            f"✅ Название: {giveaway['title']}\n\n"
            "Шаг 2/11: Введите описание розыгрыша:"
        )
        return DESCRIPTION
    
    # Назад к описанию
    elif action == "back_to_description":
        await query.edit_message_text(
            "Шаг 2/11: Введите описание розыгрыша:"
        )
        return DESCRIPTION
    
    # Далее к призам
    elif action == "next_to_prizes":
        if not giveaway.get('description'):
            await query.edit_message_text(
                "❌ Сначала введите описание розыгрыша:"
            )
            return DESCRIPTION
        await query.edit_message_text(
            "✅ Описание сохранено\n\n"
            "Шаг 3/11: Опишите призы (что получит победитель):"
        )
        return PRIZES
    
    # Назад к призам
    elif action == "back_to_prizes":
        await query.edit_message_text(
            "Шаг 3/11: Опишите призы (что получит победитель):"
        )
        return PRIZES
    
    # Далее к target_chats
    elif action == "next_to_target_chats":
        if not giveaway.get('prizes'):
            await query.edit_message_text(
                "❌ Сначала опишите призы:"
            )
            return PRIZES
        await query.edit_message_text(
            "✅ Призы сохранены\n\n"
            "Шаг 4/11: Введите ID каналов и чатов для публикации анонса.\n"
            "Формат: укажите chat_id через запятую.\n"
            "Например: -1001234567890, -1009876543210"
        )
        return TARGET_CHATS
    
    # Назад к target_chats
    elif action == "back_to_target_chats":
        await query.edit_message_text(
            "Шаг 4/11: Введите ID каналов и чатов для публикации анонса.\n"
            "Формат: укажите chat_id через запятую.\n"
            "Например: -1001234567890, -1009876543210"
        )
        return TARGET_CHATS
    
    # Далее к количеству победителей
    elif action == "next_to_winners":
        await query.edit_message_text(
            "Шаг 6/11: Введите количество победителей (число):"
        )
        return WINNERS_COUNT
    
    # Назад к картинке
    elif action == "back_to_image":
        keyboard = [
            [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_target_chats")],
            [InlineKeyboardButton("📷 Загрузить картинку", callback_data="upload_image")],
            [InlineKeyboardButton("⏭ Пропустить картинку", callback_data="skip_image")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "Шаг 5/11: Хотите добавить картинку к розыгрышу?",
            reply_markup=reply_markup
        )
        return IMAGE
    
    # Назад к победителям
    elif action == "back_to_winners":
        await query.edit_message_text(
            "Шаг 6/11: Введите количество победителей (число):"
        )
        return WINNERS_COUNT
    
    # Далее к условиям
    elif action == "next_to_rules":
        await query.edit_message_text(
            "Шаг 8/11: Введите условия участия (например: 'Подписаться на канал @channel'):"
        )
        return RULES
    
    # Назад к максимуму участников
    elif action == "back_to_max_participants":
        keyboard = [
            [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_winners")],
            [InlineKeyboardButton("♾ Без ограничений", callback_data="unlimited_participants")],
            [InlineKeyboardButton("📝 Указать число", callback_data="set_max_participants")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "Шаг 7/11: Установить максимальное количество участников?",
            reply_markup=reply_markup
        )
        return MAX_PARTICIPANTS
    
    return ConversationHandler.END


# ConversationHandler для создания розыгрыша
def get_giveaway_conversation_handler() -> ConversationHandler:
    """Возвращает ConversationHandler для создания розыгрыша."""
    return ConversationHandler(
        entry_points=[
            CommandHandler("create_giveaway", create_giveaway_start),
            CallbackQueryHandler(start_create_from_menu, pattern="^start_create_launch$")
        ],
        states={
            MODE_SELECT: [
                CallbackQueryHandler(handle_creation_mode, pattern="^(creation_manual|creation_ai)$")
            ],
            AI_BRIEF: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_ai_brief)
            ],
            AI_REVIEW: [
                CallbackQueryHandler(
                    handle_ai_review,
                    pattern="^(accept_ai_draft|regenerate_ai_draft|revise_ai_draft|switch_manual)$"
                )
            ],
            AI_FEEDBACK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_ai_feedback)
            ],
            TITLE: [
                CallbackQueryHandler(navigation_handler, pattern="^(back_to_|next_to_)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_title)
            ],
            DESCRIPTION: [
                CallbackQueryHandler(navigation_handler, pattern="^(back_to_|next_to_)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_description)
            ],
            PRIZES: [
                CallbackQueryHandler(navigation_handler, pattern="^(back_to_|next_to_)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_prizes)
            ],
            TARGET_CHATS: [
                CallbackQueryHandler(navigation_handler, pattern="^(back_to_|next_to_)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_target_chats)
            ],
            IMAGE: [
                CallbackQueryHandler(navigation_handler, pattern="^(back_to_|next_to_)"),
                CallbackQueryHandler(handle_image_choice, pattern="^(upload_image|skip_image)$"),
                MessageHandler(filters.PHOTO, set_image)
            ],
            WINNERS_COUNT: [
                CallbackQueryHandler(navigation_handler, pattern="^(back_to_|next_to_)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_winners_count)
            ],
            MAX_PARTICIPANTS: [
                CallbackQueryHandler(navigation_handler, pattern="^(back_to_|next_to_)"),
                CallbackQueryHandler(handle_max_participants_choice, pattern="^(unlimited_participants|set_max_participants)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_max_participants)
            ],
            RULES: [
                CallbackQueryHandler(navigation_handler, pattern="^(back_to_|next_to_)"),
                CallbackQueryHandler(handle_required_channels_choice, pattern="^(add_required_channels|skip_required_channels)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, lambda update, context: 
                    set_required_channels(update, context) if context.user_data.get('giveaway', {}).get('participation_rules') 
                    else set_rules(update, context))
            ],
            START_DATE: [
                CallbackQueryHandler(navigation_handler, pattern="^(back_to_|next_to_)"),
                CallbackQueryHandler(handle_start_date_choice, pattern="^(start_now|set_start_date)$"),
                CallbackQueryHandler(set_start_date)
            ],
            START_TIME: [
                CallbackQueryHandler(set_start_time, pattern="^start_time_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_start_time_custom)
            ],
            END_DATE: [
                CallbackQueryHandler(navigation_handler, pattern="^(back_to_|next_to_)"),
                CallbackQueryHandler(set_end_date)
            ],
            END_TIME: [
                CallbackQueryHandler(set_end_time, pattern="^end_time_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_end_time_custom)
            ],
            ANNOUNCE_DATE: [
                CallbackQueryHandler(navigation_handler, pattern="^(back_to_|next_to_)"),
                CallbackQueryHandler(handle_announce_choice, pattern="^(announce_now|set_announce_date|skip_announce)$"),
                CallbackQueryHandler(set_announce_date)
            ],
            ANNOUNCE_TIME: [
                CallbackQueryHandler(set_announce_time, pattern="^announce_time_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_announce_time_custom)
            ],
            ANNOUNCEMENT_TEXT: [
                CallbackQueryHandler(navigation_handler, pattern="^(back_to_|next_to_)"),
                MessageHandler(filters.TEXT, set_announcement_text)
            ],
            PREVIEW: [CallbackQueryHandler(confirm_giveaway, pattern="^(confirm_giveaway|cancel_giveaway)$")]
        },
        fallbacks=[CommandHandler("cancel", cancel_giveaway_creation)],
        per_message=False
    )
