"""
Activity Validator - Детектор "Мертвых Душ"
Выявляет подозрительную и фейковую активность менеджеров
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from collections import Counter
import structlog

from ..config import get_settings
from ..database.init_db import db_manager
from ..database.crud import CallCRUD
import httpx

logger = structlog.get_logger("salesbot.fraud.activity_validator")


class ActivityValidator:
    """Проверяет подлинность активности менеджеров"""

    # Пороги для красных флагов
    THRESHOLDS = {
        'same_number_max_calls': 10,  # Максимум звонков на один номер
        'short_calls_ratio': 0.30,    # Макс. доля коротких звонков
        'night_calls_max': 5,          # Макс. звонков в нерабочее время
        'min_conversion_rate': 0.05,   # Мин. конверсия при большой активности
        'suspicious_conversation_threshold': 0.7  # Порог подозрительности
    }

    def __init__(self):
        self.settings = get_settings()

    async def detect_suspicious_activity(
        self,
        manager_id: int,
        days: int = 7
    ) -> Dict[str, Any]:
        """
        Обнаружить подозрительную активность менеджера

        Args:
            manager_id: ID менеджера
            days: Проверить за последние N дней

        Returns:
            Dict с результатами проверки и красными флагами
        """
        logger.info("Checking for suspicious activity", manager_id=manager_id, days=days)

        try:
            # Получить данные менеджера
            async with db_manager.get_session() as session:
                from ..database.crud import ManagerCRUD
                manager = await ManagerCRUD.get_manager(session, manager_id)

                if not manager:
                    return {'error': 'Manager not found'}

            # Получить звонки за период
            calls = await self._get_manager_calls(manager_id, days)

            if not calls:
                return {
                    'manager_id': manager_id,
                    'is_suspicious': False,
                    'red_flags': [],
                    'message': 'Недостаточно данных для анализа'
                }

            # Проверки
            red_flags = []

            # 1. Звонки на один и тот же номер
            same_number_flag = self._check_same_number_repeatedly(calls)
            if same_number_flag:
                red_flags.append(same_number_flag)

            # 2. Слишком много коротких звонков
            short_calls_flag = self._check_too_many_short_calls(calls)
            if short_calls_flag:
                red_flags.append(short_calls_flag)

            # 3. Звонки в нерабочее время
            night_calls_flag = self._check_calls_outside_hours(calls)
            if night_calls_flag:
                red_flags.append(night_calls_flag)

            # 4. AI анализ разговоров на осмысленность
            fake_conversations_flag = await self._check_conversation_validity(calls)
            if fake_conversations_flag:
                red_flags.append(fake_conversations_flag)

            # 5. Высокая активность без результатов
            no_results_flag = await self._check_activity_without_results(manager_id, calls)
            if no_results_flag:
                red_flags.append(no_results_flag)

            # 6. Паттерн времени звонков (всегда в одно время)
            time_pattern_flag = self._check_suspicious_time_pattern(calls)
            if time_pattern_flag:
                red_flags.append(time_pattern_flag)

            # Определить общий уровень подозрительности
            is_suspicious = len(red_flags) >= 2  # 2+ красных флага = подозрительно
            confidence = min(len(red_flags) * 0.25, 1.0)  # 0.0 - 1.0

            return {
                'manager_id': manager_id,
                'manager_name': manager.name,
                'period_days': days,
                'total_calls': len(calls),
                'is_suspicious': is_suspicious,
                'confidence': confidence,
                'red_flags': red_flags,
                'red_flags_count': len(red_flags),
                'recommended_action': self._get_recommended_action(len(red_flags)),
                'checked_at': datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.error(f"Failed to detect suspicious activity: {e}", manager_id=manager_id)
            return {'error': str(e)}

    async def _get_manager_calls(self, manager_id: int, days: int) -> List:
        """Получить звонки менеджера за период"""

        from_date = datetime.utcnow() - timedelta(days=days)

        async with db_manager.get_session() as session:
            from sqlalchemy import select, and_
            from ..database.models import Call

            stmt = select(Call).where(
                and_(
                    Call.manager_id == manager_id,
                    Call.created_at >= from_date
                )
            )

            result = await session.execute(stmt)
            return list(result.scalars().all())

    def _check_same_number_repeatedly(self, calls: List) -> Optional[Dict]:
        """Проверка: много звонков на один номер"""

        phone_numbers = [c.client_phone for c in calls if c.client_phone]

        if not phone_numbers:
            return None

        phone_frequency = Counter(phone_numbers)
        max_calls_to_same = max(phone_frequency.values())
        most_called_number = max(phone_frequency, key=phone_frequency.get)

        if max_calls_to_same > self.THRESHOLDS['same_number_max_calls']:
            return {
                'type': 'same_number_repeatedly',
                'severity': 'high',
                'description': f'{max_calls_to_same} звонков на один номер ({most_called_number})',
                'details': {
                    'phone': most_called_number,
                    'call_count': max_calls_to_same
                }
            }

        return None

    def _check_too_many_short_calls(self, calls: List) -> Optional[Dict]:
        """Проверка: слишком много коротких звонков"""

        if not calls:
            return None

        short_calls = [c for c in calls if c.duration and c.duration < 10]
        ratio = len(short_calls) / len(calls)

        if ratio > self.THRESHOLDS['short_calls_ratio']:
            return {
                'type': 'too_many_short_calls',
                'severity': 'medium',
                'description': f'{int(ratio * 100)}% звонков короче 10 секунд',
                'details': {
                    'short_calls_count': len(short_calls),
                    'total_calls': len(calls),
                    'ratio': round(ratio, 2)
                }
            }

        return None

    def _check_calls_outside_hours(self, calls: List) -> Optional[Dict]:
        """Проверка: звонки в нерабочее время"""

        night_calls = []
        for call in calls:
            hour = call.created_at.hour
            if hour < 9 or hour > 20:
                night_calls.append(call)

        if len(night_calls) > self.THRESHOLDS['night_calls_max']:
            return {
                'type': 'calls_outside_hours',
                'severity': 'medium',
                'description': f'{len(night_calls)} звонков в нерабочее время (до 9:00 или после 20:00)',
                'details': {
                    'night_calls_count': len(night_calls),
                    'times': [c.created_at.strftime('%H:%M') for c in night_calls[:5]]
                }
            }

        return None

    async def _check_conversation_validity(self, calls: List) -> Optional[Dict]:
        """Проверка: AI анализ осмысленности разговоров"""

        # Выборочно проверить 5-10 звонков с транскрипцией
        calls_with_transcription = [
            c for c in calls
            if c.transcription_text and len(c.transcription_text) > 100
        ]

        if not calls_with_transcription:
            return None

        # Проверить случайную выборку
        import random
        sample_size = min(5, len(calls_with_transcription))
        sample_calls = random.sample(calls_with_transcription, sample_size)

        suspicious_count = 0
        for call in sample_calls:
            is_valid = await self._validate_single_conversation(call.transcription_text)
            if not is_valid:
                suspicious_count += 1

        # Если >50% подозрительны
        if suspicious_count / sample_size > 0.5:
            return {
                'type': 'suspicious_conversations',
                'severity': 'high',
                'description': f'{suspicious_count} из {sample_size} разговоров выглядят ненастоящими',
                'details': {
                    'suspicious_count': suspicious_count,
                    'checked_count': sample_size
                }
            }

        return None

    async def _validate_single_conversation(self, transcription: str) -> bool:
        """Проверить один разговор на осмысленность"""

        if not self.settings.openai_api_key:
            return True  # Не можем проверить

        prompt = f"""
Это транскрипция разговора между менеджером и клиентом:

{transcription[:1000]}

Оцени: это настоящий бизнес-разговор или фейковый/бессмысленный?

Признаки фейкового:
- Нет бизнес-контекста (не обсуждается продукт, услуга, цена)
- Общая болтовня не по теме
- Искусственный диалог
- Повторяющиеся фразы

Ответь ТОЛЬКО одним словом: НАСТОЯЩИЙ или ФЕЙКОВЫЙ
"""

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.settings.openai_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "gpt-3.5-turbo",
                        "messages": [
                            {"role": "system", "content": "Ты детектор фейковых разговоров."},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": 10,
                        "temperature": 0.1
                    }
                )

                response.raise_for_status()
                result = response.json()
                answer = result['choices'][0]['message']['content'].strip().upper()

                return 'НАСТОЯЩИЙ' in answer or 'REAL' in answer

        except Exception as e:
            logger.error(f"Failed to validate conversation: {e}")
            return True  # При ошибке считаем нормальным

    async def _check_activity_without_results(self, manager_id: int, calls: List) -> Optional[Dict]:
        """Проверка: много активности без результатов"""

        if len(calls) < 30:
            return None  # Мало данных

        # Получить сделки менеджера
        async with db_manager.get_session() as session:
            from sqlalchemy import select, and_, func
            from ..database.models import Call

            # Подсчитать закрытые сделки за тот же период
            from_date = min(c.created_at for c in calls)

            # TODO: добавить модель Deal и подсчитать conversion
            # Пока упрощенно - если много звонков но мало разных клиентов

            unique_phones = len(set(c.client_phone for c in calls if c.client_phone))
            calls_per_client = len(calls) / max(unique_phones, 1)

            # Если >5 звонков на клиента в среднем - подозрительно
            if calls_per_client > 5:
                return {
                    'type': 'high_activity_no_results',
                    'severity': 'medium',
                    'description': f'{len(calls)} звонков на {unique_phones} клиентов (среднее {calls_per_client:.1f} звонков/клиент)',
                    'details': {
                        'total_calls': len(calls),
                        'unique_clients': unique_phones,
                        'calls_per_client': round(calls_per_client, 1)
                    }
                }

        return None

    def _check_suspicious_time_pattern(self, calls: List) -> Optional[Dict]:
        """Проверка: подозрительный паттерн времени звонков"""

        if len(calls) < 20:
            return None

        # Собрать время звонков (часы)
        call_hours = [c.created_at.hour for c in calls]
        hour_frequency = Counter(call_hours)

        # Если >70% звонков в один час - подозрительно
        max_hour_calls = max(hour_frequency.values())
        if max_hour_calls / len(calls) > 0.7:
            most_common_hour = max(hour_frequency, key=hour_frequency.get)

            return {
                'type': 'suspicious_time_pattern',
                'severity': 'low',
                'description': f'{int(max_hour_calls/len(calls)*100)}% звонков в {most_common_hour}:00',
                'details': {
                    'most_common_hour': most_common_hour,
                    'calls_at_that_hour': max_hour_calls,
                    'total_calls': len(calls)
                }
            }

        return None

    def _get_recommended_action(self, red_flags_count: int) -> str:
        """Получить рекомендованное действие"""

        if red_flags_count >= 4:
            return 'immediate_investigation'  # Немедленная проверка
        elif red_flags_count >= 2:
            return 'manual_review'  # Ручная проверка
        elif red_flags_count == 1:
            return 'monitor'  # Наблюдение
        else:
            return 'no_action'  # Всё ок


# Global instance
activity_validator = ActivityValidator()
