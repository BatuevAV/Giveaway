"""Тесты для обработчиков участия в розыгрышах."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src import participation_handlers as ph


class _DummyQuery:
    def __init__(self, data: str):
        self.data = data
        self.answer = AsyncMock()
        self.edit_message_text = AsyncMock()


@pytest.mark.asyncio
async def test_join_giveaway_blocks_admin_user(monkeypatch):
    """Администратор не может участвовать в розыгрыше."""
    monkeypatch.setattr(ph, "is_admin", AsyncMock(return_value=True))
    monkeypatch.setattr(ph, "is_owner", AsyncMock(return_value=False))

    update = SimpleNamespace(
        callback_query=_DummyQuery("join_1"),
        effective_user=SimpleNamespace(id=777, username="admin", first_name="Admin", last_name="User"),
    )
    context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))

    await ph.join_giveaway(update, context)

    update.callback_query.answer.assert_awaited_once()
    args, kwargs = update.callback_query.answer.await_args
    assert "Администраторы" in args[0]
    assert kwargs.get("show_alert") is True


@pytest.mark.asyncio
async def test_join_giveaway_notifies_when_max_reached(monkeypatch):
    """При достижении max_participants вызывается уведомление админов."""
    monkeypatch.setattr(ph, "is_admin", AsyncMock(return_value=False))
    monkeypatch.setattr(ph, "_notify_admins_max_participants", AsyncMock())

    giveaway = SimpleNamespace(
        id=5,
        title="Тестовый розыгрыш",
        is_active=True,
        starts_at=None,
        ends_at=None,
        required_channels=None,
        max_participants=2,
        winners_count=1,
    )
    user = SimpleNamespace(id=42)

    class FakeDb:
        participants_calls = 0

        def __init__(self, *_args, **_kwargs):
            pass

        async def get_giveaway_by_id(self, _gid):
            return giveaway

        async def get_participants_count(self, _gid):
            # 1-й вызов: проверка "еще не заполнено", 2-й: после add_participant -> лимит достигнут
            FakeDb.participants_calls += 1
            return 1 if FakeDb.participants_calls == 1 else 2

        async def get_participation(self, *_args, **_kwargs):
            return None

        async def get_user_by_telegram_id(self, _tgid):
            return user

        async def add_participant(self, *_args, **_kwargs):
            return None

        async def close(self):
            return None

    monkeypatch.setattr(ph, "Database", FakeDb)

    update = SimpleNamespace(
        callback_query=_DummyQuery("join_5"),
        effective_user=SimpleNamespace(id=1001, username="u", first_name="F", last_name="L"),
    )
    context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))

    await ph.join_giveaway(update, context)

    ph._notify_admins_max_participants.assert_awaited_once()
    notify_args = ph._notify_admins_max_participants.await_args.args
    assert notify_args[0].id == 5
    assert notify_args[1] == 2


@pytest.mark.asyncio
async def test_notify_admins_max_participants_sends_buttons(monkeypatch):
    """Уведомление о заполнении лимита отправляется всем админам с нужными кнопками."""
    admins = [SimpleNamespace(telegram_id=11), SimpleNamespace(telegram_id=22)]
    giveaway = SimpleNamespace(id=9, title="Розыгрыш 9", max_participants=10)

    class FakeDb:
        def __init__(self, *_args, **_kwargs):
            pass

        async def get_all_admins(self):
            return admins

        async def close(self):
            return None

    monkeypatch.setattr(ph, "Database", FakeDb)

    send_message = AsyncMock()
    context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message))

    await ph._notify_admins_max_participants(giveaway, 10, context)

    assert send_message.await_count == 2
    first_call = send_message.await_args_list[0]
    reply_markup = first_call.kwargs["reply_markup"]
    assert reply_markup.inline_keyboard[0][0].callback_data == "max_participants_announce_9"
    assert reply_markup.inline_keyboard[0][1].callback_data == "max_participants_skip_9"


@pytest.mark.asyncio
async def test_announce_max_participants_broadcasts_to_target_chats(monkeypatch):
    """Кнопка 'Анонсировать' рассылает сообщение по target_chats."""
    monkeypatch.setattr(ph, "is_admin", AsyncMock(return_value=True))

    giveaway = SimpleNamespace(
        id=12,
        title="Розыгрыш 12",
        max_participants=3,
        target_chats=[-1001, -1002],
    )

    class FakeDb:
        def __init__(self, *_args, **_kwargs):
            pass

        async def get_giveaway_by_id(self, _gid):
            return giveaway

        async def close(self):
            return None

    monkeypatch.setattr(ph, "Database", FakeDb)

    query = _DummyQuery("max_participants_announce_12")
    send_message = AsyncMock()
    update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=1))
    context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message))

    await ph.announce_max_participants(update, context)

    # 2 отправки в target_chats + edit ответа администратору
    assert send_message.await_count == 2
    query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_join_to_max_then_admin_announce_end_to_end(monkeypatch):
    """Интеграционный сценарий: join достигает лимита, админ нажимает 'Анонсировать', идет рассылка в target_chats."""
    monkeypatch.setattr(ph, "is_admin", AsyncMock(side_effect=lambda uid: uid == 9001))
    monkeypatch.setattr(ph, "is_owner", AsyncMock(return_value=False))

    giveaway = SimpleNamespace(
        id=21,
        title="Розыгрыш 21",
        is_active=True,
        starts_at=None,
        ends_at=None,
        required_channels=None,
        max_participants=2,
        winners_count=1,
        target_chats=[-2001, -2002],
    )
    participant_user = SimpleNamespace(id=501)
    admins = [SimpleNamespace(telegram_id=9001)]

    class FakeDb:
        participants_calls = 0

        def __init__(self, *_args, **_kwargs):
            pass

        async def get_giveaway_by_id(self, _gid):
            return giveaway

        async def get_participants_count(self, _gid):
            FakeDb.participants_calls += 1
            # До add_participant -> 1, после -> 2 (достигли лимита)
            return 1 if FakeDb.participants_calls == 1 else 2

        async def get_participation(self, *_args, **_kwargs):
            return None

        async def get_user_by_telegram_id(self, _tgid):
            return participant_user

        async def add_participant(self, *_args, **_kwargs):
            return None

        async def get_all_admins(self):
            return admins

        async def close(self):
            return None

    monkeypatch.setattr(ph, "Database", FakeDb)

    send_message = AsyncMock()
    context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message))

    # 1) Пользователь присоединяется и достигает max_participants.
    join_update = SimpleNamespace(
        callback_query=_DummyQuery("join_21"),
        effective_user=SimpleNamespace(id=7001, username="u", first_name="F", last_name="L"),
    )
    await ph.join_giveaway(join_update, context)

    # Ищем админское уведомление с кнопкой "Анонсировать".
    admin_notify_calls = [
        c for c in send_message.await_args_list
        if c.kwargs.get("chat_id") == 9001 and "reply_markup" in c.kwargs
    ]
    assert admin_notify_calls, "Не найдено уведомление админу о достижении лимита"
    callback_data = admin_notify_calls[0].kwargs["reply_markup"].inline_keyboard[0][0].callback_data
    assert callback_data == "max_participants_announce_21"

    # 2) Админ нажимает "Анонсировать", сообщение уходит в target_chats.
    announce_update = SimpleNamespace(
        callback_query=_DummyQuery(callback_data),
        effective_user=SimpleNamespace(id=9001),
    )
    await ph.announce_max_participants(announce_update, context)

    broadcast_calls = [
        c for c in send_message.await_args_list
        if c.kwargs.get("chat_id") in (-2001, -2002)
    ]
    assert len(broadcast_calls) == 2
    announce_update.callback_query.edit_message_text.assert_awaited_once()


def test_ollama_normalize_prizes_keeps_explicit_simple_club_prize():
    """Для комп-клуба явный простой приз (мышка) не должен перетираться в сертификаты."""
    from src.ollama_client import _normalize_prizes

    prize = _normalize_prizes(
        "Игровая мышка",
        brief="Для компьютерного клуба, разыгрываем мышку",
        raw_response="",
    )
    assert "мыш" in prize.lower()


def test_ollama_normalize_prizes_downgrades_expensive_club_prize():
    """Для комп-клуба дорогие призы по-прежнему заменяются на сертификаты."""
    from src.ollama_client import _normalize_prizes

    prize = _normalize_prizes(
        "Ноутбук ASUS TUF Gaming",
        brief="Для компьютерного клуба",
        raw_response="",
    )
    assert "сертификат" in prize.lower()


def test_ollama_normalize_prizes_prefers_explicit_hint_over_generic_certificates():
    """Если пользователь явно указал приз в brief, сертификаты от модели не должны перетирать этот выбор."""
    from src.ollama_client import _normalize_prizes

    prize = _normalize_prizes(
        "Сертификаты на 500 ₽, 250 ₽ и 100 ₽ для посещения компьютерного клуба",
        brief="Для компьютерного клуба, разыгрываем компьютерную мышку",
        raw_response="",
    )
    assert "мыш" in prize.lower()


def test_ollama_normalize_title_avoids_bad_agreement():
    """Название с плохим согласованием должно заменяться на корректный вариант."""
    from src.ollama_client import _normalize_title

    title = _normalize_title("Жаркий удача 🎮", brief="для игрового клуба")
    assert "жаркий удача" not in title.lower()


def test_ollama_normalize_description_syncs_with_prize():
    """Если описание осталось со старым типом приза, оно синхронизируется с нормализованным призом."""
    from src.ollama_client import _normalize_description

    desc = _normalize_description(
        "Среди участников разыграем: Сертификаты на 500 ₽, 250 ₽ и 100 ₽.",
        "Игровая компьютерная мышь",
    )
    assert "мыш" in desc.lower()


def test_ollama_normalize_prizes_fixes_mixed_script_word():
    """Mixed кириллица/латиница в слове должна исправляться."""
    from src.ollama_client import _normalize_prizes

    prize = _normalize_prizes(
        "Компьюterная мышь",
        brief="Для компьютерного клуба, приз: компьютерная мышь",
        raw_response="",
    )
    assert "компьютерная" in prize.lower()


def test_ollama_normalize_prizes_supports_ranked_places_from_text():
    """Призы по местам должны сохраняться как многострочный список."""
    from src.ollama_client import _normalize_prizes

    prize = _normalize_prizes(
        "1 место: компьютерная мышь; 2 место: сертификат на 500 рублей",
        brief="Компьютерный клуб, геймеры",
        raw_response="",
    )
    assert "1 место" in prize.lower()
    assert "2 место" in prize.lower()
    assert "мыш" in prize.lower()
    assert "сертификат" in prize.lower()


def test_ollama_normalize_prizes_supports_ranked_places_from_structured_list():
    """Structured list с place/position должен превращаться в призы по местам."""
    from src.ollama_client import _normalize_prizes

    prize = _normalize_prizes(
        [
            {"place": 1, "name": "Компьютерная мышь"},
            {"place": 2, "name": "Сертификат на 500 рублей"},
        ],
        brief="Розыгрыш для геймеров",
        raw_response="",
    )
    assert "1 место" in prize.lower()
    assert "2 место" in prize.lower()
