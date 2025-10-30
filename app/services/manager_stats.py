"""
Manager Statistics Service - сбор статистики менеджеров из AmoCRM
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import structlog

from ..amocrm.client import amocrm_client
from ..database.init_db import db_manager
from ..database.crud import ManagerCRUD, CallCRUD

logger = structlog.get_logger("salesbot.manager_stats")


class ManagerStatsService:
    """Сервис для получения статистики менеджеров из AmoCRM и базы данных"""

    async def get_all_managers_stats(self) -> List[Dict[str, Any]]:
        """
        Получить статистику по всем менеджерам

        Returns:
            Список словарей с данными о каждом менеджере:
            - id, name, telegram_chat_id
            - deals_in_progress - количество сделок в работе
            - deals_completed_all_time - количество завершенных сделок за все время
            - revenue_all_time - выручка от закрытых сделок
            - tasks_today_assigned - задач назначено сегодня
            - tasks_today_completed - задач выполнено сегодня
            - last_call_date - дата последнего звонка
        """
        try:
            # Получить всех активных менеджеров из БД
            async with db_manager.get_session() as session:
                managers = await ManagerCRUD.get_active_managers(session)

            if not managers:
                return []

            # Собрать статистику по каждому менеджеру
            managers_stats = []
            for manager in managers:
                stats = await self.get_manager_stats(manager.amocrm_id, manager.name)
                stats['db_id'] = manager.id
                stats['telegram_chat_id'] = manager.telegram_chat_id
                managers_stats.append(stats)

            # Сортировать по количеству сделок в работе
            managers_stats.sort(key=lambda x: x['deals_in_progress'], reverse=True)

            logger.info(
                "Managers stats collected",
                managers_count=len(managers_stats)
            )

            return managers_stats

        except Exception as e:
            logger.error(f"Failed to get managers stats", error=str(e))
            return []

    async def get_manager_stats(
        self,
        manager_amocrm_id: int,
        manager_name: str = None
    ) -> Dict[str, Any]:
        """
        Получить статистику конкретного менеджера

        Args:
            manager_amocrm_id: ID менеджера в AmoCRM
            manager_name: Имя менеджера (опционально)

        Returns:
            Словарь с данными менеджера
        """
        try:
            stats = {
                'amocrm_id': manager_amocrm_id,
                'name': manager_name or f"Manager #{manager_amocrm_id}",
                'deals_in_progress': 0,
                'deals_completed_all_time': 0,
                'revenue_all_time': 0,
                'tasks_today_assigned': 0,
                'tasks_today_completed': 0,
                'last_call_date': None,
                'calls_with_transcription': 0,
                'avg_quality_score': 0
            }

            # Получить сделки в работе (статусы для воронки)
            # В AmoCRM статусы: 142 - Первичный контакт, 143 - Переговоры, и т.д.
            # Статус 142 = новые, 143 = в работе, 39536394 = успешно (закрыто)
            deals_in_progress_response = await amocrm_client.get_leads(
                limit=250,
                filter_params={
                    "filter[responsible_user_id][]": [manager_amocrm_id],
                    "filter[statuses][0][pipeline_id]": 7841826,  # ID воронки
                    # Не включаем завершенные статусы
                }
            )
            deals = deals_in_progress_response.get('_embedded', {}).get('leads', [])

            # Считаем сделки в работе (исключая закрытые статусы)
            closed_status_ids = [142, 143]  # ID успешно закрытых и отказов
            deals_in_progress_list = [
                d for d in deals
                if d.get('status_id') not in closed_status_ids
            ]
            stats['deals_in_progress'] = len(deals_in_progress_list)

            # Получить завершенные сделки за все время
            # Статус 142 и 143 - это закрытые сделки
            deals_completed_response = await amocrm_client.get_leads(
                limit=250,
                filter_params={
                    "filter[responsible_user_id][]": [manager_amocrm_id],
                    "filter[statuses][0][pipeline_id]": 7841826,
                    "filter[statuses][0][status_id][]": [142, 143]  # Закрытые статусы
                }
            )
            completed_deals = deals_completed_response.get('_embedded', {}).get('leads', [])
            stats['deals_completed_all_time'] = len(completed_deals)

            # Посчитать выручку от успешно закрытых (status_id = 142 - успешно закрыто)
            successfully_closed = [d for d in completed_deals if d.get('status_id') == 142]
            revenue = sum(d.get('price', 0) for d in successfully_closed)
            stats['revenue_all_time'] = revenue

            # Получить задачи на сегодня
            # AmoCRM API для задач - используем фильтр по дате
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            today_end = today_start + timedelta(days=1)

            try:
                # Задачи назначенные на сегодня (через API tasks)
                # Примечание: AmoCRM API для задач требует отдельного эндпоинта
                # Пока используем упрощенную версию через notes
                pass  # TODO: Реализовать получение задач через API
            except Exception as e:
                logger.warning(f"Failed to get tasks for manager", error=str(e))

            # Получить данные из нашей БД (звонки с транскрипцией и оценками)
            async with db_manager.get_session() as session:
                from sqlalchemy import select, func
                from ..database.models import Call

                # Последний звонок
                last_call_stmt = select(Call).where(
                    Call.manager_id == manager_amocrm_id
                ).order_by(Call.created_at.desc()).limit(1)

                last_call_result = await session.execute(last_call_stmt)
                last_call = last_call_result.scalar_one_or_none()

                if last_call:
                    stats['last_call_date'] = last_call.created_at

                # Звонки с транскрипцией
                transcribed_count_stmt = select(func.count(Call.id)).where(
                    Call.manager_id == manager_amocrm_id,
                    Call.transcription_text.isnot(None)
                )
                transcribed_count = await session.scalar(transcribed_count_stmt)
                stats['calls_with_transcription'] = transcribed_count or 0

                # Средний score
                avg_score_stmt = select(func.avg(Call.quality_score)).where(
                    Call.manager_id == manager_amocrm_id,
                    Call.quality_score.isnot(None)
                )
                avg_score = await session.scalar(avg_score_stmt)
                stats['avg_quality_score'] = round(avg_score, 1) if avg_score else 0

            logger.info(
                "Manager stats collected",
                manager_id=manager_amocrm_id,
                deals_in_progress=stats['deals_in_progress'],
                deals_completed=stats['deals_completed_all_time']
            )

            return stats

        except Exception as e:
            logger.error(
                f"Failed to get manager stats",
                manager_id=manager_amocrm_id,
                error=str(e)
            )
            # Вернуть базовые данные при ошибке
            return {
                'amocrm_id': manager_amocrm_id,
                'name': manager_name or f"Manager #{manager_amocrm_id}",
                'deals_in_progress': 0,
                'deals_completed_all_time': 0,
                'revenue_all_time': 0,
                'tasks_today_assigned': 0,
                'tasks_today_completed': 0,
                'last_call_date': None,
                'calls_with_transcription': 0,
                'avg_quality_score': 0,
                'error': str(e)
            }

    async def get_manager_deals(
        self,
        manager_amocrm_id: int,
        include_closed: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Получить все сделки менеджера с информацией о звонках

        Args:
            manager_amocrm_id: ID менеджера в AmoCRM
            include_closed: Включать ли закрытые сделки

        Returns:
            Список сделок с дополнительной информацией
        """
        try:
            # Получить сделки менеджера из AmoCRM
            filter_params = {
                "filter[responsible_user_id][]": [manager_amocrm_id],
                "filter[statuses][0][pipeline_id]": 7841826
            }

            if not include_closed:
                # Исключить закрытые статусы
                closed_status_ids = [142, 143]
                # AmoCRM не поддерживает "не равно", поэтому получаем все и фильтруем

            response = await amocrm_client.get_leads(
                limit=250,
                filter_params=filter_params
            )

            deals = response.get('_embedded', {}).get('leads', [])

            if not include_closed:
                closed_status_ids = {142, 143}
                deals = [d for d in deals if d.get('status_id') not in closed_status_ids]

            # Для каждой сделки получить информацию о звонках из БД
            deals_with_calls = []
            async with db_manager.get_session() as session:
                from sqlalchemy import select, func
                from ..database.models import Call

                for deal in deals:
                    lead_id = str(deal['id'])

                    # Получить звонки по этой сделке
                    calls_stmt = select(
                        func.count(Call.id).label('total_calls'),
                        func.count(Call.transcription_text).label('transcribed_calls'),
                        func.avg(Call.quality_score).label('avg_quality'),
                        func.max(Call.created_at).label('last_call_date')
                    ).where(
                        Call.amocrm_lead_id == lead_id
                    )

                    calls_result = await session.execute(calls_stmt)
                    calls_stats = calls_result.one_or_none()

                    deal_info = {
                        'id': lead_id,
                        'name': deal.get('name', f"Сделка #{lead_id}"),
                        'price': deal.get('price', 0),
                        'status_id': deal.get('status_id'),
                        'created_at': datetime.fromtimestamp(deal.get('created_at', 0)),
                        'updated_at': datetime.fromtimestamp(deal.get('updated_at', 0)),
                        'total_calls': calls_stats.total_calls if calls_stats else 0,
                        'transcribed_calls': calls_stats.transcribed_calls if calls_stats else 0,
                        'avg_quality': round(calls_stats.avg_quality, 1) if calls_stats and calls_stats.avg_quality else 0,
                        'last_call_date': calls_stats.last_call_date if calls_stats else None
                    }

                    deals_with_calls.append(deal_info)

            # Сортировать по дате последнего обновления
            deals_with_calls.sort(key=lambda x: x['updated_at'], reverse=True)

            logger.info(
                "Manager deals retrieved",
                manager_id=manager_amocrm_id,
                deals_count=len(deals_with_calls)
            )

            return deals_with_calls

        except Exception as e:
            logger.error(
                f"Failed to get manager deals",
                manager_id=manager_amocrm_id,
                error=str(e)
            )
            return []


# Global service instance
manager_stats_service = ManagerStatsService()
