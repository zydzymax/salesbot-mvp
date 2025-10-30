"""
Тесты для Call Quality Scorer
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

from app.analysis.call_quality_scorer import CallQualityScorer


@pytest.fixture
def scorer():
    """Фикстура для создания экземпляра CallQualityScorer"""
    return CallQualityScorer()


@pytest.fixture
def sample_transcription():
    """Пример транскрипции звонка"""
    return """
    Менеджер: Добрый день! Меня зовут Иван из компании "Продажи+".
    Клиент: Здравствуйте.
    Менеджер: Скажите, с какими задачами вы сейчас работаете в вашем отделе продаж?
    Клиент: У нас проблема с учетом звонков.
    Менеджер: Понимаю. То есть вам нужна система для автоматизации?
    Клиент: Да, верно.
    Менеджер: Отлично. Наша система как раз решает эту задачу. Она автоматически записывает все звонки.
    Клиент: А сколько стоит?
    Менеджер: Хороший вопрос. Давайте я подготовлю для вас коммерческое предложение с точными цифрами и отправлю сегодня до 18:00. Вас устроит?
    Клиент: Да, хорошо.
    Менеджер: Отлично. Значит, жду от вас обратную связь. Договорились созвониться завтра в 14:00?
    Клиент: Договорились.
    Менеджер: Спасибо за уделенное время, до связи!
    """


@pytest.fixture
def mock_gpt_response():
    """Мок ответа GPT API"""
    def _mock_response(score=75):
        return {
            'choices': [{
                'message': {
                    'content': str(score)
                }
            }]
        }
    return _mock_response


class TestCallQualityScorer:
    """Тесты для оценки качества звонков"""

    @pytest.mark.asyncio
    async def test_score_call_short_transcription(self, scorer):
        """Тест: слишком короткая транскрипция"""
        result = await scorer.score_call("короткий текст", "cold_call", 10)

        assert result['total_score'] == 0
        assert result['grade'] == 'N/A'
        assert 'error' in result
        assert 'короткая' in result['error'].lower()

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_score_call_success(self, mock_post, scorer, sample_transcription):
        """Тест: успешная оценка звонка"""
        # Мокаем ответы GPT для разных критериев
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            'choices': [{
                'message': {'content': '75'}
            }]
        }
        mock_post.return_value = mock_response

        result = await scorer.score_call(sample_transcription, "cold_call", 300)

        assert 'total_score' in result
        assert result['total_score'] >= 0
        assert result['total_score'] <= 100
        assert 'grade' in result
        assert result['grade'] in ['A', 'B', 'C', 'D', 'F']
        assert 'breakdown' in result
        assert 'strengths' in result
        assert 'weaknesses' in result
        assert 'recommendations' in result

    def test_get_grade(self, scorer):
        """Тест: преобразование оценки в буквенную"""
        assert scorer._get_grade(95) == 'A'
        assert scorer._get_grade(85) == 'B'
        assert scorer._get_grade(75) == 'C'
        assert scorer._get_grade(65) == 'D'
        assert scorer._get_grade(50) == 'F'

    def test_identify_strong_points(self, scorer):
        """Тест: определение сильных сторон"""
        results = {
            'greeting': {
                'score': 90,
                'weight': 5,
                'weighted_score': 4.5,
                'description': 'Приветствие'
            },
            'need_identification': {
                'score': 85,
                'weight': 15,
                'weighted_score': 12.75,
                'description': 'Выявление потребностей'
            },
            'tone_professionalism': {
                'score': 70,
                'weight': 10,
                'weighted_score': 7.0,
                'description': 'Профессионализм'
            }
        }

        strengths = scorer._identify_strong_points(results)

        assert len(strengths) <= 3
        assert all(s['score'] >= 80 for s in strengths)
        # Должны быть отсортированы по убыванию оценки
        if len(strengths) > 1:
            assert strengths[0]['score'] >= strengths[1]['score']

    def test_identify_weak_points(self, scorer):
        """Тест: определение слабых сторон"""
        results = {
            'greeting': {
                'score': 90,
                'weight': 5,
                'weighted_score': 4.5,
                'description': 'Приветствие'
            },
            'need_identification': {
                'score': 65,
                'weight': 15,
                'weighted_score': 9.75,
                'description': 'Выявление потребностей'
            },
            'tone_professionalism': {
                'score': 50,
                'weight': 10,
                'weighted_score': 5.0,
                'description': 'Профессионализм'
            }
        }

        weaknesses = scorer._identify_weak_points(results)

        assert len(weaknesses) <= 3
        assert all(60 < w['score'] < 80 for w in weaknesses)

    def test_identify_critical_issues(self, scorer):
        """Тест: определение критических проблем"""
        results = {
            'greeting': {
                'score': 90,
                'weight': 5,
                'weighted_score': 4.5,
                'description': 'Приветствие'
            },
            'need_identification': {
                'score': 55,
                'weight': 15,
                'weighted_score': 8.25,
                'description': 'Выявление потребностей'
            },
            'tone_professionalism': {
                'score': 40,
                'weight': 10,
                'weighted_score': 4.0,
                'description': 'Профессионализм'
            }
        }

        critical = scorer._identify_critical_issues(results)

        assert len(critical) == 2
        assert all(c['score'] <= 60 for c in critical)

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_generate_recommendations(self, mock_post, scorer):
        """Тест: генерация рекомендаций"""
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            'choices': [{
                'message': {
                    'content': """
                    • Задавайте больше открытых вопросов
                    • Используйте активное слушание
                    • Фокусируйтесь на выгодах для клиента
                    """
                }
            }]
        }
        mock_post.return_value = mock_response

        results = {}
        weaknesses = [
            {'description': 'Выявление потребностей', 'score': 65}
        ]
        critical = [
            {'description': 'Работа с возражениями', 'score': 50}
        ]

        recommendations = await scorer._generate_recommendations(
            results, weaknesses, critical, "cold_call"
        )

        assert isinstance(recommendations, list)
        assert len(recommendations) > 0
        assert len(recommendations) <= 4

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_evaluate_criterion(self, mock_post, scorer, sample_transcription):
        """Тест: оценка одного критерия"""
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            'choices': [{
                'message': {'content': '82'}
            }]
        }
        mock_post.return_value = mock_response

        score = await scorer._evaluate_criterion(
            sample_transcription,
            "greeting",
            "Поздоровался, представился, назвал компанию",
            "cold_call"
        )

        assert isinstance(score, (int, float))
        assert 0 <= score <= 100

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_evaluate_criterion_invalid_response(self, mock_post, scorer):
        """Тест: некорректный ответ от GPT"""
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            'choices': [{
                'message': {'content': 'не число'}
            }]
        }
        mock_post.return_value = mock_response

        score = await scorer._evaluate_criterion(
            "test transcription",
            "greeting",
            "criteria",
            "cold_call"
        )

        # Должен вернуть дефолтное значение
        assert score == 50

    def test_get_default_score(self, scorer):
        """Тест: дефолтная оценка при ошибке"""
        result = scorer._get_default_score("Test error")

        assert result['total_score'] == 0
        assert result['grade'] == 'N/A'
        assert result['error'] == "Test error"
        assert 'evaluated_at' in result

    @pytest.mark.asyncio
    async def test_quality_checklist_coverage(self, scorer):
        """Тест: проверка полноты чек-листа критериев"""
        checklist = scorer.QUALITY_CHECKLIST

        # Проверяем наличие важных критериев
        assert 'greeting' in checklist
        assert 'need_identification' in checklist
        assert 'value_proposition' in checklist
        assert 'next_step' in checklist

        # Проверяем структуру каждого критерия
        for criterion, config in checklist.items():
            assert 'weight' in config
            assert 'criteria' in config
            assert 'description' in config
            assert isinstance(config['weight'], (int, float))
            assert config['weight'] > 0

    @pytest.mark.asyncio
    async def test_score_call_empty_transcription(self, scorer):
        """Тест: пустая транскрипция"""
        result = await scorer.score_call("", "cold_call", 0)

        assert result['total_score'] == 0
        assert 'error' in result
