"""Модели данных для базы данных."""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, JSON
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class User(Base):
    """Модель пользователя."""
    
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False, index=True)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    is_admin = Column(Boolean, default=False)
    is_owner = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Связи
    participations = relationship("Participation", back_populates="user")
    
    def __repr__(self):
        return f"<User(id={self.id}, telegram_id={self.telegram_id}, username='{self.username}', is_admin={self.is_admin}, is_owner={self.is_owner})>"


class Giveaway(Base):
    """Модель розыгрыша."""
    
    __tablename__ = 'giveaways'
    
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    creator_id = Column(Integer, nullable=False)
    
    # Параметры розыгрыша
    winners_count = Column(Integer, default=1)
    max_participants = Column(Integer, nullable=True)  # Максимальное количество участников
    prizes = Column(String, nullable=True)  # JSON или текст с описанием призов
    
    # Условия участия
    participation_rules = Column(String, nullable=True)  # Условия для участия
    
    # Медиа
    image_file_id = Column(String, nullable=True)  # Telegram file_id картинки
    image_url = Column(String, nullable=True)  # URL картинки
    
    # Целевые чаты для публикации
    target_chats = Column(JSON, nullable=True)  # Список chat_id для публикации анонса
    
    # Обязательные каналы для подписки
    required_channels = Column(JSON, nullable=True)  # Список chat_id обязательных каналов для участия
    
    # Статусы и даты
    is_active = Column(Boolean, default=True)
    is_published = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Временные рамки
    announce_at = Column(DateTime, nullable=True)  # Когда опубликовать анонс
    starts_at = Column(DateTime, nullable=True)  # Начало розыгрыша
    ends_at = Column(DateTime, nullable=True)  # Окончание розыгрыша
    
    # Текст анонса
    announcement_text = Column(String, nullable=True)  # Кастомный текст анонса
    
    # Связи
    participations = relationship("Participation", back_populates="giveaway")
    
    def __repr__(self):
        return f"<Giveaway(id={self.id}, title='{self.title}', is_active={self.is_active}, is_published={self.is_published})>"


class Participation(Base):
    """Модель участия в розыгрыше."""
    
    __tablename__ = 'participations'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    giveaway_id = Column(Integer, ForeignKey('giveaways.id'), nullable=False)
    is_winner = Column(Boolean, default=False)
    participated_at = Column(DateTime, default=datetime.utcnow)
    
    # Связи
    user = relationship("User", back_populates="participations")
    giveaway = relationship("Giveaway", back_populates="participations")
    
    def __repr__(self):
        return f"<Participation(user_id={self.user_id}, giveaway_id={self.giveaway_id}, is_winner={self.is_winner})>"
