"""
Deal Prioritizer - Приоритизация сделок для РОПа
"Светофор" сделок: требуют внимания, в работе, всё ОК
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import structlog

from ..config import get_settings
from ..database.init_db import db_manager

logger = structlog.get_logger("salesbot.analytics.deal_prioritizer")


class DealPriority(str, Enum):
    """Приоритет сделки (светофор)"""
    CRITICAL = "critical"   # 🔴 Требует немедленного внимания
    WARNING = "warning"     # 🟡 Есть риски
    NORMAL = "normal"       # 🟢 Всё в порядке
    HOT = "hot"             # 🔥 Горячая - близка к закрытию


@dataclass
class DealAlert:
    """Алерт по сделке"""
    type: str
    message: str
    severity: str  # critical, warning, info


@dataclass
class PrioritizedDeal:
    """Сделка с приоритетом и алертами"""
    lead_id: str
    lead_name: str
    manager_id: int
    manager_name: str
    priority: DealPriority
    priority_score: int  # 0-100, чем выше - тем больше внимания
    budget: float
    stage: str
    days_in_stage: int
    last_activity_days: int
    calls_count: int
    avg_quality: float
    alerts: List[DealAlert]
    recommendations: List[str]
    client_sentiment: Optional[str]
    next_action: Optional[str]


class DealPrioritizer:
    """Сервис приоритизации сделок для РОПа"""

    # Пороги для алертов
    THRESHOLDS = {
        "days_without_activity": 3,      # Дней без активности
        "days_in_stage_warning": 7,      # Дней на одном этапе - предупреждение
        "days_in_stage_critical": 14,    # Дней на одном этапе - критично
        "low_quality_score": 50,         # Низкое качество звонков
        "min_calls_per_deal": 2,         # Минимум звонков на сделку
        "hot_deal_days_to_close": 7,     # Дней до закрытия для "горячей"
    }

    def __init__(self):
        self.settings = get_settings()

    async def get_prioritized_deals(
        self,
        manager_id: Optional[int] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Получить список сделок с приоритетами

        Args:
            manager_id: ID менеджера (None = все)
            limit: Максимум сделок

        Returns:
            Список сделок, отсортированных по приоритету
        """
        from ..amocrm.client import amocrm_client

        try:
            # Получить активные сделки из AmoCRM
            filter_params = {"filter[status_id]": "!143"}  # Не закрытые

            if manager_id:
                # Получить amocrm_user_id менеджера
                async with db_manager.get_session() as session:
                    from ..database.crud import ManagerCRUD
                    manager = await ManagerCRUD.get_manager(session, manager_id)
                    if manager and manager.amocrm_user_id:
                        filter_params["filter[responsible_user_id]"] = manager.amocrm_user_id

            response = await amocrm_client.get_leads(limit=limit, filter_params=filter_params)
            leads = response.get("_embedded", {}).get("leads", [])

            # Приоритизировать каждую сделку
            prioritized = []
            for lead in leads:
                deal = await self._analyze_deal(lead)
                if deal:
                    prioritized.append(deal)

            # Сортировать по приоритету (critical первые)
            priority_order = {
                DealPriority.CRITICAL: 0,
                DealPriority.HOT: 1,
                DealPriority.WARNING: 2,
                DealPriority.NORMAL: 3
            }

            prioritized.sort(key=lambda d: (
                priority_order.get(d["priority"], 99),
                -d["priority_score"]
            ))

            return prioritized

        except Exception as e:
            logger.error(f"Failed to get prioritized deals: {e}")
            return []

    async def _analyze_deal(self, lead: Dict) -> Optional[Dict[str, Any]]:
        """Анализировать сделку и определить приоритет"""
        try:
            lead_id = str(lead.get("id"))
            lead_name = lead.get("name", f"Сделка #{lead_id}")
            budget = lead.get("price", 0) or 0
            status_id = lead.get("status_id")
            responsible_user_id = lead.get("responsible_user_id")

            # Даты
            created_at = lead.get("created_at", 0)
            updated_at = lead.get("updated_at", 0)

            now = datetime.now().timestamp()
            days_since_update = int((now - updated_at) / 86400) if updated_at else 0
            days_since_created = int((now - created_at) / 86400) if created_at else 0

            # Получить данные о звонках по этой сделке
            calls_data = await self._get_deal_calls_data(lead_id)

            # Получить менеджера
            manager_name = "Неизвестно"
            manager_id = None
            if responsible_user_id:
                async with db_manager.get_session() as session:
                    from ..database.crud import ManagerCRUD
                    from sqlalchemy import select
                    from ..database.models import Manager

                    result = await session.execute(
                        select(Manager).where(Manager.amocrm_user_id == str(responsible_user_id))
                    )
                    manager = result.scalar_one_or_none()
                    if manager:
                        manager_name = manager.name
                        manager_id = manager.id

            # Определить этап
            stage = self._get_stage_name(status_id)

            # Анализ и алерты
            alerts = []
            recommendations = []
            priority_score = 50  # Базовый score

            # === ПРОВЕРКИ ===

            # 1. Давно без активности
            if days_since_update >= self.THRESHOLDS["days_without_activity"]:
                alerts.append(DealAlert(
                    type="no_activity",
                    message=f"Нет активности {days_since_update} дней",
                    severity="critical" if days_since_update >= 7 else "warning"
                ))
                priority_score += 20
                recommendations.append("Связаться с клиентом сегодня")

            # 2. Долго на одном этапе
            if days_since_update >= self.THRESHOLDS["days_in_stage_critical"]:
                alerts.append(DealAlert(
                    type="stuck",
                    message=f"Застряла на этапе {days_since_update} дней",
                    severity="critical"
                ))
                priority_score += 30
                recommendations.append("Проанализировать причину задержки")

            elif days_since_update >= self.THRESHOLDS["days_in_stage_warning"]:
                alerts.append(DealAlert(
                    type="slow_progress",
                    message=f"На этапе уже {days_since_update} дней",
                    severity="warning"
                ))
                priority_score += 15

            # 3. Мало звонков
            if calls_data["count"] < self.THRESHOLDS["min_calls_per_deal"]:
                alerts.append(DealAlert(
                    type="few_calls",
                    message=f"Мало звонков: {calls_data['count']}",
                    severity="warning"
                ))
                priority_score += 10
                recommendations.append("Увеличить количество касаний")

            # 4. Низкое качество звонков
            if calls_data["avg_quality"] > 0 and calls_data["avg_quality"] < self.THRESHOLDS["low_quality_score"]:
                alerts.append(DealAlert(
                    type="low_quality",
                    message=f"Низкое качество звонков: {calls_data['avg_quality']:.0f}/100",
                    severity="warning"
                ))
                priority_score += 15
                recommendations.append("Провести коучинг по звонкам")

            # 5. Большой бюджет
            if budget >= 100000:
                priority_score += 10
                if days_since_update >= 3:
                    alerts.append(DealAlert(
                        type="high_value_inactive",
                        message=f"Крупная сделка ({budget:,.0f} ₽) без активности",
                        severity="critical"
                    ))
                    priority_score += 20

            # 6. Негативный sentiment (если есть анализ)
            client_sentiment = calls_data.get("sentiment")
            if client_sentiment in ["negative", "hesitant"]:
                alerts.append(DealAlert(
                    type="negative_sentiment",
                    message=f"Клиент настроен негативно/сомневается",
                    severity="warning"
                ))
                priority_score += 15
                recommendations.append("Разобрать возражения клиента")

            # === ОПРЕДЕЛЕНИЕ ПРИОРИТЕТА ===

            # Критический
            critical_alerts = [a for a in alerts if a.severity == "critical"]
            warning_alerts = [a for a in alerts if a.severity == "warning"]

            if len(critical_alerts) >= 1:
                priority = DealPriority.CRITICAL
            elif len(warning_alerts) >= 2:
                priority = DealPriority.WARNING
            elif budget >= 200000 and days_since_update <= 3:
                priority = DealPriority.HOT
            else:
                priority = DealPriority.NORMAL

            # Определить следующее действие
            next_action = None
            if recommendations:
                next_action = recommendations[0]
            elif priority == DealPriority.HOT:
                next_action = "Подготовить коммерческое предложение"

            return {
                "lead_id": lead_id,
                "lead_name": lead_name,
                "manager_id": manager_id,
                "manager_name": manager_name,
                "priority": priority,
                "priority_score": min(100, priority_score),
                "budget": budget,
                "stage": stage,
                "days_in_stage": days_since_update,
                "last_activity_days": days_since_update,
                "calls_count": calls_data["count"],
                "avg_quality": calls_data["avg_quality"],
                "alerts": [{"type": a.type, "message": a.message, "severity": a.severity} for a in alerts],
                "recommendations": recommendations[:3],
                "client_sentiment": client_sentiment,
                "next_action": next_action
            }

        except Exception as e:
            logger.error(f"Failed to analyze deal {lead.get('id')}: {e}")
            return None

    async def _get_deal_calls_data(self, lead_id: str) -> Dict[str, Any]:
        """Получить данные о звонках по сделке"""
        try:
            async with db_manager.get_session() as session:
                from sqlalchemy import select, func
                from ..database.models import Call

                result = await session.execute(
                    select(
                        func.count(Call.id).label("count"),
                        func.avg(Call.quality_score).label("avg_quality")
                    ).where(Call.amocrm_lead_id == lead_id)
                )
                row = result.one_or_none()

                if row:
                    return {
                        "count": row.count or 0,
                        "avg_quality": float(row.avg_quality or 0),
                        "sentiment": None  # TODO: Get from last analysis
                    }

        except Exception as e:
            logger.error(f"Failed to get calls data for deal {lead_id}: {e}")

        return {"count": 0, "avg_quality": 0, "sentiment": None}

    def _get_stage_name(self, status_id: int) -> str:
        """Получить название этапа по ID"""
        # Стандартные этапы AmoCRM (могут отличаться)
        stages = {
            142: "Первичный контакт",
            143: "Закрыто",
            145: "Переговоры",
            146: "Принятие решения",
            147: "Подписание",
        }
        return stages.get(status_id, f"Этап {status_id}")

    async def get_summary_stats(self) -> Dict[str, Any]:
        """Получить сводную статистику для дашборда РОПа"""
        deals = await self.get_prioritized_deals(limit=100)

        if not deals:
            return {
                "total_deals": 0,
                "critical_count": 0,
                "warning_count": 0,
                "hot_count": 0,
                "normal_count": 0,
                "total_budget": 0,
                "avg_quality": 0,
                "deals_without_activity": 0,
                "by_manager": {}
            }

        # Подсчёт по приоритетам
        critical = [d for d in deals if d["priority"] == DealPriority.CRITICAL]
        warning = [d for d in deals if d["priority"] == DealPriority.WARNING]
        hot = [d for d in deals if d["priority"] == DealPriority.HOT]
        normal = [d for d in deals if d["priority"] == DealPriority.NORMAL]

        # По менеджерам
        by_manager = {}
        for deal in deals:
            name = deal["manager_name"]
            if name not in by_manager:
                by_manager[name] = {
                    "total": 0,
                    "critical": 0,
                    "warning": 0,
                    "hot": 0,
                    "budget": 0
                }
            by_manager[name]["total"] += 1
            by_manager[name]["budget"] += deal["budget"]
            if deal["priority"] == DealPriority.CRITICAL:
                by_manager[name]["critical"] += 1
            elif deal["priority"] == DealPriority.WARNING:
                by_manager[name]["warning"] += 1
            elif deal["priority"] == DealPriority.HOT:
                by_manager[name]["hot"] += 1

        # Общая статистика
        total_budget = sum(d["budget"] for d in deals)
        quality_scores = [d["avg_quality"] for d in deals if d["avg_quality"] > 0]
        avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0
        inactive = len([d for d in deals if d["last_activity_days"] >= 3])

        return {
            "total_deals": len(deals),
            "critical_count": len(critical),
            "warning_count": len(warning),
            "hot_count": len(hot),
            "normal_count": len(normal),
            "total_budget": total_budget,
            "avg_quality": round(avg_quality, 1),
            "deals_without_activity": inactive,
            "by_manager": by_manager
        }


# Global instance
deal_prioritizer = DealPrioritizer()
