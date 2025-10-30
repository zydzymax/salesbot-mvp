"""
Commitment Tracker - Детектор Невыполнения Обещаний
Отслеживает обещания менеджеров клиентам и контролирует выполнение
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
import structlog
import json
import re

from ..config import get_settings
from ..database.init_db import db_manager
from ..database.models import Commitment  # Импортируем из models
import httpx

logger = structlog.get_logger("salesbot.analysis.commitment_tracker")


@dataclass
class CommitmentData:
    """Структура данных обещания"""
    text: str
    deadline: datetime
    category: str
    priority: str


class CommitmentTracker:
    """Отслеживает обещания менеджеров"""

    # Паттерны для извлечения обещаний
    COMMITMENT_PATTERNS = [
        # Временные маркеры
        r'(отправлю|вышлю|передам|дам|сделаю|подготовлю|согласую)\s+.*?\s+(сегодня|завтра|послезавтра|через\s+\d+\s+(день|дня|дней|час|часа|часов)|до\s+\w+)',
        r'(перезвоню|свяжусь|созвонимся|встретимся)\s+.*?\s+(сегодня|завтра|послезавтра|на\s+этой\s+неделе|в\s+\w+)',
        r'до\s+(\d{1,2}):(\d{2})|до\s+(\d{1,2})\s+(часов|вечера|утра)',
        r'к\s+(\w+|завтра|сегодня|послезавтра)',
        r'обязательно\s+(сделаю|отправлю|вышлю|перезвоню)',
    ]

    # Категории обещаний
    CATEGORIES = {
        'document': ['кп', 'коммерческое предложение', 'договор', 'документ', 'презентацию', 'прайс'],
        'call': ['перезвоню', 'позвоню', 'свяжусь', 'созвонимся'],
        'meeting': ['встреч', 'приеду', 'приедем', 'визит', 'демо'],
        'approval': ['согласую', 'уточню', 'проверю', 'узнаю'],
        'information': ['отправлю', 'вышлю', 'передам', 'дам информацию']
    }

    def __init__(self):
        self.settings = get_settings()

    async def extract_commitments_from_call(
        self,
        transcription: str,
        call_id: int = None,
        deal_id: int = None,
        manager_id: int = None
    ) -> List[CommitmentData]:
        """
        Извлечь обещания из текста звонка

        Args:
            transcription: Текст разговора
            call_id: ID звонка
            deal_id: ID сделки
            manager_id: ID менеджера

        Returns:
            Список найденных обещаний
        """
        logger.info("Extracting commitments from call", call_id=call_id)

        if not transcription or len(transcription.strip()) < 50:
            return []

        try:
            # Использовать GPT для извлечения обещаний
            commitments_data = await self._extract_with_ai(transcription)

            commitments = []
            for c_data in commitments_data:
                # Определить категорию
                category = self._categorize_commitment(c_data['text'])

                # Парсить дедлайн
                deadline = self._parse_deadline(c_data.get('deadline', 'завтра'))

                # Определить приоритет
                priority = self._calculate_priority(c_data['text'], deadline)

                commitments.append(CommitmentData(
                    text=c_data['text'],
                    deadline=deadline,
                    category=category,
                    priority=priority
                ))

            # Сохранить в БД если есть данные
            if commitments and deal_id and manager_id:
                await self._save_commitments(
                    commitments,
                    call_id=call_id,
                    deal_id=deal_id,
                    manager_id=manager_id
                )

            logger.info(f"Extracted {len(commitments)} commitments")
            return commitments

        except Exception as e:
            logger.error(f"Failed to extract commitments: {e}")
            return []

    async def _extract_with_ai(self, transcription: str) -> List[Dict]:
        """Использовать AI для извлечения обещаний"""

        prompt = f"""
Найди в разговоре ВСЕ обещания менеджера клиенту.

Разговор:
{transcription[:3000]}

Обещание - это когда менеджер говорит что он СДЕЛАЕТ что-то для клиента.
Примеры:
- "Отправлю вам КП сегодня до 18:00"
- "Перезвоню завтра в 10 утра"
- "Согласую скидку с директором и сообщу до пятницы"
- "Вышлю презентацию в течение часа"

НЕ включай:
- Общие фразы типа "свяжемся", "будем на связи" БЕЗ конкретного времени
- Просьбы к клиенту
- Неопределенные фразы

Верни JSON массив:
[
    {
        "text": "Отправлю коммерческое предложение",
        "deadline": "сегодня до 18:00"
    },
    {
        "text": "Перезвоню для уточнения деталей",
        "deadline": "завтра в 10:00"
    }
]

Если обещаний нет - верни пустой массив [].
"""

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.settings.openai_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "gpt-4",
                        "messages": [
                            {
                                "role": "system",
                                "content": "Ты эксперт NLP для извлечения обещаний из текста. Возвращаешь только валидный JSON."
                            },
                            {
                                "role": "user",
                                "content": prompt
                            }
                        ],
                        "max_tokens": 500,
                        "temperature": 0.1
                    }
                )

                response.raise_for_status()
                result = response.json()
                content = result['choices'][0]['message']['content'].strip()

                # Парсить JSON
                # Убрать markdown code blocks если есть
                content = re.sub(r'```json\n?', '', content)
                content = re.sub(r'```\n?', '', content)

                commitments = json.loads(content)
                return commitments if isinstance(commitments, list) else []

        except Exception as e:
            logger.error(f"AI extraction failed: {e}")
            return []

    def _categorize_commitment(self, text: str) -> str:
        """Определить категорию обещания"""
        text_lower = text.lower()

        for category, keywords in self.CATEGORIES.items():
            if any(keyword in text_lower for keyword in keywords):
                return category

        return 'other'

    def _parse_deadline(self, deadline_text: str) -> datetime:
        """Парсить дедлайн из текста"""

        deadline_text = deadline_text.lower().strip()
        now = datetime.now()

        # Сегодня
        if 'сегодня' in deadline_text:
            # Искать время
            time_match = re.search(r'(\d{1,2}):(\d{2})', deadline_text)
            if time_match:
                hour, minute = int(time_match.group(1)), int(time_match.group(2))
                return now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            else:
                return now.replace(hour=18, minute=0, second=0, microsecond=0)

        # Завтра
        elif 'завтра' in deadline_text:
            tomorrow = now + timedelta(days=1)
            time_match = re.search(r'(\d{1,2}):(\d{2})', deadline_text)
            if time_match:
                hour, minute = int(time_match.group(1)), int(time_match.group(2))
                return tomorrow.replace(hour=hour, minute=minute, second=0, microsecond=0)
            else:
                return tomorrow.replace(hour=12, minute=0, second=0, microsecond=0)

        # Через N дней/часов
        elif 'через' in deadline_text:
            match = re.search(r'через\s+(\d+)\s+(день|дня|дней|час|часа|часов)', deadline_text)
            if match:
                number = int(match.group(1))
                unit = match.group(2)
                if 'день' in unit or 'дня' in unit or 'дней' in unit:
                    return now + timedelta(days=number)
                elif 'час' in unit:
                    return now + timedelta(hours=number)

        # На этой неделе
        elif 'на этой неделе' in deadline_text or 'до конца недели' in deadline_text:
            # До пятницы 18:00
            days_until_friday = (4 - now.weekday()) % 7
            return now + timedelta(days=days_until_friday, hours=18-now.hour)

        # По умолчанию - завтра в 12:00
        return (now + timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)

    def _calculate_priority(self, text: str, deadline: datetime) -> str:
        """Вычислить приоритет обещания"""

        hours_until_deadline = (deadline - datetime.now()).total_seconds() / 3600

        # Высокий приоритет
        if hours_until_deadline < 4:
            return 'high'

        # Важные категории
        high_priority_words = ['срочно', 'обязательно', 'важно', 'скидк', 'директор']
        if any(word in text.lower() for word in high_priority_words):
            return 'high'

        # Средний приоритет
        if hours_until_deadline < 24:
            return 'medium'

        return 'low'

    async def _save_commitments(
        self,
        commitments: List[CommitmentData],
        call_id: int,
        deal_id: int,
        manager_id: int
    ):
        """Сохранить обещания в БД"""

        async with db_manager.get_session() as session:
            for commitment in commitments:
                db_commitment = Commitment(
                    call_id=call_id,
                    deal_id=deal_id,
                    manager_id=manager_id,
                    commitment_text=commitment.text,
                    deadline=commitment.deadline,
                    category=commitment.category,
                    priority=commitment.priority
                )
                session.add(db_commitment)

            await session.commit()

    async def check_overdue_commitments(self) -> List[Dict]:
        """Проверить просроченные обещания"""

        async with db_manager.get_session() as session:
            from sqlalchemy import select

            # Найти просроченные и не выполненные
            stmt = select(Commitment).where(
                Commitment.is_fulfilled == False,
                Commitment.deadline < datetime.now()
            )

            result = await session.execute(stmt)
            overdue = result.scalars().all()

            # Пометить как просроченные
            for commitment in overdue:
                if not commitment.is_overdue:
                    commitment.is_overdue = True

            await session.commit()

            return [self._commitment_to_dict(c) for c in overdue]

    async def send_commitment_reminders(self):
        """Отправить напоминания о приближающихся дедлайнах"""

        async with db_manager.get_session() as session:
            from sqlalchemy import select

            # Найти обещания с дедлайном в ближайшие 2 часа
            now = datetime.now()
            two_hours_later = now + timedelta(hours=2)

            stmt = select(Commitment).where(
                Commitment.is_fulfilled == False,
                Commitment.reminder_sent == False,
                Commitment.deadline > now,
                Commitment.deadline <= two_hours_later
            )

            result = await session.execute(stmt)
            upcoming = result.scalars().all()

            # Отправить напоминания
            from ..bot.telegram_bot import send_message

            for commitment in upcoming:
                # Получить менеджера
                manager = commitment.manager
                if not manager or not manager.telegram_chat_id:
                    continue

                # Отправить напоминание
                message = self._format_reminder_message(commitment)
                await send_message(
                    chat_id=manager.telegram_chat_id,
                    text=message
                )

                # Пометить как отправлено
                commitment.reminder_sent = True

            await session.commit()

            logger.info(f"Sent {len(upcoming)} commitment reminders")

    async def escalate_overdue_commitments(self):
        """Эскалировать просроченные обещания руководителю"""

        async with db_manager.get_session() as session:
            from sqlalchemy import select

            # Найти просроченные которые еще не эскалированы
            stmt = select(Commitment).where(
                Commitment.is_overdue == True,
                Commitment.escalated_to_manager == False
            )

            result = await session.execute(stmt)
            overdue = result.scalars().all()

            # Отправить руководителю
            from ..bot.telegram_bot import send_message

            # Группировать по менеджерам
            by_manager = {}
            for commitment in overdue:
                manager_id = commitment.manager_id
                if manager_id not in by_manager:
                    by_manager[manager_id] = []
                by_manager[manager_id].append(commitment)

            # TODO: получить telegram_chat_id руководителя
            # Пока отправляем самому менеджеру
            for manager_id, commitments in by_manager.items():
                manager = commitments[0].manager
                if not manager or not manager.telegram_chat_id:
                    continue

                message = self._format_escalation_message(commitments, manager.name)
                await send_message(
                    chat_id=manager.telegram_chat_id,
                    text=message
                )

                # Пометить как эскалированные
                for commitment in commitments:
                    commitment.escalated_to_manager = True

            await session.commit()

            logger.info(f"Escalated {len(overdue)} overdue commitments")

    def _format_reminder_message(self, commitment: Commitment) -> str:
        """Форматировать напоминание"""

        hours_left = (commitment.deadline - datetime.now()).total_seconds() / 3600

        return f"""
⏰ НАПОМИНАНИЕ ОБ ОБЕЩАНИИ

Ваше обещание: {commitment.commitment_text}
Дедлайн: {commitment.deadline.strftime('%d.%m %H:%M')}
Осталось: {int(hours_left)} ч.

❗️Клиент ждет. Выполните обещание или сообщите о задержке.
"""

    def _format_escalation_message(self, commitments: List[Commitment], manager_name: str) -> str:
        """Форматировать эскалацию"""

        message = f"""
🚨 ОБЕЩАНИЯ НЕ ВЫПОЛНЕНЫ

Менеджер: {manager_name}
Просрочено обещаний: {len(commitments)}

"""

        for commitment in commitments[:5]:  # Топ 5
            hours_overdue = (datetime.now() - commitment.deadline).total_seconds() / 3600

            message += f"""
Обещание: {commitment.commitment_text}
Просрочено: {int(hours_overdue)} ч.

"""

        message += "\n⚠️ Требуется вмешательство!"

        return message

    def _commitment_to_dict(self, commitment: Commitment) -> Dict:
        """Преобразовать модель в dict"""
        return {
            'id': commitment.id,
            'deal_id': commitment.deal_id,
            'manager_id': commitment.manager_id,
            'text': commitment.commitment_text,
            'deadline': commitment.deadline.isoformat(),
            'category': commitment.category,
            'priority': commitment.priority,
            'is_fulfilled': commitment.is_fulfilled,
            'is_overdue': commitment.is_overdue
        }


# Global instance
commitment_tracker = CommitmentTracker()
