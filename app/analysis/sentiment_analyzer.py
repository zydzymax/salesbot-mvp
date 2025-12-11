"""
Extended Sentiment Analyzer
Анализ эмоциональной динамики разговора с трекингом изменений настроения
"""

from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
import json
import re
import httpx
import structlog

from ..config import get_settings
from ..utils.api_budget import api_budget, BudgetExceededError
from ..utils.runtime_settings import runtime_settings

logger = structlog.get_logger("salesbot.analysis.sentiment_analyzer")


class EmotionType(str, Enum):
    """Типы эмоций"""
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    INTERESTED = "interested"
    HESITANT = "hesitant"
    FRUSTRATED = "frustrated"
    EXCITED = "excited"
    CONFUSED = "confused"
    TRUSTING = "trusting"
    SKEPTICAL = "skeptical"


class SentimentTrend(str, Enum):
    """Тренд изменения настроения"""
    IMPROVING = "improving"      # Улучшается
    DECLINING = "declining"      # Ухудшается
    STABLE = "stable"            # Стабильно
    VOLATILE = "volatile"        # Нестабильно (колебания)


@dataclass
class EmotionPoint:
    """Точка эмоции на таймлайне"""
    segment_index: int           # Номер сегмента разговора
    timestamp_approx: str        # Примерное время (начало/середина/конец)
    speaker: str                 # Кто говорит (manager/client)
    emotion: EmotionType         # Основная эмоция
    intensity: float             # Интенсивность 0-1
    trigger: str                 # Что вызвало эмоцию
    quote: str                   # Цитата


@dataclass
class EmotionShift:
    """Значимое изменение эмоции"""
    from_emotion: EmotionType
    to_emotion: EmotionType
    trigger: str                 # Что вызвало изменение
    impact: str                  # positive/negative/neutral
    segment_index: int
    recommendation: str          # Что можно было сделать лучше


@dataclass
class SentimentDynamicsResult:
    """Результат анализа эмоциональной динамики"""
    # Общие метрики
    overall_client_sentiment: EmotionType
    overall_manager_sentiment: EmotionType
    sentiment_trend: SentimentTrend
    emotional_rapport: float     # Насколько менеджер "в контакте" с клиентом (0-100)

    # Динамика
    client_emotion_timeline: List[Dict]   # Список EmotionPoint в виде dict
    manager_emotion_timeline: List[Dict]
    emotion_shifts: List[Dict]   # Значимые изменения эмоций

    # Ключевые моменты
    positive_peaks: List[Dict]   # Моменты позитива
    negative_peaks: List[Dict]   # Моменты негатива
    turning_points: List[Dict]   # Поворотные точки разговора

    # Рекомендации
    emotional_wins: List[str]    # Что менеджер сделал хорошо эмоционально
    emotional_misses: List[str]  # Упущенные эмоциональные возможности
    recommendations: List[str]   # Рекомендации по эмоциональному интеллекту

    # Мета
    analyzed_at: str
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        # Convert enums to strings
        result["overall_client_sentiment"] = self.overall_client_sentiment.value
        result["overall_manager_sentiment"] = self.overall_manager_sentiment.value
        result["sentiment_trend"] = self.sentiment_trend.value
        return result


class SentimentDynamicsAnalyzer:
    """Анализатор эмоциональной динамики разговоров"""

    def __init__(self):
        self.settings = get_settings()

    async def analyze_sentiment_dynamics(
        self,
        transcription: str,
        call_duration_seconds: Optional[int] = None
    ) -> Optional[SentimentDynamicsResult]:
        """
        Анализировать эмоциональную динамику разговора

        Args:
            transcription: Полная транскрипция разговора
            call_duration_seconds: Длительность звонка (для временных меток)

        Returns:
            Детальный анализ эмоциональной динамики
        """
        if not transcription or len(transcription.strip()) < 50:
            logger.warning("Transcription too short for sentiment analysis")
            return None

        # Проверка бюджета
        allowed, reason = api_budget.can_make_request(0.08)
        if not allowed:
            logger.warning(f"Budget exceeded for sentiment analysis: {reason}")
            return None

        try:
            # Разбить на сегменты для анализа динамики
            segments = self._split_into_segments(transcription)

            # Получить модель
            model = await runtime_settings.get_model()

            # Анализ через GPT
            analysis = await self._analyze_with_gpt(
                transcription=transcription,
                segments=segments,
                model=model
            )

            if not analysis:
                return None

            return self._parse_result(analysis)

        except BudgetExceededError as e:
            logger.warning(f"Budget exceeded: {e}")
            return None
        except Exception as e:
            logger.error(f"Sentiment dynamics analysis failed: {e}")
            return None

    def _split_into_segments(self, transcription: str, max_segments: int = 10) -> List[str]:
        """Разбить транскрипцию на сегменты для анализа динамики"""
        # Разбиваем по репликам (обычно отделены переносом строки или маркерами)
        lines = transcription.split('\n')
        lines = [l.strip() for l in lines if l.strip()]

        if len(lines) <= max_segments:
            return lines

        # Группируем реплики в сегменты
        segment_size = max(1, len(lines) // max_segments)
        segments = []

        for i in range(0, len(lines), segment_size):
            segment = '\n'.join(lines[i:i + segment_size])
            segments.append(segment)

        return segments[:max_segments]

    async def _analyze_with_gpt(
        self,
        transcription: str,
        segments: List[str],
        model: str
    ) -> Optional[Dict]:
        """Анализ эмоциональной динамики через GPT"""

        segments_text = ""
        for i, seg in enumerate(segments):
            segments_text += f"\n--- СЕГМЕНТ {i+1} ---\n{seg}\n"

        prompt = f"""Проанализируй эмоциональную динамику этого разговора между менеджером и клиентом.

ТРАНСКРИПЦИЯ РАЗБИТА НА СЕГМЕНТЫ:
{segments_text}

Проанализируй и верни JSON:
{{
    "overall_client_sentiment": "positive|negative|neutral|interested|hesitant|frustrated|excited|confused|trusting|skeptical",
    "overall_manager_sentiment": "positive|negative|neutral|interested|hesitant|frustrated|excited|confused|trusting|skeptical",
    "sentiment_trend": "improving|declining|stable|volatile",
    "emotional_rapport": число от 0 до 100 (насколько менеджер "в контакте" с эмоциями клиента),

    "client_emotion_timeline": [
        {{
            "segment_index": номер_сегмента,
            "timestamp_approx": "начало|середина|конец",
            "speaker": "client",
            "emotion": "тип_эмоции",
            "intensity": число от 0 до 1,
            "trigger": "что вызвало эмоцию",
            "quote": "короткая цитата"
        }}
    ],

    "manager_emotion_timeline": [
        {{
            "segment_index": номер_сегмента,
            "timestamp_approx": "начало|середина|конец",
            "speaker": "manager",
            "emotion": "тип_эмоции",
            "intensity": число от 0 до 1,
            "trigger": "что вызвало эмоцию",
            "quote": "короткая цитата"
        }}
    ],

    "emotion_shifts": [
        {{
            "from_emotion": "предыдущая_эмоция",
            "to_emotion": "новая_эмоция",
            "trigger": "что вызвало изменение",
            "impact": "positive|negative|neutral",
            "segment_index": номер_сегмента,
            "recommendation": "что можно было сделать лучше"
        }}
    ],

    "positive_peaks": [
        {{
            "segment_index": номер,
            "description": "описание позитивного момента",
            "quote": "цитата"
        }}
    ],

    "negative_peaks": [
        {{
            "segment_index": номер,
            "description": "описание негативного момента",
            "quote": "цитата"
        }}
    ],

    "turning_points": [
        {{
            "segment_index": номер,
            "description": "что изменилось в разговоре",
            "impact": "positive|negative"
        }}
    ],

    "emotional_wins": ["что менеджер сделал хорошо эмоционально"],
    "emotional_misses": ["упущенные эмоциональные возможности"],
    "recommendations": ["конкретные рекомендации по эмоциональному интеллекту"]
}}

Важно:
- Отслеживай как меняются эмоции по ходу разговора
- Обращай внимание на триггеры изменения настроения
- Оценивай, насколько менеджер реагирует на эмоции клиента
- Давай конкретные рекомендации по улучшению эмоционального контакта
"""

        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.settings.openai_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "Ты эксперт по эмоциональному интеллекту и анализу коммуникаций. Анализируешь эмоциональную динамику разговоров. Отвечай только JSON."
                            },
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.3,
                        "max_tokens": 2500,
                        "response_format": {"type": "json_object"}
                    }
                )

                response.raise_for_status()
                result = response.json()

                # Track usage
                usage = result.get("usage", {})
                if usage:
                    await api_budget.record_request(
                        model=model,
                        input_tokens=usage.get("prompt_tokens", 0),
                        output_tokens=usage.get("completion_tokens", 0),
                        request_type="sentiment_dynamics"
                    )

                content = result["choices"][0]["message"]["content"]
                return json.loads(content)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse GPT response: {e}")
            return None
        except Exception as e:
            logger.error(f"GPT request failed: {e}")
            return None

    def _parse_result(self, analysis: Dict) -> SentimentDynamicsResult:
        """Преобразовать ответ GPT в структурированный результат"""

        # Парсинг эмоций с fallback
        def parse_emotion(value: str) -> EmotionType:
            try:
                return EmotionType(value.lower())
            except ValueError:
                return EmotionType.NEUTRAL

        def parse_trend(value: str) -> SentimentTrend:
            try:
                return SentimentTrend(value.lower())
            except ValueError:
                return SentimentTrend.STABLE

        return SentimentDynamicsResult(
            overall_client_sentiment=parse_emotion(analysis.get("overall_client_sentiment", "neutral")),
            overall_manager_sentiment=parse_emotion(analysis.get("overall_manager_sentiment", "neutral")),
            sentiment_trend=parse_trend(analysis.get("sentiment_trend", "stable")),
            emotional_rapport=float(analysis.get("emotional_rapport", 50)),
            client_emotion_timeline=analysis.get("client_emotion_timeline", []),
            manager_emotion_timeline=analysis.get("manager_emotion_timeline", []),
            emotion_shifts=analysis.get("emotion_shifts", []),
            positive_peaks=analysis.get("positive_peaks", []),
            negative_peaks=analysis.get("negative_peaks", []),
            turning_points=analysis.get("turning_points", []),
            emotional_wins=analysis.get("emotional_wins", []),
            emotional_misses=analysis.get("emotional_misses", []),
            recommendations=analysis.get("recommendations", []),
            analyzed_at=datetime.utcnow().isoformat(),
            confidence=0.85
        )

    async def get_emotion_summary(
        self,
        transcription: str
    ) -> Dict[str, Any]:
        """
        Получить краткую сводку по эмоциям (легкая версия анализа)

        Returns:
            {
                "client_sentiment": "positive",
                "manager_sentiment": "neutral",
                "trend": "improving",
                "rapport_score": 75,
                "key_moment": "описание ключевого момента"
            }
        """
        if not transcription or len(transcription.strip()) < 30:
            return {
                "client_sentiment": "neutral",
                "manager_sentiment": "neutral",
                "trend": "stable",
                "rapport_score": 50,
                "key_moment": None
            }

        # Проверка бюджета (меньше, т.к. легкий запрос)
        allowed, reason = api_budget.can_make_request(0.02)
        if not allowed:
            return {
                "client_sentiment": "neutral",
                "manager_sentiment": "neutral",
                "trend": "stable",
                "rapport_score": 50,
                "key_moment": None,
                "error": reason
            }

        try:
            model = await runtime_settings.get_model()

            prompt = f"""Кратко проанализируй эмоции в разговоре.

РАЗГОВОР:
{transcription[:2000]}

Верни JSON:
{{
    "client_sentiment": "positive|negative|neutral|interested|hesitant",
    "manager_sentiment": "positive|negative|neutral|professional|enthusiastic",
    "trend": "improving|declining|stable",
    "rapport_score": число от 0 до 100,
    "key_moment": "краткое описание ключевого эмоционального момента или null"
}}
"""

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.settings.openai_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": "Анализируй эмоции в разговорах. Отвечай только JSON."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.2,
                        "max_tokens": 200,
                        "response_format": {"type": "json_object"}
                    }
                )

                response.raise_for_status()
                result = response.json()

                usage = result.get("usage", {})
                if usage:
                    await api_budget.record_request(
                        model=model,
                        input_tokens=usage.get("prompt_tokens", 0),
                        output_tokens=usage.get("completion_tokens", 0),
                        request_type="emotion_summary"
                    )

                content = result["choices"][0]["message"]["content"]
                return json.loads(content)

        except Exception as e:
            logger.error(f"Emotion summary failed: {e}")
            return {
                "client_sentiment": "neutral",
                "manager_sentiment": "neutral",
                "trend": "stable",
                "rapport_score": 50,
                "key_moment": None,
                "error": str(e)
            }


# Global instance
sentiment_dynamics_analyzer = SentimentDynamicsAnalyzer()
