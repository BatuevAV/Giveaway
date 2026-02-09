"""Тесты для работы с базой данных."""

import pytest
from src.database import Database
from src.models import User


class TestDatabase:
    """Тесты для класса Database."""
    
    @pytest.mark.asyncio
    async def test_database_initialization(self):
        """Тест инициализации базы данных."""
        db = Database("sqlite+aiosqlite:///:memory:")
        await db.init_db()
        assert db.engine is not None
        await db.close()
    
    @pytest.mark.asyncio
    async def test_create_user(self, mock_telegram_id, mock_username):
        """Тест создания пользователя."""
        db = Database("sqlite+aiosqlite:///:memory:")
        await db.init_db()
        
        user = await db.create_user(
            telegram_id=mock_telegram_id,
            username=mock_username,
            first_name="Test",
            last_name="User"
        )
        
        assert user.telegram_id == mock_telegram_id
        assert user.username == mock_username
        assert user.first_name == "Test"
        assert user.last_name == "User"
        
        await db.close()
    
    @pytest.mark.asyncio
    async def test_get_user_by_telegram_id(self, mock_telegram_id, mock_username):
        """Тест получения пользователя по Telegram ID."""
        db = Database("sqlite+aiosqlite:///:memory:")
        await db.init_db()
        
        # Создаем пользователя
        await db.create_user(
            telegram_id=mock_telegram_id,
            username=mock_username
        )
        
        # Получаем пользователя
        user = await db.get_user_by_telegram_id(mock_telegram_id)
        assert user is not None
        assert user.telegram_id == mock_telegram_id
        assert user.username == mock_username
        
        await db.close()
    
    @pytest.mark.asyncio
    async def test_get_or_create_user(self, mock_telegram_id, mock_username):
        """Тест получения или создания пользователя."""
        db = Database("sqlite+aiosqlite:///:memory:")
        await db.init_db()
        
        # Первый вызов - создание
        user1 = await db.get_or_create_user(
            telegram_id=mock_telegram_id,
            username=mock_username
        )
        assert user1.telegram_id == mock_telegram_id
        
        # Второй вызов - получение существующего
        user2 = await db.get_or_create_user(
            telegram_id=mock_telegram_id,
            username=mock_username
        )
        assert user2.id == user1.id
        
        await db.close()
