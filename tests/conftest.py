"""Конфигурация pytest."""

import pytest
import asyncio
from typing import Generator


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Создание event loop для тестов."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_telegram_id():
    """Фикстура для тестового Telegram ID."""
    return 123456789


@pytest.fixture
def mock_username():
    """Фикстура для тестового username."""
    return "test_user"


@pytest.fixture
def mock_bot_token():
    """Фикстура для тестового токена бота."""
    return "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
