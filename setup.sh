#!/bin/bash

# Скрипт для настройки проекта

echo "🚀 Настройка проекта Giveaway Bot"
echo ""

# Проверка Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 не установлен"
    exit 1
fi

echo "✅ Python 3 найден: $(python3 --version)"

# Создание виртуального окружения
echo ""
echo "📦 Создание виртуального окружения..."
python3 -m venv venv

# Активация и установка зависимостей
echo ""
echo "📥 Установка зависимостей..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Создание .env файла
if [ ! -f .env ]; then
    echo ""
    echo "📝 Создание файла .env..."
    cp .env.example .env
    echo "⚠️  Пожалуйста, отредактируйте файл .env и добавьте токен вашего бота"
else
    echo ""
    echo "ℹ️  Файл .env уже существует"
fi

# Запуск тестов
echo ""
echo "🧪 Запуск тестов..."
pytest tests/ -v

echo ""
echo "✅ Настройка завершена!"
echo ""
echo "📋 Следующие шаги:"
echo "1. Отредактируйте файл .env и добавьте TELEGRAM_BOT_TOKEN"
echo "2. Активируйте виртуальное окружение: source venv/bin/activate"
echo "3. Запустите бота: python run.py"
