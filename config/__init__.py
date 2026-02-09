"""Конфигурация приложения."""

import os
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()


class Settings:
    """Настройки приложения."""
    
    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv('TELEGRAM_BOT_TOKEN', '')
    
    # Database
    DATABASE_URL: str = os.getenv('DATABASE_URL', 'sqlite+aiosqlite:///giveaway.db')
    
    # Owner (главный администратор)
    OWNER_ID: int = int(os.getenv('OWNER_ID', '0')) if os.getenv('OWNER_ID') else None
    
    # Admin
    ADMIN_IDS: list[int] = [
        int(admin_id.strip()) 
        for admin_id in os.getenv('ADMIN_IDS', '').split(',') 
        if admin_id.strip()
    ]
    
    def validate(self) -> bool:
        """
        Валидация настроек.
        
        Returns:
            True если настройки валидны, иначе False
        """
        if not self.TELEGRAM_BOT_TOKEN:
            print("Ошибка: TELEGRAM_BOT_TOKEN не установлен")
            return False
        if not self.OWNER_ID:
            print("Предупреждение: OWNER_ID не установлен. Установите его для полного доступа к функциям владельца.")
        return True


settings = Settings()
