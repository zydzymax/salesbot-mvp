"""
Deal Analysis Service - Professional B2B Sales Analysis
Анализ сделки как от опытного руководителя продаж B2B
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
import structlog
from openai import AsyncOpenAI

from ..config import get_settings
from ..database.models import Call

logger = structlog.get_logger("salesbot.deal_analysis")


class DealAnalysisService:
    """Сервис профессионального анализа сделки"""

    def __init__(self):
        self.settings = get_settings()
        self.client = AsyncOpenAI(api_key=self.settings.openai_api_key)
        self.model = "gpt-4o-mini"

    async def analyze_deal(
        self,
        calls: List[Call],
        lead_name: str,
        manager_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        Провести комплексный анализ сделки на основе всех звонков

        Args:
            calls: Список звонков по сделке (отсортированы по дате)
            lead_name: Название сделки
            manager_name: Имя менеджера

        Returns:
            Словарь с анализом и рекомендациями
        """
        try:
            if not calls:
                return None

            # Подготовить данные о звонках
            calls_data = []
            for i, call in enumerate(reversed(calls), 1):  # От старых к новым
                if call.transcription_text:
                    call_info = {
                        "номер": i,
                        "дата": call.created_at.strftime("%d.%m.%Y %H:%M"),
                        "длительность": f"{call.duration_seconds} сек" if call.duration_seconds else "неизвестно",
                        "транскрипт": call.transcription_text,
                        "оценка": call.quality_score if call.quality_score else "не оценен"
                    }
                    calls_data.append(call_info)

            if not calls_data:
                return None

            # Системный промпт - опытный руководитель продаж B2B
            system_prompt = """Ты — опытный руководитель отдела продаж B2B с 20-летним стажем.
Ты работал в различных отраслях: производство, IT, консалтинг, промышленное оборудование.
Ты знаешь все современные техники продаж: SPIN, Challenger Sale, Solution Selling, MEDDIC.
Ты понимаешь специфику B2B: длинный цикл сделки, множество лиц принимающих решение, сложные переговоры.

Твоя задача — проанализировать сделку на основе записей разговоров менеджера с клиентом и дать:
1. Объективную оценку текущего состояния сделки
2. Анализ действий менеджера (что делает правильно, что нужно улучшить)
3. Конкретные, практические рекомендации для закрытия сделки
4. Предупреждения о рисках срыва сделки

Анализируй как настоящий руководитель: профессионально, конструктивно, с фокусом на результат.
Твои рекомендации должны быть конкретными и применимыми на практике."""

            # Пользовательский промпт
            user_prompt = f"""Проанализируй сделку "{lead_name}" менеджера {manager_name}.

Всего звонков: {len(calls_data)}

Хронология разговоров (от первого к последнему):
"""

            for call_data in calls_data:
                user_prompt += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ЗВОНОК #{call_data['номер']} | {call_data['дата']} | {call_data['длительность']}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{call_data['транскрипт']}
"""

            user_prompt += """

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Дай мне ПРОФЕССИОНАЛЬНЫЙ АНАЛИЗ в формате JSON:

{
  "deal_status": "название статуса (новая/в работе/горячая/холодная/риск срыва/готова к закрытию)",
  "deal_health_score": 0-100,
  "overall_summary": "Краткая оценка ситуации по сделке (2-3 предложения)",

  "manager_performance": {
    "strengths": ["что менеджер делает хорошо - конкретно", "..."],
    "weaknesses": ["что нужно улучшить - конкретно", "..."],
    "skill_level": "junior/middle/senior",
    "grade": "A/B/C/D/F"
  },

  "deal_dynamics": {
    "trend": "улучшается/стабильно/ухудшается",
    "progress_indicators": ["конкретные признаки прогресса или регресса", "..."],
    "key_moments": ["важные моменты в истории сделки", "..."]
  },

  "client_analysis": {
    "interest_level": "высокий/средний/низкий",
    "decision_stage": "знакомство/изучение/оценка/принятие решения",
    "objections": ["главные возражения клиента", "..."],
    "buying_signals": ["сигналы готовности к покупке", "..."],
    "red_flags": ["тревожные сигналы", "..."]
  },

  "next_steps_recommendations": {
    "immediate_actions": [
      {
        "action": "конкретное действие",
        "why": "почему это важно",
        "how": "как это сделать",
        "deadline": "когда"
      }
    ],
    "conversation_script": "Рекомендуемый сценарий следующего звонка (2-3 абзаца)",
    "key_questions_to_ask": ["вопросы для следующего звонка", "..."],
    "objection_handling": "Как работать с главными возражениями клиента"
  },

  "risks": {
    "risk_level": "высокий/средний/низкий",
    "main_risks": ["ключевые риски срыва сделки", "..."],
    "mitigation_plan": ["что сделать для снижения рисков", "..."]
  },

  "strategic_recommendations": [
    "Стратегические рекомендации для закрытия сделки",
    "Конкретные советы по работе с этим клиентом",
    "..."
  ],

  "coaching_notes": "Персональные рекомендации менеджеру для роста (как от коуча)"
}

ВАЖНО:
- Анализируй как руководитель отдела продаж, а не как консультант
- Будь конкретен: вместо "улучшить презентацию" → "на следующем звонке начать с конкретных цифр ROI"
- Фокусируйся на результате: что сделать, чтобы ЗАКРЫТЬ сделку
- Учитывай специфику B2B: длинный цикл, несколько ЛПР, сложные переговоры
- Если видишь риски — говори прямо, но конструктивно"""

            logger.info(
                "Requesting deal analysis",
                deal_name=lead_name,
                calls_count=len(calls_data)
            )

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                response_format={"type": "json_object"}
            )

            import json
            result = json.loads(response.choices[0].message.content)

            result["tokens_used"] = response.usage.total_tokens
            result["analyzed_at"] = datetime.utcnow().isoformat()
            result["calls_analyzed"] = len(calls_data)

            logger.info(
                "Deal analysis completed",
                deal_name=lead_name,
                health_score=result.get("deal_health_score", 0),
                tokens_used=result["tokens_used"]
            )

            return result

        except Exception as e:
            logger.error(f"Deal analysis failed", error=str(e), deal_name=lead_name)
            return None


# Global service instance
deal_analysis_service = DealAnalysisService()
