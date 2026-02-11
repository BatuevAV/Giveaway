"""Основной модуль бота для розыгрышей."""

import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

from config import settings
from src.admin_handlers import add_admin, remove_admin, list_admins
from src.database import Database
from src.giveaway_handlers import get_giveaway_conversation_handler
from src.list_handlers import (
    list_giveaways, view_giveaway, view_giveaway_callback, publish_giveaway,
    edit_announcement, save_new_announcement, reset_announcement, cancel_edit_announcement,
    back_to_list_callback, draw_winners, draw_winners_callback, notify_winners,
    force_draw, redraw_winners, force_draw_legacy,
    delete_giveaways, delete_giveaway_callback, confirm_delete_giveaway, cancel_delete_giveaway,
    edit_giveaway, edit_giveaway_callback, edit_field_callback, save_edited_field,
    toggle_active_callback, finish_edit_callback
)
from src.participation_handlers import get_participation_handlers

logger = logging.getLogger(__name__)


class GiveawayBot:
    """Основной класс бота для розыгрышей."""
    
    def __init__(self, token: str):
        """
        Инициализация бота.
        
        Args:
            token: Токен Telegram бота
        """
        self.token = token
        self.application = None

    async def _build_help_text(self, user_id: int) -> str:
        """Формирует help-текст с учетом роли пользователя."""
        from src.permissions import is_admin, is_owner

        is_user_owner = await is_owner(user_id)
        is_user_admin = await is_admin(user_id) or is_user_owner

        help_text = "📋 Доступные команды:\n\n"
        help_text += "👤 Для всех:\n"
        help_text += "/start - Начать работу с ботом\n"
        help_text += "/help - Показать это сообщение\n"
        help_text += "/my_participation - Проверить участие в активном розыгрыше\n"

        if is_user_admin:
            help_text += "\n👨‍💼 Для администраторов:\n"
            help_text += "/create_giveaway - Создать новый розыгрыш\n"
            help_text += "/list_giveaways - Список всех розыгрышей\n"
            help_text += "/view_giveaway <id> - Подробная информация о розыгрыше\n"
            help_text += "/draw_winners <id> - Провести розыгрыш и выбрать победителей\n"
            help_text += "/force_draw <id> - Принудительный розыгрыш (если участников мало)\n"
            help_text += "/force_draw_<id> - Старый формат принудительного розыгрыша (совместимость)\n"
            help_text += "/redraw_winners <id> - Провести повторный розыгрыш\n"
            help_text += "/edit_giveaway <id> - Изменить параметры розыгрыша\n"
            help_text += "/delete_giveaway <id> - Удалить розыгрыш\n"
            help_text += "/delete_giveaways <id1,id2,...> - Удалить несколько розыгрышей\n"
            help_text += "/cancel - Отменить текущее действие\n"

        if is_user_owner:
            help_text += "\n👑 Для владельца:\n"
            help_text += "/add_admin <id> - Добавить администратора\n"
            help_text += "/remove_admin <id> - Удалить администратора\n"
            help_text += "/list_admins - Список администраторов\n"

        return help_text

    async def _build_start_text(self, user) -> str:
        """Формирует приветственный текст со статусом пользователя."""
        from src.permissions import is_admin, is_owner

        user_id = user.id
        if await is_owner(user_id):
            status = "Владельцем"
        elif await is_admin(user_id):
            status = "Администратором"
        else:
            status = "Пользователем"

        first_name = user.first_name or "Пользователь"
        return (
            f"Привет, {first_name}! 👋\n\n"
            f"Вы являетесь {status}.\n\n"
            "Я бот для проведения розыгрышей.\n"
            "Выберите действие:"
        )

    async def _start_menu_markup(self, user_id: int) -> InlineKeyboardMarkup:
        """Клавиатура стартового меню с учетом роли пользователя."""
        from src.permissions import is_admin, is_owner

        is_user_admin = await is_admin(user_id) or await is_owner(user_id)

        keyboard = [[InlineKeyboardButton("❓ Помощь", callback_data="start_menu_help")]]

        if is_user_admin:
            keyboard.append([InlineKeyboardButton("🎉 Создать розыгрыш", callback_data="start_menu_create")])
            keyboard.append([InlineKeyboardButton("📋 Список розыгрышей", callback_data="start_menu_list")])
            keyboard.append([InlineKeyboardButton("👥 Проверить участников", callback_data="start_menu_participants")])
        else:
            keyboard.append([InlineKeyboardButton("🔎 Проверить участие", callback_data="start_menu_check_participation")])
        return InlineKeyboardMarkup(keyboard)

    def _is_current_active_giveaway(self, giveaway) -> bool:
        """Проверка, что розыгрыш активен по флагу и времени."""
        if not giveaway or not giveaway.is_active:
            return False
        now = datetime.utcnow()
        if giveaway.starts_at and giveaway.starts_at > now:
            return False
        if giveaway.ends_at and giveaway.ends_at <= now:
            return False
        return True

    async def _get_current_active_giveaways(self) -> list:
        """Получает текущие активные розыгрыши."""
        db = Database(settings.DATABASE_URL)
        try:
            giveaways = await db.get_active_giveaways()
            return [g for g in giveaways if self._is_current_active_giveaway(g)]
        finally:
            await db.close()

    async def _show_participants_for_giveaway(self, query, giveaway_id: int) -> None:
        """Показывает количество участников по выбранному розыгрышу."""
        db = Database(settings.DATABASE_URL)
        try:
            giveaway = await db.get_giveaway_by_id(giveaway_id)
            if not giveaway or not self._is_current_active_giveaway(giveaway):
                await query.edit_message_text(
                    "❌ Розыгрыш не найден или уже неактивен.",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("⬅️ К списку", callback_data="start_menu_participants_list")]]
                    )
                )
                return

            participants_count = await db.get_participants_count(giveaway_id)
            text = (
                f"👥 <b>Количество участников</b>\n\n"
                f"🎉 <b>{giveaway.title}</b>\n"
                f"Участников: <b>{participants_count}</b>\n"
                f"Победителей: <b>{giveaway.winners_count}</b>\n"
            )
            keyboard = [[InlineKeyboardButton("⬅️ К списку", callback_data="start_menu_participants_list")]]
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        finally:
            await db.close()

    async def _show_active_giveaways_for_participants(self, query) -> None:
        """Показывает список активных розыгрышей для выбора."""
        current_giveaways = await self._get_current_active_giveaways()

        if not current_giveaways:
            await query.edit_message_text(
                "ℹ️ Сейчас нет активных розыгрышей.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("⬅️ Назад", callback_data="start_menu_back")]]
                )
            )
            return

        if len(current_giveaways) == 1:
            await self._show_participants_for_giveaway(query, current_giveaways[0].id)
            return

        keyboard = [
            [InlineKeyboardButton(f"🎉 {g.title[:45]}", callback_data=f"start_menu_participants_{g.id}")]
            for g in current_giveaways[:20]
        ]
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="start_menu_back")])
        await query.edit_message_text(
            "📋 Выберите розыгрыш для проверки количества участников:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Обработчик команды /start.
        
        Args:
            update: Объект обновления Telegram
            context: Контекст выполнения
        """
        user = update.effective_user
        start_text = await self._build_start_text(user)
        await update.message.reply_text(start_text, reply_markup=await self._start_menu_markup(user.id))
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Обработчик команды /help.
        
        Args:
            update: Объект обновления Telegram
            context: Контекст выполнения
        """
        help_text = await self._build_help_text(update.effective_user.id)
        await update.message.reply_text(help_text)

    async def start_menu_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработка кнопок стартового меню."""
        from src.permissions import is_admin, is_owner

        query = update.callback_query
        await query.answer()
        action = query.data
        user_id = update.effective_user.id
        is_user_admin = await is_admin(user_id) or await is_owner(user_id)

        if action == "start_menu_help":
            help_text = await self._build_help_text(user_id)
            keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="start_menu_back")]]
            await query.edit_message_text(help_text, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        if action == "start_menu_create":
            if not is_user_admin:
                await query.edit_message_text(
                    "⛔️ Создание розыгрышей доступно только администраторам.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="start_menu_back")]])
                )
                return
            text = (
                "🎉 Создание розыгрыша\n\n"
                "Нажмите кнопку ниже, чтобы запустить мастер создания.\n\n"
                "Внутри мастера будут 2 варианта:\n"
                "1. 🧩 Самостоятельно — ручной ввод всех полей.\n"
                "2. 🤖 Автоматическое создание (AI) — Ollama генерирует название, описание, призы и условия, "
                "после чего вы можете согласовать или отправить на доработку."
            )
            keyboard = [
                [InlineKeyboardButton("🚀 Запустить создание", callback_data="start_create_launch")],
                [InlineKeyboardButton("⬅️ Назад", callback_data="start_menu_back")]
            ]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        if action == "start_menu_participants":
            if not is_user_admin:
                await query.edit_message_text(
                    "⛔️ Проверка количества участников доступна только администраторам.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="start_menu_back")]])
                )
                return
            await self._show_active_giveaways_for_participants(query)
            return

        if action == "start_menu_participants_list":
            if not is_user_admin:
                await query.edit_message_text(
                    "⛔️ Проверка количества участников доступна только администраторам.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="start_menu_back")]])
                )
                return
            await self._show_active_giveaways_for_participants(query)
            return

        if action.startswith("start_menu_participants_"):
            if not is_user_admin:
                await query.edit_message_text(
                    "⛔️ Проверка количества участников доступна только администраторам.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="start_menu_back")]])
                )
                return
            giveaway_id = int(action.split("_")[-1])
            await self._show_participants_for_giveaway(query, giveaway_id)
            return

        if action == "start_menu_check_participation":
            await query.edit_message_text(
                "🔎 Проверка участия\n\n"
                "Нажмите команду /my_participation, чтобы посмотреть статус участия "
                "в текущих активных розыгрышах."
            )
            return

        if action == "start_menu_list":
            if not is_user_admin:
                await query.edit_message_text(
                    "⛔️ Список розыгрышей доступен только администраторам.\n\n"
                    "Если у вас есть права администратора, используйте /list_giveaways.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="start_menu_back")]])
                )
                return

            db = Database(settings.DATABASE_URL)
            try:
                giveaways = await db.get_all_giveaways()
                if not giveaways:
                    await query.edit_message_text(
                        "📋 Розыгрышей пока нет.\n\nСоздайте первый: /create_giveaway",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="start_menu_back")]])
                    )
                    return

                text = f"📋 Всего розыгрышей: {len(giveaways)}\n\n"
                for giveaway in giveaways[:10]:
                    status = "✅" if giveaway.is_active else "🔴"
                    published = "📢" if giveaway.is_published else "📝"
                    text += f"{status}{published} #{giveaway.id} — {giveaway.title}\n"

                keyboard = [
                    [InlineKeyboardButton(f"🔎 Открыть #{g.id}", callback_data=f"view_giveaway_{g.id}")]
                    for g in giveaways[:10]
                ]
                keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="start_menu_back")])
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            finally:
                await db.close()
            return

        if action == "start_menu_back":
            user = update.effective_user
            start_text = await self._build_start_text(user)
            await query.edit_message_text(start_text, reply_markup=await self._start_menu_markup(user.id))
    
    def setup_handlers(self) -> None:
        """Настройка обработчиков команд."""
        # Основные команды
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        
        # Команды управления администраторами (только для владельца)
        self.application.add_handler(CommandHandler("add_admin", add_admin))
        self.application.add_handler(CommandHandler("remove_admin", remove_admin))
        self.application.add_handler(CommandHandler("list_admins", list_admins))
        
        # Команды для работы с розыгрышами (для администраторов)
        self.application.add_handler(CommandHandler("list_giveaways", list_giveaways))
        self.application.add_handler(CommandHandler("view_giveaway", view_giveaway))
        self.application.add_handler(CommandHandler("draw_winners", draw_winners))
        self.application.add_handler(CommandHandler("force_draw", force_draw))
        self.application.add_handler(CommandHandler("redraw_winners", redraw_winners))
        self.application.add_handler(CommandHandler("edit_giveaway", edit_giveaway))
        self.application.add_handler(CommandHandler("delete_giveaway", delete_giveaways))
        self.application.add_handler(CommandHandler("delete_giveaways", delete_giveaways))
        
        # Callback кнопки для управления розыгрышами
        self.application.add_handler(CallbackQueryHandler(self.start_menu_callback, pattern=r"^start_menu_"))
        self.application.add_handler(CallbackQueryHandler(view_giveaway_callback, pattern=r"^view_giveaway_\d+$"))
        self.application.add_handler(CallbackQueryHandler(edit_giveaway_callback, pattern=r"^edit_\d+$"))
        self.application.add_handler(CallbackQueryHandler(back_to_list_callback, pattern=r"^back_to_list$"))
        self.application.add_handler(CallbackQueryHandler(publish_giveaway, pattern=r"^publish_\d+$"))
        self.application.add_handler(CallbackQueryHandler(edit_field_callback, pattern=r"^edit_field_[a-z_]+_\d+$"))
        self.application.add_handler(CallbackQueryHandler(toggle_active_callback, pattern=r"^toggle_active_\d+$"))
        self.application.add_handler(CallbackQueryHandler(finish_edit_callback, pattern=r"^finish_edit_\d+$"))
        self.application.add_handler(CallbackQueryHandler(edit_announcement, pattern=r"^edit_announcement_\d+$"))
        self.application.add_handler(CallbackQueryHandler(reset_announcement, pattern=r"^reset_announcement_\d+$"))
        self.application.add_handler(CallbackQueryHandler(cancel_edit_announcement, pattern=r"^cancel_edit_announcement_\d+$"))
        self.application.add_handler(CallbackQueryHandler(draw_winners_callback, pattern=r"^draw_winners_\d+$"))
        self.application.add_handler(CallbackQueryHandler(notify_winners, pattern=r"^notify_winners_\d+$"))
        self.application.add_handler(CallbackQueryHandler(delete_giveaway_callback, pattern=r"^delete_\d+$"))
        self.application.add_handler(CallbackQueryHandler(confirm_delete_giveaway, pattern=r"^confirm_delete_\d+$"))
        self.application.add_handler(CallbackQueryHandler(cancel_delete_giveaway, pattern=r"^cancel_delete_\d+$"))
        
        # Создание розыгрыша (conversation handler)
        self.application.add_handler(get_giveaway_conversation_handler())
        
        # Обработчик текстовых сообщений для редактирования анонса (должен быть после conversation handler)
        self.application.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
                save_edited_field
            )
        )
        self.application.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
                save_new_announcement
            )
        )

        # Совместимость со старым форматом команды: /force_draw_<id>
        self.application.add_handler(
            MessageHandler(filters.Regex(r"^/force_draw_\d+(@\w+)?$"), force_draw_legacy)
        )
        
        # Обработчики участия в розыгрышах
        for handler in get_participation_handlers():
            self.application.add_handler(handler)

    async def setup_bot_commands(self) -> None:
        """Регистрирует команды в меню Telegram рядом с полем ввода."""
        if not self.application:
            return

        commands = [
            BotCommand("start", "Главное меню"),
            BotCommand("help", "Помощь"),
            BotCommand("my_participation", "Проверить мое участие"),
            BotCommand("create_giveaway", "Создать розыгрыш"),
            BotCommand("list_giveaways", "Список розыгрышей"),
        ]
        await self.application.bot.set_my_commands(commands)
        logger.info("Telegram bot commands menu configured")
    
    def build(self) -> Application:
        """
        Построение приложения бота.
        
        Returns:
            Приложение Telegram бота
        """
        self.application = Application.builder().token(self.token).build()
        self.setup_handlers()
        return self.application
    
    async def run(self) -> None:
        """Запуск бота."""
        logger.info("Запуск бота...")
        await self.application.run_polling(allowed_updates=Update.ALL_TYPES)
