"""Тесты для моделей данных."""

import pytest
from datetime import datetime
from src.models import User, Giveaway, Participation


class TestModels:
    """Тесты для моделей данных."""
    
    def test_user_model_creation(self):
        """Тест создания модели User."""
        user = User(
            telegram_id=123456789,
            username="test_user",
            first_name="Test",
            last_name="User",
            is_admin=False
        )
        
        assert user.telegram_id == 123456789
        assert user.username == "test_user"
        assert user.first_name == "Test"
        assert user.last_name == "User"
        assert user.is_admin is False
    
    def test_giveaway_model_creation(self):
        """Тест создания модели Giveaway."""
        giveaway = Giveaway(
            title="Test Giveaway",
            description="Test Description",
            creator_id=1,
            winners_count=1,
            is_active=True
        )
        
        assert giveaway.title == "Test Giveaway"
        assert giveaway.description == "Test Description"
        assert giveaway.creator_id == 1
        assert giveaway.winners_count == 1
        assert giveaway.is_active is True
    
    def test_participation_model_creation(self):
        """Тест создания модели Participation."""
        participation = Participation(
            user_id=1,
            giveaway_id=1,
            is_winner=False
        )
        
        assert participation.user_id == 1
        assert participation.giveaway_id == 1
        assert participation.is_winner is False
    
    def test_user_repr(self):
        """Тест строкового представления User."""
        user = User(id=1, telegram_id=123, username="test")
        repr_str = repr(user)
        assert "User" in repr_str
        assert "123" in repr_str
    
    def test_giveaway_repr(self):
        """Тест строкового представления Giveaway."""
        giveaway = Giveaway(id=1, title="Test", is_active=True)
        repr_str = repr(giveaway)
        assert "Giveaway" in repr_str
        assert "Test" in repr_str
    
    def test_participation_repr(self):
        """Тест строкового представления Participation."""
        participation = Participation(user_id=1, giveaway_id=1, is_winner=False)
        repr_str = repr(participation)
        assert "Participation" in repr_str
