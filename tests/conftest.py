"""
Общие фикстуры для тестов
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock


@pytest.fixture(scope="session")
def event_loop():
    """Создать event loop для async тестов"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_settings():
    """Мок настроек приложения"""
    settings = MagicMock()
    settings.openai_api_key = "test-api-key"
    settings.database_url = "sqlite:///test.db"
    settings.telegram_bot_token = "test-bot-token"
    return settings


@pytest.fixture
def mock_db_session():
    """Мок сессии БД"""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    return session
