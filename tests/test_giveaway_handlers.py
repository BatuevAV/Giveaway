"""Тесты для обработчиков создания розыгрыша."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.ext import ConversationHandler

from src.giveaway_handlers import cancel_giveaway_creation_callback


@pytest.mark.asyncio
async def test_cancel_giveaway_creation_callback_clears_context():
    """Кнопка отмены должна завершать мастер и очищать данные."""
    query = SimpleNamespace(answer=AsyncMock(), edit_message_text=AsyncMock())
    update = SimpleNamespace(callback_query=query)
    context = SimpleNamespace(user_data={"giveaway": {"title": "draft"}, "ai_brief": "x"})

    state = await cancel_giveaway_creation_callback(update, context)

    assert state == ConversationHandler.END
    assert context.user_data == {}
    query.answer.assert_awaited_once()
    query.edit_message_text.assert_awaited_once()

