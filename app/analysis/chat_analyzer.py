"""
Chat/Message Analyzer
Анализ переписки с клиентами (WhatsApp, Telegram, SMS, email)
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import json
import httpx
import structlog

from ..config import get_settings
from ..utils.api_budget import api_budget, BudgetExceededError
from ..utils.runtime_settings import runtime_settings

logger = structlog.get_logger("salesbot.analysis.chat_analyzer")


# Типы сообщений в AmoCRM
MESSAGE_TYPES = {
    "sms_in": "SMS входящее",
    "sms_out": "SMS исходящее",
    "message_cashier": "Сообщение из виджета",
    "amomail_message": "Email",
    "wechat": "WeChat",
    "whatsapp": "WhatsApp",
    "viber": "Viber",
    "telegram": "Telegram",
    "instagram": "Instagram",
    "facebook": "Facebook Messenger",
    "vk": "ВКонтакте"
}


class ChatAnalyzer:
    """Анализатор переписки с клиентами"""

    def __init__(self):
        self.settings = get_settings()

    async def analyze_conversation(
        self,
        messages: List[Dict[str, Any]],
        deal_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Анализировать переписку с клиентом

        Args:
            messages: Список сообщений [{text, direction, timestamp, channel}, ...]
            deal_context: Контекст сделки (сумма, этап, продукт)

        Returns:
            Результат анализа с оценками и рекомендациями
        """
        if not messages:
            return self._empty_result("Нет сообщений для анализа")

        # Проверка бюджета
        allowed, reason = api_budget.can_make_request(0.05)
        if not allowed:
            logger.warning(f"Budget exceeded for chat analysis: {reason}")
            return self._empty_result(f"Бюджет исчерпан: {reason}")

        try:
            # Форматировать переписку
            conversation_text = self._format_conversation(messages)

            # Базовая статистика
            stats = self._calculate_stats(messages)

            # AI анализ
            analysis = await self._analyze_with_gpt(conversation_text, deal_context, stats)

            return {
                "success": True,
                "stats": stats,
                "analysis": analysis,
                "message_count": len(messages),
                "analyzed_at": datetime.utcnow().isoformat()
            }

        except BudgetExceededError as e:
            return self._empty_result(f"Бюджет исчерпан: {str(e)}")
        except Exception as e:
            logger.error(f"Chat analysis failed: {e}")
            return self._empty_result(f"Ошибка анализа: {str(e)}")

    def _format_conversation(self, messages: List[Dict]) -> str:
        """Форматировать переписку для анализа"""
        lines = []

        for msg in messages:
            direction = "Менеджер" if msg.get("direction") == "out" else "Клиент"
            timestamp = msg.get("timestamp", "")
            if isinstance(timestamp, (int, float)):
                timestamp = datetime.fromtimestamp(timestamp).strftime("%d.%m %H:%M")

            channel = msg.get("channel", "")
            channel_name = MESSAGE_TYPES.get(channel, channel)

            text = msg.get("text", "").strip()
            if not text:
                continue

            if channel_name:
                lines.append(f"[{timestamp}] [{channel_name}] {direction}: {text}")
            else:
                lines.append(f"[{timestamp}] {direction}: {text}")

        return "\n".join(lines)

    def _calculate_stats(self, messages: List[Dict]) -> Dict[str, Any]:
        """Вычислить базовую статистику переписки"""
        if not messages:
            return {}

        outgoing = [m for m in messages if m.get("direction") == "out"]
        incoming = [m for m in messages if m.get("direction") == "in"]

        # Время ответа
        response_times = []
        sorted_msgs = sorted(messages, key=lambda x: x.get("timestamp", 0))

        for i in range(1, len(sorted_msgs)):
            prev = sorted_msgs[i - 1]
            curr = sorted_msgs[i]

            # Если клиент написал, а потом менеджер ответил
            if prev.get("direction") == "in" and curr.get("direction") == "out":
                prev_time = prev.get("timestamp", 0)
                curr_time = curr.get("timestamp", 0)
                if prev_time and curr_time:
                    response_time = curr_time - prev_time
                    if 0 < response_time < 86400:  # Менее суток
                        response_times.append(response_time)

        avg_response_time = sum(response_times) / len(response_times) if response_times else None

        # Каналы
        channels = {}
        for msg in messages:
            ch = msg.get("channel", "unknown")
            channels[ch] = channels.get(ch, 0) + 1

        # Длина сообщений
        manager_msg_lengths = [len(m.get("text", "")) for m in outgoing if m.get("text")]
        client_msg_lengths = [len(m.get("text", "")) for m in incoming if m.get("text")]

        return {
            "total_messages": len(messages),
            "outgoing_count": len(outgoing),
            "incoming_count": len(incoming),
            "response_ratio": len(outgoing) / len(incoming) if incoming else 0,
            "avg_response_time_seconds": avg_response_time,
            "avg_response_time_minutes": round(avg_response_time / 60, 1) if avg_response_time else None,
            "channels": channels,
            "avg_manager_message_length": round(sum(manager_msg_lengths) / len(manager_msg_lengths)) if manager_msg_lengths else 0,
            "avg_client_message_length": round(sum(client_msg_lengths) / len(client_msg_lengths)) if client_msg_lengths else 0,
            "first_message_time": datetime.fromtimestamp(messages[0].get("timestamp", 0)).isoformat() if messages else None,
            "last_message_time": datetime.fromtimestamp(messages[-1].get("timestamp", 0)).isoformat() if messages else None
        }

    async def _analyze_with_gpt(
        self,
        conversation: str,
        deal_context: Optional[Dict],
        stats: Dict
    ) -> Dict[str, Any]:
        """Анализ переписки с помощью GPT"""

        model = await runtime_settings.get_model()

        context_info = ""
        if deal_context:
            context_info = f"""
Контекст сделки:
- Сумма: {deal_context.get('budget', 'не указана')}
- Этап: {deal_context.get('stage', 'не указан')}
- Продукт: {deal_context.get('product', 'не указан')}
"""

        stats_info = f"""
Статистика переписки:
- Всего сообщений: {stats.get('total_messages', 0)}
- От менеджера: {stats.get('outgoing_count', 0)}
- От клиента: {stats.get('incoming_count', 0)}
- Среднее время ответа: {stats.get('avg_response_time_minutes', 'н/д')} мин
"""

        prompt = f"""
Проанализируй переписку менеджера с клиентом.

{context_info}
{stats_info}

ПЕРЕПИСКА:
{conversation[:4000]}

Оцени по критериям (0-100):
1. Скорость ответов - насколько быстро менеджер отвечает
2. Качество коммуникации - вежливость, грамотность, профессионализм
3. Выявление потребностей - задаёт ли вопросы, слушает ли клиента
4. Работа с возражениями - как обрабатывает сомнения клиента
5. Продвижение к сделке - двигает ли клиента к покупке/встрече
6. Общая эффективность - итоговая оценка переписки

Верни JSON:
{{
    "scores": {{
        "response_speed": число,
        "communication_quality": число,
        "needs_identification": число,
        "objection_handling": число,
        "deal_progress": число,
        "overall": число
    }},
    "client_sentiment": "positive/neutral/negative/interested/hesitant",
    "client_readiness": "hot/warm/cold",
    "key_topics": ["тема1", "тема2"],
    "objections_found": ["возражение1", "возражение2"],
    "missed_opportunities": ["упущение1", "упущение2"],
    "strengths": ["сильная сторона1", "сильная сторона2"],
    "weaknesses": ["слабая сторона1", "слабая сторона2"],
    "recommendations": ["рекомендация1", "рекомендация2", "рекомендация3"],
    "next_best_action": "конкретное следующее действие",
    "summary": "краткое резюме переписки в 1-2 предложениях"
}}
"""

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
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
                                "content": "Ты эксперт по анализу продаж. Анализируешь переписку менеджеров с клиентами. Отвечай только JSON."
                            },
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.3,
                        "max_tokens": 1000,
                        "response_format": {"type": "json_object"}
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
                        request_type="chat_analysis"
                    )

                content = result["choices"][0]["message"]["content"]
                return json.loads(content)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse GPT response: {e}")
            return {"error": "Ошибка парсинга ответа"}
        except Exception as e:
            logger.error(f"GPT request failed: {e}")
            return {"error": str(e)}

    async def analyze_deal_messages(
        self,
        lead_id: str,
        include_calls: bool = False
    ) -> Dict[str, Any]:
        """
        Анализировать все сообщения по сделке из AmoCRM

        Args:
            lead_id: ID сделки в AmoCRM
            include_calls: Включать ли звонки в анализ
        """
        from ..amocrm.client import amocrm_client

        try:
            # Получить все заметки по сделке
            note_types = [
                "sms_in", "sms_out",
                "message_cashier",
                "amomail_message"
            ]

            if include_calls:
                note_types.extend(["call_in", "call_out"])

            notes = await amocrm_client.get_lead_notes(
                lead_id=lead_id,
                note_types=note_types,
                limit=250
            )

            if not notes:
                return self._empty_result("Нет сообщений по этой сделке")

            # Преобразовать в формат для анализа
            messages = []
            for note in notes:
                note_type = note.get("note_type", "")
                params = note.get("params", {})

                direction = "out" if note_type.endswith("_out") else "in"

                text = params.get("text", "") or params.get("uniq", "")
                if not text:
                    continue

                messages.append({
                    "text": text,
                    "direction": direction,
                    "timestamp": note.get("created_at", 0),
                    "channel": note_type
                })

            # Сортировать по времени
            messages.sort(key=lambda x: x.get("timestamp", 0))

            # Получить контекст сделки
            lead = await amocrm_client.get_lead(lead_id)
            deal_context = None
            if lead:
                deal_context = {
                    "budget": lead.get("price"),
                    "stage": lead.get("status_id"),
                    "product": lead.get("name")
                }

            # Анализировать
            return await self.analyze_conversation(messages, deal_context)

        except Exception as e:
            logger.error(f"Failed to analyze deal messages: {e}")
            return self._empty_result(f"Ошибка: {str(e)}")

    def _empty_result(self, error: str = None) -> Dict[str, Any]:
        """Пустой результат при ошибке"""
        return {
            "success": False,
            "error": error,
            "stats": {},
            "analysis": {},
            "message_count": 0,
            "analyzed_at": datetime.utcnow().isoformat()
        }


# Global instance
chat_analyzer = ChatAnalyzer()
