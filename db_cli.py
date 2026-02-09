#!/usr/bin/env python3
"""CLI для работы с базой данных розыгрышей."""

import asyncio
import sys
from datetime import datetime
from sqlalchemy import select, func
from src.database import Database
from src.models import Giveaway, User, Participation
from config import settings


class DatabaseCLI:
    def __init__(self):
        self.db = Database(settings.DATABASE_URL)
    
    async def close(self):
        await self.db.close()
    
    async def list_giveaways(self):
        """Список всех розыгрышей."""
        giveaways = await self.db.get_all_giveaways()
        
        if not giveaways:
            print("\n❌ Розыгрышей не найдено\n")
            return
        
        print(f"\n{'='*90}")
        print(f"📋 РОЗЫГРЫШИ (всего: {len(giveaways)})")
        print(f"{'='*90}")
        
        for g in giveaways:
            participants_count = await self.db.get_participants_count(g.id)
            winners = await self.db.get_winners(g.id)
            
            status_icon = "✅" if g.is_active else "⏸️"
            published_icon = "📢" if g.is_published else "📝"
            
            print(f"\n#{g.id:2} | {status_icon} {published_icon} | {g.title}")
            print(f"     👥 Участников: {participants_count}/{g.max_participants or '∞'}")
            print(f"     🏆 Победителей: {len(winners)}/{g.winners_count}")
            
            if g.ends_at:
                now = datetime.now()
                if g.ends_at > now:
                    delta = g.ends_at - now
                    hours = delta.total_seconds() / 3600
                    print(f"     ⏰ Осталось: {hours:.1f}ч до {g.ends_at.strftime('%d.%m %H:%M')}")
                else:
                    print(f"     ⏰ Завершен: {g.ends_at.strftime('%d.%m.%Y %H:%M')}")
        
        print(f"\n{'='*90}\n")
    
    async def show_giveaway(self, giveaway_id: int):
        """Подробная информация о розыгрыше."""
        giveaway = await self.db.get_giveaway_by_id(giveaway_id)
        
        if not giveaway:
            print(f"\n❌ Розыгрыш #{giveaway_id} не найден\n")
            return
        
        print(f"\n{'='*90}")
        print(f"🎉 РОЗЫГРЫШ #{giveaway.id}")
        print(f"{'='*90}")
        
        print(f"\n📝 Основная информация:")
        print(f"   Название: {giveaway.title}")
        print(f"   Описание: {giveaway.description or '—'}")
        print(f"   Призы: {giveaway.prizes or '—'}")
        print(f"   Правила: {giveaway.participation_rules or '—'}")
        
        print(f"\n📊 Статистика:")
        participants_count = await self.db.get_participants_count(giveaway.id)
        winners = await self.db.get_winners(giveaway.id)
        print(f"   Участников: {participants_count}/{giveaway.max_participants or 'без лимита'}")
        print(f"   Победителей выбрано: {len(winners)}/{giveaway.winners_count}")
        print(f"   Создатель ID: {giveaway.creator_id}")
        
        print(f"\n🔧 Настройки:")
        print(f"   Активен: {'✅ Да' if giveaway.is_active else '❌ Нет'}")
        print(f"   Опубликован: {'✅ Да' if giveaway.is_published else '📝 Нет'}")
        print(f"   Картинка: {'✅ Есть' if giveaway.image_file_id else '❌ Нет'}")
        
        if giveaway.target_chats:
            print(f"\n📢 Целевые чаты ({len(giveaway.target_chats)}):")
            for chat in giveaway.target_chats:
                print(f"   • {chat}")
        
        if giveaway.required_channels:
            print(f"\n🔒 Обязательные каналы ({len(giveaway.required_channels)}):")
            for channel in giveaway.required_channels:
                print(f"   • {channel}")
        
        print(f"\n⏰ Время:")
        if giveaway.starts_at:
            print(f"   Начало: {giveaway.starts_at.strftime('%d.%m.%Y %H:%M')}")
        if giveaway.ends_at:
            print(f"   Окончание: {giveaway.ends_at.strftime('%d.%m.%Y %H:%M')}")
        if giveaway.announce_at:
            print(f"   Анонс: {giveaway.announce_at.strftime('%d.%m.%Y %H:%M')}")
        print(f"   Создан: {giveaway.created_at.strftime('%d.%m.%Y %H:%M')}")
        
        print(f"\n{'='*90}\n")
    
    async def show_participants(self, giveaway_id: int):
        """Показать участников розыгрыша."""
        giveaway = await self.db.get_giveaway_by_id(giveaway_id)
        
        if not giveaway:
            print(f"\n❌ Розыгрыш #{giveaway_id} не найден\n")
            return
        
        participants = await self.db.get_participants(giveaway_id)
        winners = await self.db.get_winners(giveaway_id)
        winner_ids = {w.user_id for w in winners}
        
        print(f"\n{'='*90}")
        print(f"👥 УЧАСТНИКИ РОЗЫГРЫША #{giveaway_id}: {giveaway.title}")
        print(f"{'='*90}")
        print(f"Всего участников: {len(participants)}/{giveaway.max_participants or '∞'}")
        print(f"Победителей: {len(winners)}/{giveaway.winners_count}\n")
        
        if not participants:
            print("❌ Участников пока нет\n")
            return
        
        for i, p in enumerate(participants, 1):
            user = await self.db.get_user_by_id(p.user_id)
            is_winner = p.user_id in winner_ids
            
            winner_mark = "🏆" if is_winner else "  "
            username = f"@{user.username:20}" if user.username else f"{'без username':22}"
            full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
            
            print(f"{winner_mark} {i:2}. {full_name:25} | {username} | TG: {user.telegram_id}")
            print(f"      Участвует с: {p.participated_at.strftime('%d.%m.%Y %H:%M:%S')}")
        
        print(f"\n{'='*90}\n")
    
    async def show_winners(self, giveaway_id: int):
        """Показать победителей."""
        giveaway = await self.db.get_giveaway_by_id(giveaway_id)
        
        if not giveaway:
            print(f"\n❌ Розыгрыш #{giveaway_id} не найден\n")
            return
        
        winners = await self.db.get_winners(giveaway_id)
        
        print(f"\n{'='*90}")
        print(f"🏆 ПОБЕДИТЕЛИ РОЗЫГРЫША #{giveaway_id}: {giveaway.title}")
        print(f"{'='*90}")
        
        if not winners:
            print("\n❌ Победители еще не выбраны\n")
            return
        
        print(f"Выбрано победителей: {len(winners)}/{giveaway.winners_count}\n")
        
        for i, w in enumerate(winners, 1):
            user = await self.db.get_user_by_id(w.user_id)
            username = f"@{user.username}" if user.username else "без username"
            full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
            
            print(f"🏆 {i}. {full_name}")
            print(f"    {username} | Telegram ID: {user.telegram_id}")
            print(f"    Участвовал с: {w.participated_at.strftime('%d.%m.%Y %H:%M')}\n")
        
        print(f"{'='*90}\n")
    
    async def show_users(self):
        """Показать всех пользователей."""
        async with self.db.async_session() as session:
            result = await session.execute(
                select(User).order_by(User.created_at)
            )
            users = result.scalars().all()
        
        print(f"\n{'='*90}")
        print(f"👤 ПОЛЬЗОВАТЕЛИ (всего: {len(users)})")
        print(f"{'='*90}\n")
        
        if not users:
            print("❌ Пользователей не найдено\n")
            return
        
        for i, user in enumerate(users, 1):
            username = f"@{user.username:20}" if user.username else f"{'без username':22}"
            full_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "Без имени"
            
            roles = []
            if user.is_owner:
                roles.append("👑 Владелец")
            if user.is_admin:
                roles.append("👨‍💼 Админ")
            role_text = " | ".join(roles) if roles else "👤 Пользователь"
            
            print(f"{i:2}. {full_name:25} | {username} | TG: {user.telegram_id}")
            print(f"    {role_text} | Создан: {user.created_at.strftime('%d.%m.%Y %H:%M')}\n")
        
        print(f"{'='*90}\n")
    
    async def show_stats(self):
        """Общая статистика."""
        async with self.db.async_session() as session:
            # Подсчитываем данные
            giveaways_result = await session.execute(select(Giveaway))
            giveaways = giveaways_result.scalars().all()
            
            users_result = await session.execute(select(User))
            users = users_result.scalars().all()
            
            participations_result = await session.execute(select(Participation))
            participations = participations_result.scalars().all()
        
        active_giveaways = [g for g in giveaways if g.is_active]
        published_giveaways = [g for g in giveaways if g.is_published]
        completed_giveaways = [g for g in giveaways if g.ends_at and g.ends_at < datetime.now()]
        winners_count = sum(1 for p in participations if p.is_winner)
        
        print(f"\n{'='*90}")
        print(f"📊 СТАТИСТИКА БАЗЫ ДАННЫХ")
        print(f"{'='*90}")
        
        print(f"\n🎉 Розыгрыши:")
        print(f"   Всего создано: {len(giveaways)}")
        print(f"   ✅ Активных: {len(active_giveaways)}")
        print(f"   📢 Опубликованных: {len(published_giveaways)}")
        print(f"   🏁 Завершенных: {len(completed_giveaways)}")
        
        print(f"\n👥 Пользователи:")
        print(f"   Всего: {len(users)}")
        print(f"   👑 Владельцев: {sum(1 for u in users if u.is_owner)}")
        print(f"   👨‍💼 Администраторов: {sum(1 for u in users if u.is_admin)}")
        print(f"   👤 Обычных: {sum(1 for u in users if not u.is_admin and not u.is_owner)}")
        
        print(f"\n🎫 Участие:")
        print(f"   Всего участий: {len(participations)}")
        print(f"   🏆 Победителей: {winners_count}")
        
        if giveaways and len(giveaways) > 0:
            avg_participants = len(participations) / len(giveaways)
            print(f"   📊 Среднее участников на розыгрыш: {avg_participants:.1f}")
            
            if published_giveaways:
                published_with_participants = sum(1 for g in published_giveaways 
                    if any(p.giveaway_id == g.id for p in participations))
                engagement = (published_with_participants / len(published_giveaways)) * 100
                print(f"   📈 Вовлеченность: {engagement:.1f}% (розыгрышей с участниками)")
        
        print(f"\n{'='*90}\n")


def print_help():
    """Справка по командам."""
    print("""
╔════════════════════════════════════════════════════════════════════════════════╗
║                     🎁 CLI ДЛЯ БАЗЫ ДАННЫХ РОЗЫГРЫШЕЙ                          ║
╚════════════════════════════════════════════════════════════════════════════════╝

ИСПОЛЬЗОВАНИЕ: python db_cli.py <команда> [параметры]

📋 КОМАНДЫ:

  list                     - Список всех розыгрышей
  show <id>                - Подробная информация о розыгрыше
  participants <id>        - Участники розыгрыша
  winners <id>             - Победители розыгрыша
  users                    - Все пользователи
  stats                    - Общая статистика
  help                     - Эта справка

💡 ПРИМЕРЫ:

  python db_cli.py list
  python db_cli.py show 1
  python db_cli.py participants 1
  python db_cli.py winners 1
  python db_cli.py users
  python db_cli.py stats

📌 СОВЕТЫ:

  • Для быстрого просмотра всей БД используйте: python view_db.py
  • Для детального анализа используйте db_cli.py с конкретными командами
  • ID розыгрыша можно узнать командой 'list'

""")


async def main():
    """Главная функция."""
    if len(sys.argv) < 2:
        print_help()
        return
    
    command = sys.argv[1].lower()
    cli = DatabaseCLI()
    
    try:
        if command == "help":
            print_help()
        elif command == "list":
            await cli.list_giveaways()
        elif command == "show":
            if len(sys.argv) < 3:
                print("\n❌ Укажите ID: python db_cli.py show <id>\n")
                return
            try:
                giveaway_id = int(sys.argv[2])
                await cli.show_giveaway(giveaway_id)
            except ValueError:
                print("\n❌ ID должен быть числом\n")
        elif command == "participants":
            if len(sys.argv) < 3:
                print("\n❌ Укажите ID: python db_cli.py participants <id>\n")
                return
            try:
                giveaway_id = int(sys.argv[2])
                await cli.show_participants(giveaway_id)
            except ValueError:
                print("\n❌ ID должен быть числом\n")
        elif command == "winners":
            if len(sys.argv) < 3:
                print("\n❌ Укажите ID: python db_cli.py winners <id>\n")
                return
            try:
                giveaway_id = int(sys.argv[2])
                await cli.show_winners(giveaway_id)
            except ValueError:
                print("\n❌ ID должен быть числом\n")
        elif command == "users":
            await cli.show_users()
        elif command == "stats":
            await cli.show_stats()
        else:
            print(f"\n❌ Неизвестная команда: {command}\n")
            print_help()
    finally:
        await cli.close()


if __name__ == "__main__":
    asyncio.run(main())
