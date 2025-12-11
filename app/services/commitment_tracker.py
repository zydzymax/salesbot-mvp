"""
Commitment Tracker - Отслеживание обязательств из звонков
Трекает обещания клиента и менеджера с напоминаниями
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from enum import Enum
import json
import re
import httpx
import structlog

from ..config import get_settings
from ..database.init_db import db_manager
from ..utils.api_budget import api_budget, BudgetExceededError
from ..utils.runtime_settings import runtime_settings

logger = structlog.get_logger("salesbot.services.commitment_tracker")


class CommitmentType(str, Enum):
    """Тип обязательства"""
    CLIENT_CALL_BACK = "client_call_back"         # Клиент перезвонит
    CLIENT_DECIDE = "client_decide"               # Клиент примет решение
    CLIENT_SEND_DOCS = "client_send_docs"         # Клиент отправит документы
    CLIENT_DISCUSS = "client_discuss"             # Клиент обсудит (с семьей/руководством)
    CLIENT_MEETING = "client_meeting"             # Клиент придет на встречу
    MANAGER_CALL_BACK = "manager_call_back"       # Менеджер перезвонит
    MANAGER_SEND_INFO = "manager_send_info"       # Менеджер отправит информацию
    MANAGER_PREPARE_PROPOSAL = "manager_prepare"  # Менеджер подготовит предложение
    MANAGER_MEETING = "manager_meeting"           # Менеджер назначит встречу
    PAYMENT = "payment"                           # Оплата


class CommitmentStatus(str, Enum):
    """Статус обязательства"""
    PENDING = "pending"           # Ожидает выполнения
    OVERDUE = "overdue"           # Просрочено
    COMPLETED = "completed"       # Выполнено
    CANCELLED = "cancelled"       # Отменено


class CommitmentOwner(str, Enum):
    """Кто дал обязательство"""
    CLIENT = "client"
    MANAGER = "manager"


@dataclass
class Commitment:
    """Обязательство из разговора"""
    id: Optional[str]
    commitment_type: CommitmentType
    owner: CommitmentOwner
    description: str
    quote: str                    # Цитата из разговора
    deadline: Optional[datetime]  # Когда должно быть выполнено
    deadline_text: str            # Текстовое описание срока ("завтра", "в понедельник")
    status: CommitmentStatus
    lead_id: str
    call_id: str
    manager_id: int
    created_at: datetime
    completed_at: Optional[datetime] = None
    reminder_sent: bool = False

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["commitment_type"] = self.commitment_type.value
        result["owner"] = self.owner.value
        result["status"] = self.status.value
        if self.deadline:
            result["deadline"] = self.deadline.isoformat()
        if self.created_at:
            result["created_at"] = self.created_at.isoformat()
        if self.completed_at:
            result["completed_at"] = self.completed_at.isoformat()
        return result


@dataclass
class CommitmentSummary:
    """Сводка по обязательствам для сделки"""
    lead_id: str
    total_commitments: int
    pending_count: int
    overdue_count: int
    completed_count: int
    client_commitments: List[Dict]
    manager_commitments: List[Dict]
    next_deadline: Optional[datetime]
    health_score: int  # 0-100, насколько хорошо выполняются обязательства


class CommitmentTracker:
    """Сервис отслеживания обязательств"""

    # Паттерны для определения сроков
    DEADLINE_PATTERNS = {
        r"сегодня": 0,
        r"завтра": 1,
        r"послезавтра": 2,
        r"через\s+(\d+)\s+дн": lambda m: int(m.group(1)),
        r"через\s+(\d+)\s+час": lambda m: 0,  # Сегодня
        r"в\s+понедельник": lambda: (7 - datetime.now().weekday()) % 7 or 7,
        r"в\s+пятницу": lambda: (4 - datetime.now().weekday()) % 7 or 7,
        r"на\s+следующей\s+неделе": 7,
        r"через\s+неделю": 7,
        r"в\s+конце\s+недели": lambda: max(0, 4 - datetime.now().weekday()),
    }

    def __init__(self):
        self.settings = get_settings()

    async def extract_commitments(
        self,
        transcription: str,
        lead_id: str,
        call_id: str,
        manager_id: int
    ) -> List[Commitment]:
        """
        Извлечь обязательства из транскрипции звонка

        Args:
            transcription: Текст разговора
            lead_id: ID сделки
            call_id: ID звонка
            manager_id: ID менеджера

        Returns:
            Список обязательств
        """
        if not transcription or len(transcription.strip()) < 50:
            return []

        # Проверка бюджета
        allowed, reason = api_budget.can_make_request(0.04)
        if not allowed:
            logger.warning(f"Budget exceeded for commitment extraction: {reason}")
            return []

        try:
            model = await runtime_settings.get_model()
            commitments_data = await self._extract_with_gpt(transcription, model)

            if not commitments_data:
                return []

            commitments = []
            for c in commitments_data:
                try:
                    deadline = self._parse_deadline(c.get("deadline_text", ""))

                    commitment = Commitment(
                        id=None,
                        commitment_type=CommitmentType(c.get("type", "client_call_back")),
                        owner=CommitmentOwner(c.get("owner", "client")),
                        description=c.get("description", ""),
                        quote=c.get("quote", ""),
                        deadline=deadline,
                        deadline_text=c.get("deadline_text", ""),
                        status=CommitmentStatus.PENDING,
                        lead_id=lead_id,
                        call_id=call_id,
                        manager_id=manager_id,
                        created_at=datetime.utcnow()
                    )
                    commitments.append(commitment)
                except (ValueError, KeyError) as e:
                    logger.warning(f"Invalid commitment data: {e}")
                    continue

            logger.info(f"Extracted {len(commitments)} commitments", lead_id=lead_id)
            return commitments

        except Exception as e:
            logger.error(f"Commitment extraction failed: {e}")
            return []

    async def _extract_with_gpt(
        self,
        transcription: str,
        model: str
    ) -> List[Dict]:
        """Извлечь обязательства через GPT"""

        prompt = f"""Проанализируй разговор и найди все обязательства (обещания):
- Что клиент пообещал сделать
- Что менеджер пообещал сделать

РАЗГОВОР:
{transcription[:4000]}

Верни JSON со списком обязательств:
{{
    "commitments": [
        {{
            "type": "client_call_back|client_decide|client_send_docs|client_discuss|client_meeting|manager_call_back|manager_send_info|manager_prepare|manager_meeting|payment",
            "owner": "client|manager",
            "description": "Краткое описание обязательства",
            "quote": "Точная цитата из разговора",
            "deadline_text": "Когда обещали (завтра, через 2 дня, в понедельник, на следующей неделе)"
        }}
    ]
}}

Правила:
- Ищи явные обещания ("я перезвоню", "отправлю", "подумаю до...", "решу к...")
- Включай только конкретные обязательства с понятным действием
- deadline_text пиши как сказано в разговоре
- Если срок не указан, пиши "не указан"
- Максимум 5 обязательств
"""

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
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
                                "content": "Ты эксперт по анализу продаж. Находишь обязательства в разговорах. Отвечай только JSON."
                            },
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.2,
                        "max_tokens": 800,
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
                        request_type="commitment_extraction"
                    )

                content = result["choices"][0]["message"]["content"]
                data = json.loads(content)
                return data.get("commitments", [])[:5]

        except Exception as e:
            logger.error(f"GPT commitment extraction failed: {e}")
            return []

    def _parse_deadline(self, deadline_text: str) -> Optional[datetime]:
        """Преобразовать текстовый срок в дату"""
        if not deadline_text or deadline_text.lower() in ["не указан", "неизвестно", ""]:
            return None

        text = deadline_text.lower().strip()
        base_date = datetime.now().replace(hour=18, minute=0, second=0, microsecond=0)

        for pattern, days in self.DEADLINE_PATTERNS.items():
            match = re.search(pattern, text)
            if match:
                if callable(days):
                    if hasattr(days, '__code__') and days.__code__.co_argcount > 0:
                        days = days(match)
                    else:
                        days = days()
                return base_date + timedelta(days=days)

        # Fallback: через 3 дня
        return base_date + timedelta(days=3)

    async def get_deal_commitments(
        self,
        lead_id: str,
        include_completed: bool = False
    ) -> CommitmentSummary:
        """
        Получить все обязательства по сделке

        Args:
            lead_id: ID сделки
            include_completed: Включать выполненные

        Returns:
            Сводка по обязательствам
        """
        # В текущей реализации храним в памяти/Redis
        # TODO: Добавить модель в БД для персистентности

        async with db_manager.get_session() as session:
            from sqlalchemy import select
            from ..database.models import Call

            # Получить все звонки по сделке с анализом
            stmt = select(Call).where(
                Call.amocrm_lead_id == lead_id,
                Call.transcription_text.isnot(None)
            ).order_by(Call.created_at.desc())

            result = await session.execute(stmt)
            calls = list(result.scalars().all())

        all_commitments = []

        for call in calls[:5]:  # Последние 5 звонков
            commitments = await self.extract_commitments(
                transcription=call.transcription_text,
                lead_id=lead_id,
                call_id=str(call.id),
                manager_id=call.manager_id
            )
            all_commitments.extend(commitments)

        # Обновить статусы (просроченные)
        now = datetime.utcnow()
        for c in all_commitments:
            if c.deadline and c.deadline < now and c.status == CommitmentStatus.PENDING:
                c.status = CommitmentStatus.OVERDUE

        # Фильтрация
        if not include_completed:
            all_commitments = [c for c in all_commitments if c.status != CommitmentStatus.COMPLETED]

        # Разделение по владельцам
        client_commitments = [c.to_dict() for c in all_commitments if c.owner == CommitmentOwner.CLIENT]
        manager_commitments = [c.to_dict() for c in all_commitments if c.owner == CommitmentOwner.MANAGER]

        # Подсчеты
        pending = [c for c in all_commitments if c.status == CommitmentStatus.PENDING]
        overdue = [c for c in all_commitments if c.status == CommitmentStatus.OVERDUE]
        completed = [c for c in all_commitments if c.status == CommitmentStatus.COMPLETED]

        # Следующий дедлайн
        pending_with_deadline = [c for c in pending if c.deadline]
        next_deadline = min((c.deadline for c in pending_with_deadline), default=None)

        # Health score
        total = len(all_commitments)
        if total > 0:
            # Штрафы за просроченные
            health_score = max(0, 100 - (len(overdue) * 20))
            # Бонус за выполненные
            if len(completed) > 0:
                health_score = min(100, health_score + 10)
        else:
            health_score = 100

        return CommitmentSummary(
            lead_id=lead_id,
            total_commitments=total,
            pending_count=len(pending),
            overdue_count=len(overdue),
            completed_count=len(completed),
            client_commitments=client_commitments,
            manager_commitments=manager_commitments,
            next_deadline=next_deadline,
            health_score=health_score
        )

    async def get_overdue_commitments(
        self,
        manager_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Получить все просроченные обязательства

        Args:
            manager_id: Фильтр по менеджеру (None = все)

        Returns:
            Список просроченных обязательств
        """
        # В реальной реализации это был бы запрос к БД
        # Сейчас - заглушка для API
        return []

    async def send_reminder(
        self,
        commitment: Commitment,
        reminder_type: str = "telegram"
    ) -> bool:
        """
        Отправить напоминание об обязательстве

        Args:
            commitment: Обязательство
            reminder_type: Тип напоминания (telegram, email)

        Returns:
            Успешность отправки
        """
        if reminder_type == "telegram":
            from ..bot.telegram_bot import send_reminder_message

            emoji = "📞" if commitment.owner == CommitmentOwner.CLIENT else "📋"
            owner_text = "Клиент" if commitment.owner == CommitmentOwner.CLIENT else "Вы"

            message = (
                f"{emoji} <b>Напоминание об обязательстве</b>\n\n"
                f"{owner_text} обещал: {commitment.description}\n"
            )

            if commitment.deadline:
                message += f"⏰ Срок: {commitment.deadline.strftime('%d.%m.%Y')}\n"

            if commitment.status == CommitmentStatus.OVERDUE:
                message += "\n⚠️ <b>Просрочено!</b>"

            message += f"\n\n💬 Цитата: <i>\"{commitment.quote}\"</i>"

            try:
                # Получить telegram_id менеджера
                async with db_manager.get_session() as session:
                    from ..database.crud import ManagerCRUD
                    manager = await ManagerCRUD.get_manager(session, commitment.manager_id)
                    if manager and manager.telegram_id:
                        await send_reminder_message(
                            chat_id=manager.telegram_id,
                            message=message
                        )
                        return True
            except Exception as e:
                logger.error(f"Failed to send reminder: {e}")

        return False


# Global instance
commitment_tracker = CommitmentTracker()
