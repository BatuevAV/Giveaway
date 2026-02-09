"""Скрипт для просмотра содержимого базы данных."""

import asyncio
from src.database import Database
from config import settings


async def view_database():
    """Просмотр всех данных в базе."""
    db = Database(settings.DATABASE_URL)
    
    try:
        print("\n" + "="*80)
        print("📊 СОДЕРЖИМОЕ БАЗЫ ДАННЫХ")
        print("="*80 + "\n")
        
        # Пользователи
        users = await get_all_users(db)
        print(f"👥 ПОЛЬЗОВАТЕЛИ ({len(users)}):")
        print("-" * 80)
        for user in users:
            role = "👑 Владелец" if user.is_owner else "👨‍💼 Админ" if user.is_admin else "👤 Пользователь"
            print(f"  ID: {user.telegram_id:12} | {role:15} | @{user.username or 'None':15} | {user.first_name or ''}")
        print()
        
        # Розыгрыши
        giveaways = await db.get_all_giveaways()
        print(f"🎉 РОЗЫГРЫШИ ({len(giveaways)}):")
        print("-" * 80)
        
        if not giveaways:
            print("  Пока нет розыгрышей")
        
        for g in giveaways:
            status = "✅ Активен" if g.is_active else "🔴 Неактивен"
            published = "📢 Опубликован" if g.is_published else "📝 Черновик"
            participants_count = await db.get_participants_count(g.id)
            
            print(f"\n  #{g.id} - {g.title}")
            print(f"    Статус: {status} | {published}")
            print(f"    Создатель ID: {g.creator_id}")
            print(f"    Победителей: {g.winners_count}")
            print(f"    Участников: {participants_count}/{g.max_participants or '∞'}")
            print(f"    Призы: {g.prizes or 'Не указано'}")
            print(f"    Правила: {g.participation_rules or 'Не указано'}")
            print(f"    Картинка: {'✅' if g.image_file_id else '❌'}")
            print(f"    Целевые чаты: {g.target_chats or []}")
            print(f"    Обязательные каналы: {g.required_channels or []}")
            
            if g.starts_at:
                print(f"    Начало: {g.starts_at.strftime('%d.%m.%Y %H:%M')}")
            if g.ends_at:
                print(f"    Окончание: {g.ends_at.strftime('%d.%m.%Y %H:%M')}")
            if g.announce_at:
                print(f"    Анонс: {g.announce_at.strftime('%d.%m.%Y %H:%M')}")
            
            print(f"    Создан: {g.created_at.strftime('%d.%m.%Y %H:%M')}")
            
            # Показать участников этого розыгрыша
            participations = await get_giveaway_participants(db, g.id)
            if participations:
                print(f"    👥 Участники ({len(participations)}):")
                for p in participations:
                    winner_mark = "🏆" if p.is_winner else "  "
                    user = await db.get_user_by_id(p.user_id)
                    username = f"@{user.username}" if user.username else "Без username"
                    print(f"      {winner_mark} TG ID: {user.telegram_id} | {username} | {user.first_name or ''}")
        
        print("\n" + "="*80)
        print("✅ Готово!")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await db.close()


async def get_all_users(db):
    """Получить всех пользователей."""
    from src.models import User
    from sqlalchemy import select
    
    async with db.async_session() as session:
        result = await session.execute(select(User).order_by(User.created_at))
        return result.scalars().all()


async def get_giveaway_participants(db, giveaway_id):
    """Получить участников розыгрыша."""
    from src.models import Participation
    from sqlalchemy import select
    
    async with db.async_session() as session:
        result = await session.execute(
            select(Participation)
            .where(Participation.giveaway_id == giveaway_id)
            .order_by(Participation.participated_at)
        )
        return result.scalars().all()


if __name__ == "__main__":
    asyncio.run(view_database())
