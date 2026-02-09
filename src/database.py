"""Работа с базой данных."""

import logging
from typing import Optional
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select, delete

from src.models import Base, User, Giveaway, Participation

logger = logging.getLogger(__name__)


class Database:
    """Класс для работы с базой данных."""
    
    def __init__(self, database_url: str):
        """
        Инициализация подключения к БД.
        
        Args:
            database_url: URL подключения к базе данных
        """
        self.engine = create_async_engine(database_url, echo=False)
        self.async_session = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
    
    async def init_db(self) -> None:
        """Инициализация базы данных (создание таблиц)."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("База данных инициализирована")
    
    async def get_user_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        """
        Получение пользователя по Telegram ID.
        
        Args:
            telegram_id: ID пользователя в Telegram
        
        Returns:
            Объект пользователя или None
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            return result.scalar_one_or_none()
    
    async def create_user(self, telegram_id: int, username: str = None, 
                         first_name: str = None, last_name: str = None) -> User:
        """
        Создание нового пользователя.
        
        Args:
            telegram_id: ID пользователя в Telegram
            username: Имя пользователя
            first_name: Имя
            last_name: Фамилия
        
        Returns:
            Созданный объект пользователя
        """
        async with self.async_session() as session:
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            logger.info(f"Создан пользователь: {telegram_id}")
            return user
    
    async def get_or_create_user(self, telegram_id: int, username: str = None,
                                 first_name: str = None, last_name: str = None) -> User:
        """
        Получение или создание пользователя.
        
        Args:
            telegram_id: ID пользователя в Telegram
            username: Имя пользователя
            first_name: Имя
            last_name: Фамилия
        
        Returns:
            Объект пользователя
        """
        user = await self.get_user_by_telegram_id(telegram_id)
        if not user:
            user = await self.create_user(telegram_id, username, first_name, last_name)
        return user
    
    async def set_admin_status(self, telegram_id: int, is_admin: bool) -> None:
        """
        Установка статуса администратора.
        
        Args:
            telegram_id: ID пользователя в Telegram
            is_admin: Статус администратора
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()
            
            if user:
                user.is_admin = is_admin
                await session.commit()
                logger.info(f"Admin status for {telegram_id} set to {is_admin}")
    
    async def set_owner_status(self, telegram_id: int, is_owner: bool) -> None:
        """
        Установка статуса владельца.
        
        Args:
            telegram_id: ID пользователя в Telegram
            is_owner: Статус владельца
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()
            
            if user:
                user.is_owner = is_owner
                await session.commit()
                logger.info(f"Owner status for {telegram_id} set to {is_owner}")
    
    async def get_all_admins(self) -> list[User]:
        """
        Получение списка всех администраторов.
        
        Returns:
            Список пользователей с правами администратора или владельца
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(User).where((User.is_admin == True) | (User.is_owner == True))
            )
            return result.scalars().all()
    
    async def create_giveaway(self, creator_id: int, **kwargs) -> Giveaway:
        """
        Создание нового розыгрыша.
        
        Args:
            creator_id: ID создателя розыгрыша
            **kwargs: Параметры розыгрыша
        
        Returns:
            Созданный розыгрыш
        """
        async with self.async_session() as session:
            giveaway = Giveaway(
                creator_id=creator_id,
                **kwargs
            )
            session.add(giveaway)
            await session.commit()
            await session.refresh(giveaway)
            logger.info(f"Created giveaway: {giveaway.id} by user {creator_id}")
            return giveaway
    
    async def update_giveaway(self, giveaway_id: int, **kwargs) -> Giveaway:
        """
        Обновление розыгрыша.
        
        Args:
            giveaway_id: ID розыгрыша
            **kwargs: Параметры для обновления
        
        Returns:
            Обновленный розыгрыш
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(Giveaway).where(Giveaway.id == giveaway_id)
            )
            giveaway = result.scalar_one_or_none()
            
            if not giveaway:
                raise ValueError(f"Giveaway with id {giveaway_id} not found")
            
            # Обновляем только переданные поля
            for key, value in kwargs.items():
                if hasattr(giveaway, key):
                    setattr(giveaway, key, value)
            
            await session.commit()
            await session.refresh(giveaway)
            logger.info(f"Updated giveaway: {giveaway.id}")
            return giveaway
    
    async def get_active_giveaways(self) -> list[Giveaway]:
        """
        Получение всех активных розыгрышей.
        
        Returns:
            Список активных розыгрышей
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(Giveaway).where(Giveaway.is_active == True)
            )
            return result.scalars().all()
    
    async def get_all_giveaways(self) -> list[Giveaway]:
        """
        Получение всех розыгрышей.
        
        Returns:
            Список всех розыгрышей
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(Giveaway).order_by(Giveaway.created_at.desc())
            )
            return result.scalars().all()
    
    async def get_giveaway_by_id(self, giveaway_id: int) -> Giveaway:
        """
        Получение розыгрыша по ID.
        
        Args:
            giveaway_id: ID розыгрыша
        
        Returns:
            Объект розыгрыша или None
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(Giveaway).where(Giveaway.id == giveaway_id)
            )
            return result.scalar_one_or_none()
    
    async def get_giveaway(self, giveaway_id: int) -> Giveaway:
        """
        Алиас для get_giveaway_by_id.
        Получение розыгрыша по ID.
        
        Args:
            giveaway_id: ID розыгрыша
        
        Returns:
            Объект розыгрыша или None
        """
        return await self.get_giveaway_by_id(giveaway_id)
    
    async def get_participants_count(self, giveaway_id: int) -> int:
        """
        Получение количества участников розыгрыша.
        
        Args:
            giveaway_id: ID розыгрыша
        
        Returns:
            Количество участников
        """
        async with self.async_session() as session:
            from sqlalchemy import func
            result = await session.execute(
                select(func.count(Participation.id))
                .where(Participation.giveaway_id == giveaway_id)
            )
            return result.scalar() or 0
    
    async def check_user_membership(self, user_id: int, chat_id: int, bot) -> bool:
        """
        Проверка подписки пользователя на канал/группу.
        
        Args:
            user_id: ID пользователя
            chat_id: ID канала/группы
            bot: Экземпляр бота
            
        Returns:
            True если пользователь подписан, False иначе
        """
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            # Проверяем статус: creator, administrator, member
            return member.status in ['creator', 'administrator', 'member']
        except Exception as e:
            logger.error(f"Error checking membership for user {user_id} in chat {chat_id}: {e}")
            return False
    
    async def add_participant(self, user_id: int, giveaway_id: int) -> Participation:
        """
        Добавление участника в розыгрыш.
        
        Args:
            user_id: ID пользователя
            giveaway_id: ID розыгрыша
            
        Returns:
            Объект Participation
        """
        async with self.async_session() as session:
            # Проверяем, есть ли уже запись об участии
            existing = await session.execute(
                select(Participation).where(
                    Participation.user_id == user_id,
                    Participation.giveaway_id == giveaway_id
                )
            )
            if existing.scalar_one_or_none():
                logger.warning(f"User {user_id} already participating in giveaway {giveaway_id}")
                return existing.scalar_one_or_none()
            
            participation = Participation(
                user_id=user_id,
                giveaway_id=giveaway_id
            )
            session.add(participation)
            await session.commit()
            await session.refresh(participation)
            logger.info(f"User {user_id} added to giveaway {giveaway_id}")
            return participation
    
    async def get_participation(self, user_id: int, giveaway_id: int):
        """
        Получение участия пользователя в розыгрыше.
        
        Args:
            user_id: ID пользователя
            giveaway_id: ID розыгрыша
            
        Returns:
            Объект Participation или None
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(Participation).where(
                    Participation.user_id == user_id,
                    Participation.giveaway_id == giveaway_id
                )
            )
            return result.scalar_one_or_none()
    
    async def get_participants(self, giveaway_id: int) -> list[Participation]:
        """
        Получить всех участников розыгрыша.
        
        Args:
            giveaway_id: ID розыгрыша
            
        Returns:
            Список объектов Participation
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(Participation).where(
                    Participation.giveaway_id == giveaway_id
                )
            )
            return result.scalars().all()
    
    async def get_winners(self, giveaway_id: int) -> list[Participation]:
        """
        Получить всех победителей розыгрыша.
        
        Args:
            giveaway_id: ID розыгрыша
            
        Returns:
            Список объектов Participation с is_winner=True
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(Participation).where(
                    Participation.giveaway_id == giveaway_id,
                    Participation.is_winner == True
                )
            )
            return result.scalars().all()
    
    async def set_winners(self, giveaway_id: int, user_ids: list[int]) -> None:
        """
        Отметить пользователей как победителей.
        
        Args:
            giveaway_id: ID розыгрыша
            user_ids: Список ID пользователей (из таблицы users, не telegram_id)
        """
        async with self.async_session() as session:
            # Сначала сбрасываем всех победителей (на случай повторного розыгрыша)
            await session.execute(
                select(Participation).where(
                    Participation.giveaway_id == giveaway_id,
                    Participation.is_winner == True
                )
            )
            result = await session.execute(
                select(Participation).where(
                    Participation.giveaway_id == giveaway_id,
                    Participation.is_winner == True
                )
            )
            old_winners = result.scalars().all()
            for winner in old_winners:
                winner.is_winner = False
            
            # Отмечаем новых победителей
            for user_id in user_ids:
                result = await session.execute(
                    select(Participation).where(
                        Participation.giveaway_id == giveaway_id,
                        Participation.user_id == user_id
                    )
                )
                participation = result.scalar_one_or_none()
                if participation:
                    participation.is_winner = True
            
            await session.commit()
    
    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        """
        Получить пользователя по ID из таблицы users.
        
        Args:
            user_id: ID пользователя в таблице users
            
        Returns:
            Объект User или None
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            return result.scalar_one_or_none()

    async def delete_giveaway(self, giveaway_id: int) -> tuple[bool, int]:
        """
        Удаление розыгрыша и связанных участий.

        Args:
            giveaway_id: ID розыгрыша

        Returns:
            (удален_ли_розыгрыш, сколько_участий_удалено)
        """
        async with self.async_session() as session:
            participation_result = await session.execute(
                delete(Participation).where(Participation.giveaway_id == giveaway_id)
            )
            giveaway_result = await session.execute(
                delete(Giveaway).where(Giveaway.id == giveaway_id)
            )
            await session.commit()

            deleted_participations = participation_result.rowcount or 0
            deleted_giveaway = (giveaway_result.rowcount or 0) > 0

            if deleted_giveaway:
                logger.info(
                    "Deleted giveaway %s (removed participations: %s)",
                    giveaway_id,
                    deleted_participations
                )

            return deleted_giveaway, deleted_participations
    
    async def close(self) -> None:
        """Закрытие подключения к БД."""
        await self.engine.dispose()
        logger.info("Подключение к БД закрыто")
