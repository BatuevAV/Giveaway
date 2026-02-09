"""Основной модуль бота для розыгрышей."""

import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

from config import settings
from src.admin_handlers import add_admin, remove_admin, list_admins
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

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
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
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Обработчик команды /start.
        
        Args:
            update: Объект обновления Telegram
            context: Контекст выполнения
        """
        user = update.effective_user
        await update.message.reply_text(
            f"Привет, {user.first_name}! 👋\n\n"
            "Я бот для проведения розыгрышей.\n"
            "Функционал в разработке."
        )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Обработчик команды /help.
        
        Args:
            update: Объект обновления Telegram
            context: Контекст выполнения
        """
        from src.permissions import is_admin, is_owner
        
        user_id = update.effective_user.id
        is_user_admin = await is_admin(user_id)
        is_user_owner = await is_owner(user_id)
        
        help_text = "📋 Доступные команды:\n\n"
        help_text += "👤 Для всех:\n"
        help_text += "/start - Начать работу с ботом\n"
        help_text += "/help - Показать это сообщение\n"
        
        if is_user_admin:
            help_text += "\n👨‍💼 Для администраторов:\n"
            help_text += "/create_giveaway - Создать новый розыгрыш\n"
            help_text += "/list_giveaways - Список всех розыгрышей\n"
            help_text += "/view_giveaway <id> - Подробная информация о розыгрыше\n"
            help_text += "/draw_winners <id> - Провести розыгрыш и выбрать победителей\n"
            help_text += "/force_draw <id> - Принудительный розыгрыш (если участников мало)\n"
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
        
        await update.message.reply_text(help_text)
    
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
