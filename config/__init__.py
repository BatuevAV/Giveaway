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

    # Ollama (AI assistant for automatic content generation)
    OLLAMA_ENABLED: bool = os.getenv('OLLAMA_ENABLED', 'false').lower() in ('1', 'true', 'yes', 'on')
    OLLAMA_BASE_URL: str = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')
    OLLAMA_MODEL: str = os.getenv('OLLAMA_MODEL', 'llama3.1:8b')
    OLLAMA_TIMEOUT_SECONDS: int = int(os.getenv('OLLAMA_TIMEOUT_SECONDS', '45'))
    OLLAMA_MAX_TOKENS: int = int(os.getenv('OLLAMA_MAX_TOKENS', '260'))
    OLLAMA_TEMPERATURE: float = float(os.getenv('OLLAMA_TEMPERATURE', '0.3'))
    
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
