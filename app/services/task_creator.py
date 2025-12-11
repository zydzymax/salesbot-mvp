"""
AI Task Creator - Автоматическое создание задач в AmoCRM из рекомендаций AI
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import json
import httpx
import structlog

from ..config import get_settings
from ..amocrm.client import amocrm_client
from ..database.init_db import db_manager
from ..utils.api_budget import api_budget, BudgetExceededError
from ..utils.runtime_settings import runtime_settings

logger = structlog.get_logger("salesbot.services.task_creator")


class TaskUrgency(str, Enum):
    """Срочность задачи"""
    IMMEDIATE = "immediate"    # Сегодня
    SOON = "soon"              # 1-2 дня
    NORMAL = "normal"          # 3-5 дней
    LOW = "low"                # Неделя+


class TaskType(str, Enum):
    """Тип задачи"""
    CALL = "call"                  # Позвонить
    FOLLOW_UP = "follow_up"        # Перезвонить
    SEND_INFO = "send_info"        # Отправить информацию
    MEETING = "meeting"            # Назначить встречу
    OBJECTION = "objection"        # Отработать возражение
    PROPOSAL = "proposal"          # Подготовить КП
    CHECK_IN = "check_in"          # Проверить статус
    ESCALATE = "escalate"          # Эскалировать РОПу


@dataclass
class AITask:
    """Задача сгенерированная AI"""
    task_type: TaskType
    urgency: TaskUrgency
    title: str
    description: str
    deadline_days: int           # Дней до дедлайна
    reason: str                  # Почему нужно сделать
    source: str                  # Откуда рекомендация (call_analysis, deal_analysis, etc.)


@dataclass
class CreatedTask:
    """Созданная задача в AmoCRM"""
    amocrm_task_id: Optional[str]
    lead_id: str
    manager_id: int
    task: AITask
    created_at: datetime
    success: bool
    error: Optional[str] = None


class AITaskCreator:
    """Сервис создания задач в AmoCRM из рекомендаций AI"""

    # Маппинг типов задач на типы в AmoCRM
    AMOCRM_TASK_TYPES = {
        TaskType.CALL: 1,         # Звонок
        TaskType.FOLLOW_UP: 1,    # Звонок
        TaskType.SEND_INFO: 2,    # Встреча
        TaskType.MEETING: 2,      # Встреча
        TaskType.OBJECTION: 1,    # Звонок
        TaskType.PROPOSAL: 2,     # Встреча
        TaskType.CHECK_IN: 1,     # Звонок
        TaskType.ESCALATE: 1,     # Звонок
    }

    # Эмодзи для типов задач
    TASK_EMOJIS = {
        TaskType.CALL: "📞",
        TaskType.FOLLOW_UP: "🔄",
        TaskType.SEND_INFO: "📧",
        TaskType.MEETING: "🤝",
        TaskType.OBJECTION: "🛡️",
        TaskType.PROPOSAL: "📋",
        TaskType.CHECK_IN: "👀",
        TaskType.ESCALATE: "⚠️",
    }

    def __init__(self):
        self.settings = get_settings()

    async def create_tasks_from_analysis(
        self,
        lead_id: str,
        manager_id: int,
        analysis_result: Dict[str, Any],
        source: str = "call_analysis",
        auto_create: bool = True
    ) -> List[CreatedTask]:
        """
        Создать задачи из результата анализа

        Args:
            lead_id: ID сделки в AmoCRM
            manager_id: ID менеджера в БД
            analysis_result: Результат анализа (от AI)
            source: Источник рекомендаций
            auto_create: Автоматически создавать в AmoCRM

        Returns:
            Список созданных задач
        """
        # Извлечь рекомендации из анализа
        recommendations = self._extract_recommendations(analysis_result)

        if not recommendations:
            logger.info(f"No recommendations to create tasks from", lead_id=lead_id)
            return []

        # Преобразовать в задачи через AI
        tasks = await self._convert_to_tasks(recommendations, source)

        if not tasks:
            return []

        # Получить amocrm_user_id менеджера
        amocrm_user_id = await self._get_manager_amocrm_id(manager_id)
        if not amocrm_user_id:
            logger.warning(f"Manager {manager_id} has no AmoCRM user ID")
            return []

        # Создать задачи в AmoCRM
        created_tasks = []
        for task in tasks:
            if auto_create:
                result = await self._create_in_amocrm(
                    lead_id=lead_id,
                    manager_id=manager_id,
                    amocrm_user_id=amocrm_user_id,
                    task=task
                )
                created_tasks.append(result)
            else:
                # Только подготовить, не создавать
                created_tasks.append(CreatedTask(
                    amocrm_task_id=None,
                    lead_id=lead_id,
                    manager_id=manager_id,
                    task=task,
                    created_at=datetime.utcnow(),
                    success=False,
                    error="Auto-create disabled"
                ))

        return created_tasks

    def _extract_recommendations(self, analysis: Dict) -> List[str]:
        """Извлечь рекомендации из разных форматов анализа"""
        recommendations = []

        # Стандартные поля с рекомендациями
        if "recommendations" in analysis:
            recs = analysis["recommendations"]
            if isinstance(recs, list):
                recommendations.extend(recs)
            elif isinstance(recs, str):
                recommendations.append(recs)

        # Следующие шаги
        if "next_steps_recommendations" in analysis:
            next_steps = analysis["next_steps_recommendations"]
            if isinstance(next_steps, dict):
                if "immediate_actions" in next_steps:
                    for action in next_steps["immediate_actions"]:
                        if isinstance(action, dict):
                            recommendations.append(action.get("action", ""))
                        else:
                            recommendations.append(str(action))

        # Следующее действие
        if "next_best_action" in analysis:
            recommendations.append(analysis["next_best_action"])

        # Из анализа сделки
        if "strategic_recommendations" in analysis:
            recommendations.extend(analysis["strategic_recommendations"])

        # Фильтруем пустые
        return [r for r in recommendations if r and len(r.strip()) > 5]

    async def _convert_to_tasks(
        self,
        recommendations: List[str],
        source: str
    ) -> List[AITask]:
        """Преобразовать текстовые рекомендации в структурированные задачи"""

        # Проверка бюджета
        allowed, reason = api_budget.can_make_request(0.03)
        if not allowed:
            logger.warning(f"Budget exceeded for task conversion: {reason}")
            # Fallback: простое преобразование без AI
            return self._simple_convert(recommendations, source)

        try:
            model = await runtime_settings.get_model()

            prompt = f"""Преобразуй эти рекомендации в конкретные задачи для менеджера.

РЕКОМЕНДАЦИИ:
{chr(10).join(f'- {r}' for r in recommendations[:5])}

Верни JSON со списком задач:
{{
    "tasks": [
        {{
            "task_type": "call|follow_up|send_info|meeting|objection|proposal|check_in|escalate",
            "urgency": "immediate|soon|normal|low",
            "title": "Краткое название (до 50 символов)",
            "description": "Подробное описание что нужно сделать",
            "deadline_days": число_дней_до_дедлайна,
            "reason": "Почему это важно"
        }}
    ]
}}

Правила:
- immediate = сегодня (0 дней)
- soon = 1-2 дня
- normal = 3-5 дней
- low = 7+ дней
- Максимум 3 задачи
- Каждая задача должна быть конкретной и выполнимой
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
                            {
                                "role": "system",
                                "content": "Ты помощник менеджера по продажам. Преобразуй рекомендации в задачи. Отвечай только JSON."
                            },
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.2,
                        "max_tokens": 500,
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
                        request_type="task_conversion"
                    )

                content = result["choices"][0]["message"]["content"]
                data = json.loads(content)

                tasks = []
                for t in data.get("tasks", [])[:3]:
                    try:
                        task = AITask(
                            task_type=TaskType(t.get("task_type", "call")),
                            urgency=TaskUrgency(t.get("urgency", "normal")),
                            title=t.get("title", "Задача")[:100],
                            description=t.get("description", ""),
                            deadline_days=int(t.get("deadline_days", 3)),
                            reason=t.get("reason", ""),
                            source=source
                        )
                        tasks.append(task)
                    except (ValueError, KeyError) as e:
                        logger.warning(f"Invalid task data: {e}")
                        continue

                return tasks

        except Exception as e:
            logger.error(f"AI task conversion failed: {e}")
            return self._simple_convert(recommendations, source)

    def _simple_convert(self, recommendations: List[str], source: str) -> List[AITask]:
        """Простое преобразование без AI"""
        tasks = []

        for rec in recommendations[:2]:
            rec_lower = rec.lower()

            # Определяем тип
            if "позвон" in rec_lower or "звонок" in rec_lower:
                task_type = TaskType.CALL
            elif "встреч" in rec_lower:
                task_type = TaskType.MEETING
            elif "отправ" in rec_lower or "письм" in rec_lower:
                task_type = TaskType.SEND_INFO
            elif "возражен" in rec_lower:
                task_type = TaskType.OBJECTION
            elif "предложен" in rec_lower or "кп" in rec_lower:
                task_type = TaskType.PROPOSAL
            else:
                task_type = TaskType.FOLLOW_UP

            # Определяем срочность
            if "срочно" in rec_lower or "сегодня" in rec_lower or "немедленно" in rec_lower:
                urgency = TaskUrgency.IMMEDIATE
            elif "завтра" in rec_lower or "скоро" in rec_lower:
                urgency = TaskUrgency.SOON
            else:
                urgency = TaskUrgency.NORMAL

            deadline_days = {
                TaskUrgency.IMMEDIATE: 0,
                TaskUrgency.SOON: 1,
                TaskUrgency.NORMAL: 3,
                TaskUrgency.LOW: 7
            }.get(urgency, 3)

            tasks.append(AITask(
                task_type=task_type,
                urgency=urgency,
                title=rec[:50] + ("..." if len(rec) > 50 else ""),
                description=rec,
                deadline_days=deadline_days,
                reason="Рекомендация из анализа",
                source=source
            ))

        return tasks

    async def _get_manager_amocrm_id(self, manager_id: int) -> Optional[str]:
        """Получить AmoCRM user ID менеджера"""
        async with db_manager.get_session() as session:
            from ..database.crud import ManagerCRUD
            manager = await ManagerCRUD.get_manager(session, manager_id)
            if manager:
                return manager.amocrm_user_id
        return None

    async def _create_in_amocrm(
        self,
        lead_id: str,
        manager_id: int,
        amocrm_user_id: str,
        task: AITask
    ) -> CreatedTask:
        """Создать задачу в AmoCRM"""
        try:
            # Рассчитать дедлайн
            deadline = datetime.now() + timedelta(days=task.deadline_days)
            # Установить на конец рабочего дня
            deadline = deadline.replace(hour=18, minute=0, second=0)

            # Формируем текст задачи
            emoji = self.TASK_EMOJIS.get(task.task_type, "📋")
            text = f"{emoji} {task.title}\n\n{task.description}"
            if task.reason:
                text += f"\n\n💡 Причина: {task.reason}"
            text += f"\n\n🤖 Создано AI ({task.source})"

            # Создать в AmoCRM
            success = await amocrm_client.add_task(
                responsible_user_id=amocrm_user_id,
                text=text,
                complete_till=deadline,
                entity_id=lead_id,
                entity_type="leads"
            )

            if success:
                logger.info(
                    f"Created task in AmoCRM",
                    lead_id=lead_id,
                    task_type=task.task_type.value,
                    deadline=deadline.isoformat()
                )

            return CreatedTask(
                amocrm_task_id=None,  # AmoCRM не возвращает ID при создании
                lead_id=lead_id,
                manager_id=manager_id,
                task=task,
                created_at=datetime.utcnow(),
                success=success,
                error=None if success else "Failed to create task in AmoCRM"
            )

        except Exception as e:
            logger.error(f"Failed to create task in AmoCRM: {e}")
            return CreatedTask(
                amocrm_task_id=None,
                lead_id=lead_id,
                manager_id=manager_id,
                task=task,
                created_at=datetime.utcnow(),
                success=False,
                error=str(e)
            )

    async def suggest_tasks(
        self,
        lead_id: str,
        analysis_result: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Предложить задачи без создания (для UI)

        Returns:
            Список предложенных задач для отображения пользователю
        """
        recommendations = self._extract_recommendations(analysis_result)
        if not recommendations:
            return []

        tasks = await self._convert_to_tasks(recommendations, "suggestion")

        return [
            {
                "task_type": t.task_type.value,
                "task_type_label": self._get_task_type_label(t.task_type),
                "emoji": self.TASK_EMOJIS.get(t.task_type, "📋"),
                "urgency": t.urgency.value,
                "urgency_label": self._get_urgency_label(t.urgency),
                "title": t.title,
                "description": t.description,
                "deadline_days": t.deadline_days,
                "reason": t.reason
            }
            for t in tasks
        ]

    def _get_task_type_label(self, task_type: TaskType) -> str:
        labels = {
            TaskType.CALL: "Позвонить",
            TaskType.FOLLOW_UP: "Перезвонить",
            TaskType.SEND_INFO: "Отправить информацию",
            TaskType.MEETING: "Назначить встречу",
            TaskType.OBJECTION: "Отработать возражение",
            TaskType.PROPOSAL: "Подготовить КП",
            TaskType.CHECK_IN: "Проверить статус",
            TaskType.ESCALATE: "Эскалировать",
        }
        return labels.get(task_type, "Задача")

    def _get_urgency_label(self, urgency: TaskUrgency) -> str:
        labels = {
            TaskUrgency.IMMEDIATE: "Сегодня",
            TaskUrgency.SOON: "1-2 дня",
            TaskUrgency.NORMAL: "3-5 дней",
            TaskUrgency.LOW: "Неделя+",
        }
        return labels.get(urgency, "Нормальный")


# Global instance
ai_task_creator = AITaskCreator()
