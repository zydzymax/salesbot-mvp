"""
Manager Dashboard - Дашборд Эффективности Менеджеров
Агрегация метрик и KPI для управления командой продаж
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
import structlog

from ..config import get_settings
from ..database.init_db import db_manager

logger = structlog.get_logger("salesbot.analytics.manager_dashboard")


@dataclass
class ManagerKPI:
    """KPI менеджера"""
    manager_id: int
    manager_name: str

    # Активность
    calls_made: int
    calls_answered: int
    avg_call_duration: int  # секунды
    response_time_avg_hours: float

    # Качество
    avg_quality_score: float  # 0-100
    calls_with_quality_score: int

    # Обещания
    total_commitments: int
    fulfilled_commitments: int
    overdue_commitments: int
    commitment_fulfillment_rate: float

    # Подозрительность
    suspicious_activity_score: float  # 0-1
    red_flags_count: int

    # Временной период
    period_start: str
    period_end: str
    calculated_at: str


class ManagerDashboard:
    """Дашборд эффективности менеджеров"""

    def __init__(self):
        self.settings = get_settings()

    async def get_manager_kpi(
        self,
        manager_id: int,
        period_days: int = 7
    ) -> Dict[str, Any]:
        """
        Получить KPI конкретного менеджера

        Args:
            manager_id: ID менеджера
            period_days: Период в днях

        Returns:
            Dict с KPI менеджера
        """
        logger.info("Getting manager KPI", manager_id=manager_id, period_days=period_days)

        try:
            period_start = datetime.utcnow() - timedelta(days=period_days)
            period_end = datetime.utcnow()

            # Получить менеджера
            async with db_manager.get_session() as session:
                from ..database.crud import ManagerCRUD
                manager = await ManagerCRUD.get_manager(session, manager_id)

                if not manager:
                    return {'error': 'Manager not found'}

            # Собрать метрики
            calls_metrics = await self._get_calls_metrics(manager_id, period_start, period_end)
            quality_metrics = await self._get_quality_metrics(manager_id, period_start, period_end)
            commitments_metrics = await self._get_commitments_metrics(manager_id, period_start, period_end)
            fraud_metrics = await self._get_fraud_metrics(manager_id, period_days)

            kpi = ManagerKPI(
                manager_id=manager_id,
                manager_name=manager.name,

                # Активность
                calls_made=calls_metrics['total_calls'],
                calls_answered=calls_metrics['answered_calls'],
                avg_call_duration=calls_metrics['avg_duration'],
                response_time_avg_hours=calls_metrics.get('avg_response_time', 0),

                # Качество
                avg_quality_score=quality_metrics['avg_score'],
                calls_with_quality_score=quality_metrics['scored_calls'],

                # Обещания
                total_commitments=commitments_metrics['total'],
                fulfilled_commitments=commitments_metrics['fulfilled'],
                overdue_commitments=commitments_metrics['overdue'],
                commitment_fulfillment_rate=commitments_metrics['fulfillment_rate'],

                # Подозрительность
                suspicious_activity_score=fraud_metrics['suspicion_score'],
                red_flags_count=fraud_metrics['red_flags_count'],

                # Период
                period_start=period_start.isoformat(),
                period_end=period_end.isoformat(),
                calculated_at=datetime.utcnow().isoformat()
            )

            return asdict(kpi)

        except Exception as e:
            logger.error(f"Failed to get manager KPI: {e}", manager_id=manager_id)
            return {'error': str(e)}

    async def get_team_comparison(self, period_days: int = 7) -> List[Dict]:
        """
        Получить сравнение всех менеджеров

        Args:
            period_days: Период в днях

        Returns:
            List с KPI всех менеджеров
        """
        logger.info("Getting team comparison", period_days=period_days)

        try:
            # Получить всех менеджеров
            async with db_manager.get_session() as session:
                from ..database.crud import ManagerCRUD
                managers = await ManagerCRUD.get_active_managers(session)

            # Получить KPI для каждого
            team_kpi = []
            for manager in managers:
                kpi = await self.get_manager_kpi(manager.id, period_days)
                if 'error' not in kpi:
                    team_kpi.append(kpi)

            # Сортировать по качеству
            team_kpi.sort(key=lambda x: x['avg_quality_score'], reverse=True)

            return team_kpi

        except Exception as e:
            logger.error(f"Failed to get team comparison: {e}")
            return []

    async def get_leaderboard(self, period_days: int = 7, metric: str = 'quality') -> List[Dict]:
        """
        Получить рейтинг менеджеров

        Args:
            period_days: Период
            metric: Метрика для рейтинга (quality, activity, commitments)

        Returns:
            Отсортированный список менеджеров
        """

        team_kpi = await self.get_team_comparison(period_days)

        # Сортировать по выбранной метрике
        if metric == 'quality':
            team_kpi.sort(key=lambda x: x['avg_quality_score'], reverse=True)
        elif metric == 'activity':
            team_kpi.sort(key=lambda x: x['calls_made'], reverse=True)
        elif metric == 'commitments':
            team_kpi.sort(key=lambda x: x['commitment_fulfillment_rate'], reverse=True)

        # Добавить позицию
        for i, kpi in enumerate(team_kpi, 1):
            kpi['position'] = i

        return team_kpi

    async def get_alerts(self) -> List[Dict]:
        """
        Получить алерты по проблемам

        Returns:
            List с алертами
        """
        alerts = []

        try:
            # Получить всех менеджеров
            async with db_manager.get_session() as session:
                from ..database.crud import ManagerCRUD
                managers = await ManagerCRUD.get_active_managers(session)

            for manager in managers:
                kpi = await self.get_manager_kpi(manager.id, period_days=7)

                if 'error' in kpi:
                    continue

                # Проверки для алертов
                # 1. Низкое качество
                if kpi['avg_quality_score'] < 60 and kpi['calls_with_quality_score'] > 5:
                    alerts.append({
                        'type': 'low_quality',
                        'severity': 'high',
                        'manager_id': manager.id,
                        'manager_name': manager.name,
                        'message': f"Низкое качество звонков: {kpi['avg_quality_score']:.1f}/100",
                        'value': kpi['avg_quality_score']
                    })

                # 2. Много просроченных обещаний
                if kpi['overdue_commitments'] > 3:
                    alerts.append({
                        'type': 'overdue_commitments',
                        'severity': 'medium',
                        'manager_id': manager.id,
                        'manager_name': manager.name,
                        'message': f"Просрочено обещаний: {kpi['overdue_commitments']}",
                        'value': kpi['overdue_commitments']
                    })

                # 3. Подозрительная активность
                if kpi['suspicious_activity_score'] > 0.5:
                    alerts.append({
                        'type': 'suspicious_activity',
                        'severity': 'high',
                        'manager_id': manager.id,
                        'manager_name': manager.name,
                        'message': f"Подозрительная активность (красных флагов: {kpi['red_flags_count']})",
                        'value': kpi['suspicious_activity_score']
                    })

                # 4. Нет активности
                if kpi['calls_made'] == 0:
                    alerts.append({
                        'type': 'no_activity',
                        'severity': 'high',
                        'manager_id': manager.id,
                        'manager_name': manager.name,
                        'message': "Нет звонков за последние 7 дней",
                        'value': 0
                    })

            # Сортировать по severity
            severity_order = {'high': 0, 'medium': 1, 'low': 2}
            alerts.sort(key=lambda x: severity_order[x['severity']])

            return alerts

        except Exception as e:
            logger.error(f"Failed to get alerts: {e}")
            return []

    async def _get_calls_metrics(
        self,
        manager_id: int,
        from_date: datetime,
        to_date: datetime
    ) -> Dict:
        """Получить метрики по звонкам"""

        async with db_manager.get_session() as session:
            from sqlalchemy import select, and_, func
            from ..database.models import Call

            # Все звонки за период
            stmt = select(Call).where(
                and_(
                    Call.manager_id == manager_id,
                    Call.created_at >= from_date,
                    Call.created_at <= to_date
                )
            )

            result = await session.execute(stmt)
            calls = list(result.scalars().all())

            total_calls = len(calls)
            answered_calls = len([c for c in calls if c.duration and c.duration > 5])

            durations = [c.duration for c in calls if c.duration]
            avg_duration = int(sum(durations) / len(durations)) if durations else 0

            return {
                'total_calls': total_calls,
                'answered_calls': answered_calls,
                'avg_duration': avg_duration,
                'avg_response_time': 0  # TODO: вычислить из времени между звонками
            }

    async def _get_quality_metrics(
        self,
        manager_id: int,
        from_date: datetime,
        to_date: datetime
    ) -> Dict:
        """Получить метрики качества"""

        async with db_manager.get_session() as session:
            from sqlalchemy import select, and_
            from ..database.models import Call

            # Звонки с оценкой качества
            stmt = select(Call).where(
                and_(
                    Call.manager_id == manager_id,
                    Call.created_at >= from_date,
                    Call.created_at <= to_date,
                    Call.quality_score != None
                )
            )

            result = await session.execute(stmt)
            calls_with_score = list(result.scalars().all())

            if not calls_with_score:
                return {
                    'avg_score': 0,
                    'scored_calls': 0
                }

            avg_score = sum(c.quality_score for c in calls_with_score) / len(calls_with_score)

            return {
                'avg_score': round(avg_score, 1),
                'scored_calls': len(calls_with_score)
            }

    async def _get_commitments_metrics(
        self,
        manager_id: int,
        from_date: datetime,
        to_date: datetime
    ) -> Dict:
        """Получить метрики по обещаниям"""

        async with db_manager.get_session() as session:
            from sqlalchemy import select, and_
            from ..analysis.commitment_tracker import Commitment

            # Все обещания за период
            stmt = select(Commitment).where(
                and_(
                    Commitment.manager_id == manager_id,
                    Commitment.created_at >= from_date,
                    Commitment.created_at <= to_date
                )
            )

            result = await session.execute(stmt)
            commitments = list(result.scalars().all())

            total = len(commitments)
            fulfilled = len([c for c in commitments if c.is_fulfilled])
            overdue = len([c for c in commitments if c.is_overdue and not c.is_fulfilled])

            fulfillment_rate = (fulfilled / total * 100) if total > 0 else 0

            return {
                'total': total,
                'fulfilled': fulfilled,
                'overdue': overdue,
                'fulfillment_rate': round(fulfillment_rate, 1)
            }

    async def _get_fraud_metrics(self, manager_id: int, period_days: int) -> Dict:
        """Получить метрики подозрительности"""

        from ..fraud.activity_validator import activity_validator

        result = await activity_validator.detect_suspicious_activity(manager_id, period_days)

        if 'error' in result:
            return {
                'suspicion_score': 0,
                'red_flags_count': 0
            }

        return {
            'suspicion_score': result.get('confidence', 0),
            'red_flags_count': result.get('red_flags_count', 0)
        }

    async def generate_daily_report(self) -> Dict:
        """
        Генерировать ежедневный отчет для руководителя

        Returns:
            Dict с summary за день
        """

        today = datetime.utcnow().date()
        yesterday = today - timedelta(days=1)

        # Получить метрики команды за вчера
        team_kpi = await self.get_team_comparison(period_days=1)

        # Агрегировать
        total_calls = sum(kpi['calls_made'] for kpi in team_kpi)
        avg_quality = sum(kpi['avg_quality_score'] for kpi in team_kpi) / len(team_kpi) if team_kpi else 0

        # Топ-3 менеджера
        top_performers = sorted(team_kpi, key=lambda x: x['avg_quality_score'], reverse=True)[:3]

        # Проблемы
        alerts = await self.get_alerts()
        high_priority_alerts = [a for a in alerts if a['severity'] == 'high']

        return {
            'date': yesterday.isoformat(),
            'team_size': len(team_kpi),
            'total_calls': total_calls,
            'avg_quality_score': round(avg_quality, 1),
            'top_performers': [
                {
                    'name': p['manager_name'],
                    'score': p['avg_quality_score']
                }
                for p in top_performers
            ],
            'alerts_count': len(alerts),
            'high_priority_alerts': high_priority_alerts,
            'generated_at': datetime.utcnow().isoformat()
        }


# Global instance
manager_dashboard = ManagerDashboard()
