"""
AI Sales Coach - Generates feedback and recommendations
Acts as experienced sales manager providing coaching
"""

from typing import Dict, Any, List
import json
import httpx
import structlog

from ..config import get_settings
from ..utils.api_budget import api_budget, BudgetExceededError

logger = structlog.get_logger("salesbot.analysis.ai_coach")


class AICoach:
    """AI Sales Coach for manager feedback"""
    
    def __init__(self):
        self.settings = get_settings()
    
    async def generate_coaching_feedback(
        self,
        deal_data: Dict[str, Any],
        communications: List[Dict[str, Any]],
        funnel_history: List[Dict[str, Any]],
        tasks: List[Dict[str, Any]],
        metrics: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Генерация обратной связи и рекомендаций от лица руководителя отдела продаж
        """
        
        logger.info("Generating AI coaching feedback", deal_id=deal_data.get("id"))
        
        try:
            # Подготовить контекст для анализа
            context = self._prepare_context(
                deal_data, communications, funnel_history, tasks, metrics
            )
            
            # Сгенерировать анализ через GPT
            prompt = self._build_sales_manager_prompt(context)
            
            response = await self._call_openai(prompt)
            
            # Парсить результат
            result = self._parse_coaching_response(response)
            
            logger.info("Coaching feedback generated", deal_id=deal_data.get("id"))
            return result
            
        except Exception as e:
            logger.error(f"Coaching feedback generation failed", error=str(e))
            return {
                "error": str(e),
                "summary": "Не удалось сгенерировать рекомендации",
                "recommendations": []
            }
    
    def _prepare_context(
        self,
        deal_data: Dict[str, Any],
        communications: List[Dict[str, Any]],
        funnel_history: List[Dict[str, Any]],
        tasks: List[Dict[str, Any]],
        metrics: Dict[str, Any]
    ) -> str:
        """Подготовить контекст для анализа"""
        
        # Суммаризировать коммуникации
        calls_summary = []
        notes_summary = []
        
        for comm in communications[:10]:  # Последние 10
            if comm["type"] == "call":
                duration = comm.get("call_details", {}).get("duration", 0)
                calls_summary.append(
                    f"- Звонок {duration}сек, {comm.get('call_details', {}).get('result', 'N/A')}"
                )
            else:
                notes_summary.append(f"- Примечание: {comm.get('note_type', 'N/A')}")
        
        # Суммаризировать движение по воронке
        funnel_summary = []
        for move in funnel_history[-5:]:  # Последние 5 движений
            funnel_summary.append(
                f"- Переход из статуса {move['from_status']} в {move['to_status']}"
            )
        
        context = f"""
СДЕЛКА: {deal_data.get('name', 'Без названия')}
Бюджет: {deal_data.get('price', 0)} руб.
Возраст сделки: {metrics.get('deal_age_days', 0)} дней
Дней без активности: {metrics.get('days_since_last_update', 0)}

МЕТРИКИ:
- Всего коммуникаций: {metrics.get('total_communications', 0)}
- Звонков: {metrics.get('total_calls', 0)}
- Общая длительность звонков: {metrics.get('total_call_duration_seconds', 0)}сек
- Среднее время между касаниями: {metrics.get('avg_time_between_contacts_days', 0)} дней
- Движений по воронке: {metrics.get('funnel_movements', 0)}
- Время в текущем статусе: {metrics.get('time_in_current_stage_days', 0)} дней

ЗАДАЧИ:
- Всего задач: {metrics.get('total_tasks', 0)}
- Выполнено: {metrics.get('completed_tasks', 0)}
- Просрочено: {metrics.get('overdue_tasks', 0)}
- Процент выполнения: {metrics.get('task_completion_rate', 0)}%

ПОСЛЕДНИЕ КОММУНИКАЦИИ:
{chr(10).join(calls_summary[:5]) if calls_summary else '- Нет звонков'}
{chr(10).join(notes_summary[:5]) if notes_summary else '- Нет примечаний'}

ДВИЖЕНИЕ ПО ВОРОНКЕ:
{chr(10).join(funnel_summary) if funnel_summary else '- Нет движений'}
"""
        
        return context.strip()
    
    def _build_sales_manager_prompt(self, context: str) -> str:
        """Построить промпт для анализа"""
        
        return f"""
Ты - опытный руководитель отдела продаж с 15-летним стажем. 
Твоя задача - проанализировать работу менеджера по конкретной сделке и дать конструктивную обратную связь с конкретными рекомендациями.

Проанализируй следующую информацию о сделке:

{context}

Дай обратную связь в формате JSON:

{{
  "assessment": "краткая оценка ситуации (2-3 предложения)",
  "strengths": ["что менеджер делает хорошо"],
  "concerns": ["что вызывает беспокойство"],
  "priority": "high/medium/low - приоритет внимания к этой сделке",
  "recommendations": [
    {{
      "action": "конкретное действие которое нужно сделать",
      "why": "почему это важно",
      "how": "как именно это сделать (конкретные фразы, подходы)",
      "urgency": "срочность: immediate/this_week/planned"
    }}
  ],
  "suggested_phrases": [
    "Примеры фраз которые можно использовать в разговоре с клиентом"
  ],
  "next_steps": ["конкретный план действий на ближайшие 2-3 дня"],
  "red_flags": ["критичные проблемы если есть"],
  "estimated_conversion_probability": "оценка вероятности закрытия в %"
}}

ВАЖНО:
- Будь конструктивным но честным
- Давай КОНКРЕТНЫЕ рекомендации с примерами фраз
- Учитывай контекст и специфику B2B продаж
- Фокусируйся на действиях которые повысят конверсию
- Если ситуация критичная - четко об этом скажи

Отвечай ТОЛЬКО в формате JSON, без дополнительного текста.
"""
    
    async def _call_openai(self, prompt: str) -> str:
        """Вызвать OpenAI API с бюджетной защитой"""

        # Budget check
        allowed, reason = api_budget.can_make_request(0.15)  # AI coach is complex
        if not allowed:
            raise BudgetExceededError(reason)

        api_key = self.settings.openai_api_key
        # Get model from runtime settings (can be changed via admin panel)
        from ..utils.runtime_settings import runtime_settings
        model = await runtime_settings.get_model()

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "Ты опытный руководитель отдела продаж. Анализируешь работу менеджеров и даешь конкретные рекомендации. Отвечай структурированно и кратко."
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    "temperature": 0.7,
                    "max_tokens": 1500
                }
            )

            response.raise_for_status()
            result = response.json()

            # Track cost
            usage = result.get("usage", {})
            if usage:
                await api_budget.record_request(
                    model=model,
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", 0),
                    request_type="ai_coaching"
                )

            return result["choices"][0]["message"]["content"]
    
    def _parse_coaching_response(self, response: str) -> Dict[str, Any]:
        """Парсить ответ от OpenAI"""
        
        try:
            # Попробовать парсить как JSON
            # Убрать markdown код если есть
            response = response.strip()
            if response.startswith("```json"):
                response = response[7:]
            if response.startswith("```"):
                response = response[3:]
            if response.endswith("```"):
                response = response[:-3]
            
            result = json.loads(response.strip())
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response as JSON", error=str(e))
            
            # Fallback - вернуть базовую структуру
            return {
                "assessment": "Не удалось проанализировать сделку",
                "strengths": [],
                "concerns": ["Ошибка анализа"],
                "priority": "medium",
                "recommendations": [
                    {
                        "action": "Проверить сделку вручную",
                        "why": "Автоматический анализ не удался",
                        "how": "Просмотрите историю коммуникаций",
                        "urgency": "this_week"
                    }
                ],
                "suggested_phrases": [],
                "next_steps": ["Связаться с клиентом"],
                "red_flags": [],
                "estimated_conversion_probability": "50"
            }


# Global instance
ai_coach = AICoach()
