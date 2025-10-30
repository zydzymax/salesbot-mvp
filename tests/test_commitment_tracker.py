"""
Тесты для Commitment Tracker
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timedelta
import json

from app.analysis.commitment_tracker import (
    CommitmentTracker,
    CommitmentData,
    Commitment
)


@pytest.fixture
def tracker():
    """Фикстура для создания экземпляра CommitmentTracker"""
    return CommitmentTracker()


@pytest.fixture
def sample_transcription_with_commitments():
    """Пример транскрипции с обещаниями"""
    return """
    Менеджер: Хорошо, я отправлю вам коммерческое предложение сегодня до 18:00.
    Клиент: Отлично.
    Менеджер: И перезвоню завтра в 10 утра для обсуждения деталей.
    Клиент: Договорились.
    Менеджер: Также согласую с директором возможность скидки и сообщу до конца недели.
    """


@pytest.fixture
def sample_transcription_no_commitments():
    """Пример транскрипции без обещаний"""
    return """
    Менеджер: Как у вас дела?
    Клиент: Нормально, спасибо.
    Менеджер: Будем на связи.
    Клиент: Хорошо.
    """


class TestCommitmentTracker:
    """Тесты для трекера обещаний"""

    @pytest.mark.asyncio
    async def test_extract_commitments_short_transcription(self, tracker):
        """Тест: короткая транскрипция"""
        result = await tracker.extract_commitments_from_call("короткий текст")

        assert result == []

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_extract_commitments_success(
        self,
        mock_post,
        tracker,
        sample_transcription_with_commitments
    ):
        """Тест: успешное извлечение обещаний"""
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            'choices': [{
                'message': {
                    'content': json.dumps([
                        {
                            "text": "Отправлю коммерческое предложение",
                            "deadline": "сегодня до 18:00"
                        },
                        {
                            "text": "Перезвоню для обсуждения деталей",
                            "deadline": "завтра в 10:00"
                        }
                    ])
                }
            }]
        }
        mock_post.return_value = mock_response

        result = await tracker.extract_commitments_from_call(
            sample_transcription_with_commitments
        )

        assert isinstance(result, list)
        assert len(result) > 0
        for commitment in result:
            assert isinstance(commitment, CommitmentData)
            assert commitment.text
            assert commitment.deadline
            assert commitment.category
            assert commitment.priority

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_extract_commitments_no_commitments(
        self,
        mock_post,
        tracker,
        sample_transcription_no_commitments
    ):
        """Тест: нет обещаний в транскрипции"""
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            'choices': [{
                'message': {
                    'content': '[]'
                }
            }]
        }
        mock_post.return_value = mock_response

        result = await tracker.extract_commitments_from_call(
            sample_transcription_no_commitments
        )

        assert result == []

    def test_categorize_commitment(self, tracker):
        """Тест: определение категории обещания"""
        # Документы
        assert tracker._categorize_commitment("Отправлю коммерческое предложение") == "document"
        assert tracker._categorize_commitment("Вышлю договор") == "document"
        assert tracker._categorize_commitment("Пришлю презентацию") == "document"

        # Звонки
        assert tracker._categorize_commitment("Перезвоню завтра") == "call"
        assert tracker._categorize_commitment("Свяжусь с вами") == "call"

        # Встречи
        assert tracker._categorize_commitment("Приедем на встречу") == "meeting"
        assert tracker._categorize_commitment("Организуем демо") == "meeting"

        # Согласование
        assert tracker._categorize_commitment("Согласую скидку") == "approval"
        assert tracker._categorize_commitment("Уточню у директора") == "approval"

        # Информация
        assert tracker._categorize_commitment("Отправлю информацию") == "information"

        # Другое
        assert tracker._categorize_commitment("Что-то неопределенное") == "other"

    def test_parse_deadline_today(self, tracker):
        """Тест: парсинг дедлайна - сегодня"""
        deadline = tracker._parse_deadline("сегодня до 18:00")

        assert deadline.date() == datetime.now().date()
        assert deadline.hour == 18
        assert deadline.minute == 0

        # Без времени - по умолчанию 18:00
        deadline_no_time = tracker._parse_deadline("сегодня")
        assert deadline_no_time.date() == datetime.now().date()
        assert deadline_no_time.hour == 18

    def test_parse_deadline_tomorrow(self, tracker):
        """Тест: парсинг дедлайна - завтра"""
        deadline = tracker._parse_deadline("завтра в 10:00")

        tomorrow = datetime.now() + timedelta(days=1)
        assert deadline.date() == tomorrow.date()
        assert deadline.hour == 10
        assert deadline.minute == 0

    def test_parse_deadline_through_days(self, tracker):
        """Тест: парсинг дедлайна - через N дней"""
        deadline = tracker._parse_deadline("через 3 дня")

        expected_date = (datetime.now() + timedelta(days=3)).date()
        assert deadline.date() == expected_date

    def test_parse_deadline_through_hours(self, tracker):
        """Тест: парсинг дедлайна - через N часов"""
        deadline = tracker._parse_deadline("через 2 часа")

        expected_time = datetime.now() + timedelta(hours=2)
        # Проверяем с точностью до минуты
        assert abs((deadline - expected_time).total_seconds()) < 60

    def test_parse_deadline_this_week(self, tracker):
        """Тест: парсинг дедлайна - на этой неделе"""
        deadline = tracker._parse_deadline("на этой неделе")

        # Должно быть до пятницы
        assert deadline.weekday() <= 4  # 0-4 это пн-пт

    def test_parse_deadline_default(self, tracker):
        """Тест: дефолтный дедлайн"""
        deadline = tracker._parse_deadline("неопределенное время")

        # По умолчанию - завтра в 12:00
        tomorrow = datetime.now() + timedelta(days=1)
        assert deadline.date() == tomorrow.date()
        assert deadline.hour == 12

    def test_calculate_priority_high_urgent(self, tracker):
        """Тест: высокий приоритет - срочно"""
        now = datetime.now()
        soon = now + timedelta(hours=2)

        priority = tracker._calculate_priority("Срочно нужна скидка", soon)
        assert priority == 'high'

    def test_calculate_priority_high_keywords(self, tracker):
        """Тест: высокий приоритет - важные слова"""
        tomorrow = datetime.now() + timedelta(days=1)

        priority = tracker._calculate_priority("Обязательно согласую с директором", tomorrow)
        assert priority == 'high'

    def test_calculate_priority_medium(self, tracker):
        """Тест: средний приоритет"""
        tomorrow = datetime.now() + timedelta(hours=20)

        priority = tracker._calculate_priority("Отправлю документы", tomorrow)
        assert priority == 'medium'

    def test_calculate_priority_low(self, tracker):
        """Тест: низкий приоритет"""
        next_week = datetime.now() + timedelta(days=5)

        priority = tracker._calculate_priority("Вышлю информацию", next_week)
        assert priority == 'low'

    def test_format_reminder_message(self, tracker):
        """Тест: форматирование напоминания"""
        commitment = MagicMock(spec=Commitment)
        commitment.commitment_text = "Отправить КП"
        commitment.deadline = datetime.now() + timedelta(hours=1)

        message = tracker._format_reminder_message(commitment)

        assert "НАПОМИНАНИЕ" in message
        assert "Отправить КП" in message
        assert "Дедлайн" in message

    def test_format_escalation_message(self, tracker):
        """Тест: форматирование эскалации"""
        commitment1 = MagicMock(spec=Commitment)
        commitment1.commitment_text = "Отправить КП"
        commitment1.deadline = datetime.now() - timedelta(hours=2)

        commitment2 = MagicMock(spec=Commitment)
        commitment2.commitment_text = "Перезвонить клиенту"
        commitment2.deadline = datetime.now() - timedelta(hours=5)

        commitments = [commitment1, commitment2]

        message = tracker._format_escalation_message(commitments, "Иван Иванов")

        assert "НЕ ВЫПОЛНЕНЫ" in message
        assert "Иван Иванов" in message
        assert str(len(commitments)) in message
        assert "Отправить КП" in message

    def test_commitment_to_dict(self, tracker):
        """Тест: преобразование модели в dict"""
        commitment = MagicMock(spec=Commitment)
        commitment.id = 1
        commitment.deal_id = 100
        commitment.manager_id = 5
        commitment.commitment_text = "Test commitment"
        commitment.deadline = datetime(2025, 1, 15, 18, 0)
        commitment.category = "document"
        commitment.priority = "high"
        commitment.is_fulfilled = False
        commitment.is_overdue = True

        result = tracker._commitment_to_dict(commitment)

        assert result['id'] == 1
        assert result['deal_id'] == 100
        assert result['manager_id'] == 5
        assert result['text'] == "Test commitment"
        assert result['category'] == "document"
        assert result['priority'] == "high"
        assert result['is_fulfilled'] is False
        assert result['is_overdue'] is True

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_extract_with_ai_json_with_code_blocks(self, mock_post, tracker):
        """Тест: извлечение JSON с markdown code blocks"""
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        # GPT иногда возвращает JSON в code blocks
        mock_response.json.return_value = {
            'choices': [{
                'message': {
                    'content': '''```json
[
    {
        "text": "Отправлю КП",
        "deadline": "сегодня"
    }
]
```'''
                }
            }]
        }
        mock_post.return_value = mock_response

        result = await tracker._extract_with_ai("test transcription")

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]['text'] == "Отправлю КП"

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_extract_with_ai_invalid_json(self, mock_post, tracker):
        """Тест: некорректный JSON от AI"""
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            'choices': [{
                'message': {
                    'content': 'не JSON'
                }
            }]
        }
        mock_post.return_value = mock_response

        result = await tracker._extract_with_ai("test transcription")

        assert result == []

    def test_commitment_patterns(self, tracker):
        """Тест: проверка паттернов обещаний"""
        patterns = tracker.COMMITMENT_PATTERNS

        assert len(patterns) > 0
        assert all(isinstance(p, str) for p in patterns)

    def test_commitment_categories(self, tracker):
        """Тест: проверка категорий обещаний"""
        categories = tracker.CATEGORIES

        assert 'document' in categories
        assert 'call' in categories
        assert 'meeting' in categories
        assert 'approval' in categories
        assert 'information' in categories

        # Каждая категория должна иметь список ключевых слов
        for category, keywords in categories.items():
            assert isinstance(keywords, list)
            assert len(keywords) > 0
