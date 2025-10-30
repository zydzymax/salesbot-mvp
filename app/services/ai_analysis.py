"""
AI-powered call analysis service using OpenAI GPT
"""

from typing import Optional, Dict, Any
import json
import structlog
from openai import AsyncOpenAI

from ..config import get_settings

logger = structlog.get_logger("salesbot.ai_analysis")


class AIAnalysisService:
    """Service for analyzing call transcripts using GPT"""

    def __init__(self):
        self.settings = get_settings()
        self.client = AsyncOpenAI(api_key=self.settings.openai_api_key)
        self.model = "gpt-4o-mini"  # Cheap and fast

    async def analyze_call(
        self,
        transcript: str,
        phone: Optional[str] = None,
        duration: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Analyze call transcript and return quality assessment

        Args:
            transcript: Call transcription text
            phone: Client phone number
            duration: Call duration in seconds

        Returns:
            Dict with analysis results or None if failed
        """
        try:
            # Prepare context
            context_info = []
            if phone:
                context_info.append(f"Телефон клиента: {phone}")
            if duration:
                context_info.append(f"Длительность: {duration} сек")

            context = "\n".join(context_info) if context_info else ""

            # Professional sales quality analysis prompt
            system_prompt = """Ты эксперт по оценке качества телефонных продаж с 15-летним опытом.
Проанализируй транскрипт звонка менеджера с клиентом по критериям профессиональных продаж.

КРИТЕРИИ ОЦЕНКИ (каждый 0-10 баллов):
1. Установление контакта (приветствие, представление, получение разрешения)
2. Выявление потребностей (открытые вопросы, активное слушание)
3. Презентация (ценностное предложение, выгоды для клиента)
4. Работа с возражениями (техники, аргументация)
5. Завершение (договоренности, следующие шаги, благодарность)
6. Профессионализм (грамотность речи, уверенность, эмпатия)
7. Структура разговора (логика, управление диалогом)
8. Результативность (достигнута ли цель звонка)

Верни ТОЛЬКО валидный JSON:
{
  "quality_score": 0-100,
  "summary": "краткое резюме звонка (2-3 предложения)",
  "scores": {
    "contact_establishment": 0-10,
    "needs_identification": 0-10,
    "presentation": 0-10,
    "objection_handling": 0-10,
    "closing": 0-10,
    "professionalism": 0-10,
    "structure": 0-10,
    "effectiveness": 0-10
  },
  "strengths": ["конкретная сильная сторона 1", "конкретная сильная сторона 2"],
  "weaknesses": ["конкретная слабость 1", "конкретная слабость 2"],
  "recommendations": ["конкретная рекомендация 1", "конкретная рекомендация 2", "конкретная рекомендация 3"],
  "key_moments": {
    "greeting_done": true/false,
    "permission_asked": true/false,
    "needs_identified": true/false,
    "objections_appeared": true/false,
    "objections_handled": true/false,
    "next_step_agreed": true/false,
    "commitment_obtained": true/false
  },
  "call_outcome": "positive/neutral/negative",
  "manager_level": "junior/middle/senior"
}

Оценивай строго и объективно. Качество 80+ только для действительно отличных звонков."""

            user_prompt = f"""{context}

Транскрипт звонка:
{transcript}"""

            logger.info(
                "Requesting AI analysis",
                model=self.model,
                transcript_length=len(transcript)
            )

            # Call GPT API
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                response_format={"type": "json_object"}
            )

            # Parse response
            result_text = response.choices[0].message.content
            result = json.loads(result_text)

            # Add metadata
            result["tokens_used"] = response.usage.total_tokens
            result["model"] = self.model

            logger.info(
                "AI analysis completed",
                quality_score=result.get("quality_score", 0),
                tokens_used=result["tokens_used"]
            )

            return result

        except Exception as e:
            logger.error("AI analysis failed", error=str(e))
            return None


# Global service instance
ai_analysis_service = AIAnalysisService()
