"""
Тесты для Activity Validator (Fraud Detection)
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timedelta
from collections import namedtuple

from app.fraud.activity_validator import ActivityValidator


# Mock модель Call
MockCall = namedtuple('Call', [
    'id', 'manager_id', 'client_phone', 'duration',
    'created_at', 'transcription_text'
])


@pytest.fixture
def validator():
    """Фикстура для создания экземпляра ActivityValidator"""
    return ActivityValidator()


@pytest.fixture
def normal_calls():
    """Нормальная активность менеджера"""
    base_time = datetime.now() - timedelta(days=3)
    calls = []

    for i in range(20):
        calls.append(MockCall(
            id=i,
            manager_id=1,
            client_phone=f"+7900123456{i % 10}",  # Разные номера
            duration=120 + (i * 10),  # Разная длительность
            created_at=base_time + timedelta(hours=i),
            transcription_text=f"Нормальный разговор {i}" * 20
        ))

    return calls


@pytest.fixture
def suspicious_same_number_calls():
    """Подозрительная активность: много звонков на один номер"""
    base_time = datetime.now() - timedelta(days=3)
    calls = []

    for i in range(15):
        calls.append(MockCall(
            id=i,
            manager_id=1,
            client_phone="+79001234567",  # Один и тот же номер
            duration=120,
            created_at=base_time + timedelta(hours=i),
            transcription_text="Разговор"
        ))

    return calls


@pytest.fixture
def suspicious_short_calls():
    """Подозрительная активность: много коротких звонков"""
    base_time = datetime.now() - timedelta(days=3)
    calls = []

    for i in range(30):
        calls.append(MockCall(
            id=i,
            manager_id=1,
            client_phone=f"+7900123456{i}",
            duration=5,  # Очень короткие
            created_at=base_time + timedelta(hours=i),
            transcription_text="Короткий"
        ))

    return calls


class TestActivityValidator:
    """Тесты для детектора мертвых душ"""

    def test_check_same_number_repeatedly_normal(self, validator, normal_calls):
        """Тест: нормальная активность - разные номера"""
        result = validator._check_same_number_repeatedly(normal_calls)

        assert result is None

    def test_check_same_number_repeatedly_suspicious(
        self,
        validator,
        suspicious_same_number_calls
    ):
        """Тест: подозрительная активность - много звонков на один номер"""
        result = validator._check_same_number_repeatedly(suspicious_same_number_calls)

        assert result is not None
        assert result['type'] == 'same_number_repeatedly'
        assert result['severity'] == 'high'
        assert result['details']['call_count'] > validator.THRESHOLDS['same_number_max_calls']

    def test_check_same_number_repeatedly_no_phones(self, validator):
        """Тест: нет номеров телефонов"""
        calls = [
            MockCall(1, 1, None, 120, datetime.now(), "text")
        ]

        result = validator._check_same_number_repeatedly(calls)

        assert result is None

    def test_check_too_many_short_calls_normal(self, validator, normal_calls):
        """Тест: нормальная активность - нормальная длительность"""
        result = validator._check_too_many_short_calls(normal_calls)

        assert result is None

    def test_check_too_many_short_calls_suspicious(
        self,
        validator,
        suspicious_short_calls
    ):
        """Тест: подозрительная активность - много коротких звонков"""
        result = validator._check_too_many_short_calls(suspicious_short_calls)

        assert result is not None
        assert result['type'] == 'too_many_short_calls'
        assert result['severity'] == 'medium'
        assert result['details']['ratio'] > validator.THRESHOLDS['short_calls_ratio']

    def test_check_calls_outside_hours_normal(self, validator):
        """Тест: нормальная активность - звонки в рабочее время"""
        base_time = datetime.now().replace(hour=10, minute=0)  # 10:00
        calls = []

        for i in range(10):
            calls.append(MockCall(
                id=i,
                manager_id=1,
                client_phone=f"+7900123456{i}",
                duration=120,
                created_at=base_time + timedelta(hours=i),
                transcription_text="text"
            ))

        result = validator._check_calls_outside_hours(calls)

        assert result is None

    def test_check_calls_outside_hours_suspicious(self, validator):
        """Тест: подозрительная активность - звонки ночью"""
        night_time = datetime.now().replace(hour=2, minute=0)  # 2:00 ночи
        calls = []

        for i in range(10):
            calls.append(MockCall(
                id=i,
                manager_id=1,
                client_phone=f"+7900123456{i}",
                duration=120,
                created_at=night_time + timedelta(minutes=i * 10),
                transcription_text="text"
            ))

        result = validator._check_calls_outside_hours(calls)

        assert result is not None
        assert result['type'] == 'calls_outside_hours'
        assert result['severity'] == 'medium'
        assert result['details']['night_calls_count'] > validator.THRESHOLDS['night_calls_max']

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_validate_single_conversation_real(self, mock_post, validator):
        """Тест: проверка настоящего разговора"""
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            'choices': [{
                'message': {
                    'content': 'НАСТОЯЩИЙ'
                }
            }]
        }
        mock_post.return_value = mock_response

        transcription = """
        Менеджер: Добрый день! Меня зовут Иван.
        Клиент: Здравствуйте.
        Менеджер: Расскажите о вашей компании.
        Клиент: Мы занимаемся оптовыми продажами.
        """

        result = await validator._validate_single_conversation(transcription)

        assert result is True

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_validate_single_conversation_fake(self, mock_post, validator):
        """Тест: проверка фейкового разговора"""
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            'choices': [{
                'message': {
                    'content': 'ФЕЙКОВЫЙ'
                }
            }]
        }
        mock_post.return_value = mock_response

        transcription = "Привет привет как дела нормально окей окей"

        result = await validator._validate_single_conversation(transcription)

        assert result is False

    @pytest.mark.asyncio
    async def test_validate_single_conversation_no_api_key(self, validator):
        """Тест: нет API ключа"""
        validator.settings.openai_api_key = None

        result = await validator._validate_single_conversation("test")

        # Без ключа считаем разговор нормальным
        assert result is True

    def test_check_suspicious_time_pattern_normal(self, validator):
        """Тест: нормальное распределение времени звонков"""
        base_time = datetime.now().replace(hour=9, minute=0)
        calls = []

        # Звонки в разное время
        for i in range(30):
            calls.append(MockCall(
                id=i,
                manager_id=1,
                client_phone=f"+7900123456{i}",
                duration=120,
                created_at=base_time + timedelta(hours=i % 8),  # Разброс по часам
                transcription_text="text"
            ))

        result = validator._check_suspicious_time_pattern(calls)

        assert result is None

    def test_check_suspicious_time_pattern_suspicious(self, validator):
        """Тест: подозрительный паттерн - все звонки в один час"""
        base_time = datetime.now().replace(hour=14, minute=0)
        calls = []

        # Все звонки в 14:00
        for i in range(30):
            calls.append(MockCall(
                id=i,
                manager_id=1,
                client_phone=f"+7900123456{i}",
                duration=120,
                created_at=base_time + timedelta(minutes=i),  # Все в один час
                transcription_text="text"
            ))

        result = validator._check_suspicious_time_pattern(calls)

        assert result is not None
        assert result['type'] == 'suspicious_time_pattern'
        assert result['severity'] == 'low'

    def test_check_suspicious_time_pattern_too_few_calls(self, validator):
        """Тест: слишком мало звонков для анализа паттерна"""
        calls = [
            MockCall(1, 1, "+79001234567", 120, datetime.now(), "text")
        ]

        result = validator._check_suspicious_time_pattern(calls)

        assert result is None

    def test_check_activity_without_results_normal(self, validator):
        """Тест: нормальное соотношение звонков/клиентов"""
        # Будет протестировано в интеграционных тестах с БД

    def test_get_recommended_action(self, validator):
        """Тест: рекомендованные действия"""
        assert validator._get_recommended_action(0) == 'no_action'
        assert validator._get_recommended_action(1) == 'monitor'
        assert validator._get_recommended_action(2) == 'manual_review'
        assert validator._get_recommended_action(3) == 'manual_review'
        assert validator._get_recommended_action(4) == 'immediate_investigation'
        assert validator._get_recommended_action(5) == 'immediate_investigation'

    def test_thresholds_configuration(self, validator):
        """Тест: проверка конфигурации порогов"""
        thresholds = validator.THRESHOLDS

        assert 'same_number_max_calls' in thresholds
        assert 'short_calls_ratio' in thresholds
        assert 'night_calls_max' in thresholds
        assert 'min_conversion_rate' in thresholds
        assert 'suspicious_conversation_threshold' in thresholds

        # Все пороги должны быть числами
        for key, value in thresholds.items():
            assert isinstance(value, (int, float))

    @pytest.mark.asyncio
    async def test_check_conversation_validity_no_transcriptions(self, validator):
        """Тест: нет транскрипций для проверки"""
        calls = [
            MockCall(1, 1, "+79001234567", 120, datetime.now(), None),
            MockCall(2, 1, "+79001234568", 130, datetime.now(), "short"),
        ]

        result = await validator._check_conversation_validity(calls)

        assert result is None

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_check_conversation_validity_suspicious(self, mock_post, validator):
        """Тест: подозрительные разговоры"""
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        # Все разговоры фейковые
        mock_response.json.return_value = {
            'choices': [{
                'message': {
                    'content': 'ФЕЙКОВЫЙ'
                }
            }]
        }
        mock_post.return_value = mock_response

        calls = [
            MockCall(
                i,
                1,
                f"+7900123456{i}",
                120,
                datetime.now(),
                "Фейковый разговор " * 20
            )
            for i in range(10)
        ]

        result = await validator._check_conversation_validity(calls)

        assert result is not None
        assert result['type'] == 'suspicious_conversations'
        assert result['severity'] == 'high'

    def test_check_too_many_short_calls_empty_list(self, validator):
        """Тест: пустой список звонков"""
        result = validator._check_too_many_short_calls([])

        assert result is None

    def test_check_calls_outside_hours_edge_cases(self, validator):
        """Тест: граничные случаи для рабочих часов"""
        # 9:00 - начало рабочего дня (должно быть ок)
        calls_9am = [
            MockCall(
                1, 1, "+79001234567", 120,
                datetime.now().replace(hour=9, minute=0),
                "text"
            )
        ]
        assert validator._check_calls_outside_hours(calls_9am) is None

        # 8:59 - до начала (должно быть подозрительно при большом количестве)
        calls_before_work = [
            MockCall(
                i, 1, f"+7900123456{i}", 120,
                datetime.now().replace(hour=8, minute=59),
                "text"
            )
            for i in range(10)
        ]
        result = validator._check_calls_outside_hours(calls_before_work)
        assert result is not None

        # 20:00 - конец рабочего дня (должно быть ок)
        calls_8pm = [
            MockCall(
                1, 1, "+79001234567", 120,
                datetime.now().replace(hour=20, minute=0),
                "text"
            )
        ]
        assert validator._check_calls_outside_hours(calls_8pm) is None

        # 20:01 - после конца (должно быть подозрительно при большом количестве)
        calls_after_work = [
            MockCall(
                i, 1, f"+7900123456{i}", 120,
                datetime.now().replace(hour=20, minute=1),
                "text"
            )
            for i in range(10)
        ]
        result = validator._check_calls_outside_hours(calls_after_work)
        assert result is not None
