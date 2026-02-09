"""Тесты для основного функционала бота."""

import pytest
from src.bot import GiveawayBot


class TestGiveawayBot:
    """Тесты для класса GiveawayBot."""
    
    def test_bot_initialization(self, mock_bot_token):
        """Тест инициализации бота."""
        bot = GiveawayBot(mock_bot_token)
        assert bot.token == mock_bot_token
        assert bot.application is None
    
    def test_bot_build(self, mock_bot_token):
        """Тест построения приложения бота."""
        bot = GiveawayBot(mock_bot_token)
        application = bot.build()
        assert application is not None
        assert bot.application is not None
    
    @pytest.mark.asyncio
    async def test_start_command(self, mock_bot_token):
        """Тест команды /start."""
        bot = GiveawayBot(mock_bot_token)
        # Базовая проверка что метод существует
        assert hasattr(bot, 'start_command')
        assert callable(bot.start_command)
    
    @pytest.mark.asyncio
    async def test_help_command(self, mock_bot_token):
        """Тест команды /help."""
        bot = GiveawayBot(mock_bot_token)
        # Базовая проверка что метод существует
        assert hasattr(bot, 'help_command')
        assert callable(bot.help_command)
