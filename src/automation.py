"""Автоматизация анонсов и завершения розыгрышей."""

import logging
import random
from datetime import datetime
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import settings
from src.database import Database

logger = logging.getLogger(__name__)


def format_announcement_text(giveaway) -> str:
    """Формирование текста анонса."""
    text = f"🎉 <b>{giveaway.title}</b> 🎉\n\n"

    if giveaway.description:
        text += f"{giveaway.description}\n\n"

    if giveaway.prizes:
        text += f"🏆 <b>Призы:</b>\n{giveaway.prizes}\n\n"

    text += f"👥 Победителей: {giveaway.winners_count}\n"

    if giveaway.max_participants:
        text += f"📊 Максимум участников: {giveaway.max_participants}\n"

    if giveaway.starts_at:
        text += f"📅 Начало: {giveaway.starts_at.strftime('%d.%m.%Y %H:%M')}\n"

    if giveaway.ends_at:
        text += f"🏁 Окончание: {giveaway.ends_at.strftime('%d.%m.%Y %H:%M')}\n"

    if giveaway.participation_rules:
        text += f"\n📋 <b>Условия участия:</b>\n{giveaway.participation_rules}\n"

    text += "\n👇 <b>Нажмите кнопку ниже чтобы участвовать!</b>"
    return text


def _winner_label(user) -> str:
    if user.username:
        return f"@{user.username}"
    full_name = " ".join(filter(None, [user.first_name, user.last_name])).strip()
    return full_name or f"ID: {user.telegram_id}"


async def publish_giveaway(giveaway_id: int, bot) -> dict[str, Any]:
    """
    Публикует розыгрыш в target_chats.

    Returns:
        {
            success_count: int,
            failed_chats: list[str],
            total: int,
            giveaway: Giveaway | None,
        }
    """
    db = Database(settings.DATABASE_URL)
    try:
        giveaway = await db.get_giveaway(giveaway_id)
        if not giveaway:
            return {"success_count": 0, "failed_chats": ["giveaway_not_found"], "total": 0, "giveaway": None}

        now = datetime.utcnow()
        if giveaway.ends_at and giveaway.ends_at <= now:
            logger.info(
                "Skip auto publish for giveaway %s: ended at %s (now %s)",
                giveaway_id,
                giveaway.ends_at,
                now
            )
            return {"success_count": 0, "failed_chats": ["giveaway_ended"], "total": 0, "giveaway": giveaway}

        if giveaway.starts_at and giveaway.ends_at and giveaway.ends_at <= giveaway.starts_at:
            logger.warning(
                "Skip auto publish for giveaway %s: invalid dates starts_at=%s ends_at=%s",
                giveaway_id,
                giveaway.starts_at,
                giveaway.ends_at
            )
            return {"success_count": 0, "failed_chats": ["invalid_dates"], "total": 0, "giveaway": giveaway}

        if not giveaway.target_chats:
            return {"success_count": 0, "failed_chats": ["target_chats_empty"], "total": 0, "giveaway": giveaway}

        announcement_text = giveaway.announcement_text or format_announcement_text(giveaway)
        keyboard = [[InlineKeyboardButton("🎁 Участвовать в розыгрыше", callback_data=f"join_{giveaway_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        success_count = 0
        failed_chats: list[str] = []
        for chat_id in giveaway.target_chats:
            try:
                if giveaway.image_file_id:
                    await bot.send_photo(
                        chat_id=chat_id,
                        photo=giveaway.image_file_id,
                        caption=announcement_text,
                        reply_markup=reply_markup,
                        parse_mode="HTML",
                    )
                else:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=announcement_text,
                        reply_markup=reply_markup,
                        parse_mode="HTML",
                    )
                success_count += 1
            except Exception as exc:
                logger.error("Auto publish failed for giveaway %s in chat %s: %s", giveaway_id, chat_id, exc)
                failed_chats.append(f"{chat_id}: {exc}")

        if success_count > 0:
            await db.update_giveaway(giveaway_id, is_published=True)

        return {
            "success_count": success_count,
            "failed_chats": failed_chats,
            "total": len(giveaway.target_chats),
            "giveaway": giveaway,
        }
    finally:
        await db.close()


async def _notify_winners(bot, db: Database, giveaway, winners) -> tuple[int, int]:
    success_count = 0
    failed_count = 0

    for winner in winners:
        user = await db.get_user_by_id(winner.user_id)
        if not user:
            failed_count += 1
            continue
        try:
            text = (
                "🎉 <b>Поздравляем!</b>\n\n"
                "Вы стали победителем в розыгрыше:\n"
                f"📝 <b>{giveaway.title}</b>\n\n"
            )
            if giveaway.prizes:
                text += f"🏆 Ваш приз: {giveaway.prizes}\n\n"
            text += "Для получения приза свяжитесь с организатором."
            await bot.send_message(chat_id=user.telegram_id, text=text, parse_mode="HTML")
            success_count += 1
        except Exception as exc:
            logger.error("Failed to notify winner %s for giveaway %s: %s", user.telegram_id, giveaway.id, exc)
            failed_count += 1

    return success_count, failed_count


async def _announce_results_in_chats(bot, db: Database, giveaway, winners) -> tuple[int, int]:
    if not giveaway.target_chats:
        return 0, 0

    winner_lines = []
    for index, winner in enumerate(winners, 1):
        user = await db.get_user_by_id(winner.user_id)
        if user:
            winner_lines.append(f"{index}. {_winner_label(user)}")

    if winner_lines:
        text = (
            f"🎉 <b>Итоги розыгрыша #{giveaway.id}</b>\n\n"
            f"📝 <b>{giveaway.title}</b>\n"
            f"🏆 Победителей: {len(winner_lines)}\n\n"
            f"<b>Победители:</b>\n" + "\n".join(winner_lines)
        )
    else:
        text = (
            f"ℹ️ <b>Итоги розыгрыша #{giveaway.id}</b>\n\n"
            f"📝 <b>{giveaway.title}</b>\n"
            "В розыгрыше не оказалось участников, победители не определены."
        )

    success_count = 0
    failed_count = 0
    for chat_id in giveaway.target_chats:
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
            success_count += 1
        except Exception as exc:
            logger.error("Failed to publish results for giveaway %s in chat %s: %s", giveaway.id, chat_id, exc)
            failed_count += 1

    return success_count, failed_count


async def _notify_admins(bot, db: Database, text: str) -> tuple[int, int]:
    admins = await db.get_all_admins()
    success_count = 0
    failed_count = 0
    for admin in admins:
        try:
            await bot.send_message(chat_id=admin.telegram_id, text=text, parse_mode="HTML")
            success_count += 1
        except Exception as exc:
            logger.error("Failed to notify admin %s: %s", admin.telegram_id, exc)
            failed_count += 1
    return success_count, failed_count


async def run_automatic_draw(giveaway_id: int, bot) -> dict[str, Any]:
    """
    Автоматически завершает розыгрыш:
    1) выбирает победителей;
    2) отправляет итоги в целевые чаты;
    3) шлет ЛС победителям;
    4) уведомляет администраторов о результате.
    """
    db = Database(settings.DATABASE_URL)
    try:
        giveaway = await db.get_giveaway_by_id(giveaway_id)
        if not giveaway:
            return {"ok": False, "reason": "not_found"}

        now = datetime.utcnow()
        if giveaway.ends_at and giveaway.ends_at > now:
            return {"ok": False, "reason": "not_finished"}

        existing_winners = await db.get_winners(giveaway_id)
        if existing_winners:
            # Гарантируем остановку набора участников после конца.
            if giveaway.is_active:
                await db.update_giveaway(giveaway_id, is_active=False)
            return {"ok": False, "reason": "already_drawn"}

        participants = await db.get_participants(giveaway_id)
        if not participants:
            await db.update_giveaway(giveaway_id, is_active=False)
            results_ok, results_fail = await _announce_results_in_chats(bot, db, giveaway, [])
            admin_text = (
                f"🤖 <b>Автозавершение розыгрыша #{giveaway.id}</b>\n\n"
                f"📝 {giveaway.title}\n"
                "Победители не выбраны: участников нет.\n"
                f"📢 Уведомление в чаты: {results_ok} успешно, {results_fail} ошибок."
            )
            await _notify_admins(bot, db, admin_text)
            return {"ok": True, "winners_count": 0}

        winners_limit = min(giveaway.winners_count, len(participants))
        winners = random.sample(participants, winners_limit)
        await db.set_winners(giveaway_id, [w.user_id for w in winners])
        await db.update_giveaway(giveaway_id, is_active=False)

        chat_success, chat_failed = await _announce_results_in_chats(bot, db, giveaway, winners)
        notify_success, notify_failed = await _notify_winners(bot, db, giveaway, winners)

        winner_lines = []
        for winner in winners:
            user = await db.get_user_by_id(winner.user_id)
            if user:
                winner_lines.append(_winner_label(user))

        admin_text = (
            f"🤖 <b>Автозавершение розыгрыша #{giveaway.id}</b>\n\n"
            f"📝 {giveaway.title}\n"
            f"🏆 Победители: {', '.join(winner_lines) if winner_lines else '—'}\n"
            f"📨 ЛС победителям: {notify_success} успешно, {notify_failed} ошибок\n"
            f"📢 Итоги в чаты: {chat_success} успешно, {chat_failed} ошибок"
        )
        await _notify_admins(bot, db, admin_text)

        return {
            "ok": True,
            "winners_count": len(winners),
            "notify_success": notify_success,
            "notify_failed": notify_failed,
            "chat_success": chat_success,
            "chat_failed": chat_failed,
        }
    finally:
        await db.close()
