"""
Deal Analysis Module - Sales Manager Perspective
Analyzes deals, communications, and provides coaching recommendations
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import structlog

from ..config import get_settings
from ..amocrm.client import amocrm_client
from .ai_coach import AICoach

logger = structlog.get_logger("salesbot.analysis.deal_analyzer")


class DealAnalyzer:
    """Analyze deals from sales manager perspective"""
    
    def __init__(self):
        self.settings = get_settings()
        self.ai_coach = AICoach()
    
    async def analyze_deal_comprehensive(
        self,
        deal_id: int,
        include_calls: bool = True,
        include_notes: bool = True,
        include_tasks: bool = True
    ) -> Dict[str, Any]:
        """
        Комплексный анализ сделки с точки зрения руководителя
        """
        logger.info(f"Starting comprehensive deal analysis", deal_id=deal_id)
        
        try:
            # 1. Получить данные о сделке
            deal_data = await self._get_deal_data(deal_id)
            if not deal_data:
                return {"error": "Deal not found"}
            
            # 2. Получить историю коммуникаций
            communications = await self._get_deal_communications(
                deal_id,
                include_calls=include_calls,
                include_notes=include_notes
            )
            
            # 3. Получить историю движения по воронке
            funnel_history = await self._get_funnel_history(deal_id)
            
            # 4. Получить задачи по сделке
            tasks = []
            if include_tasks:
                tasks = await self._get_deal_tasks(deal_id)
            
            # 5. Рассчитать метрики
            metrics = self._calculate_deal_metrics(
                deal_data, communications, funnel_history, tasks
            )
            
            # 6. AI анализ и рекомендации
            recommendations = await self.ai_coach.generate_coaching_feedback(
                deal_data=deal_data,
                communications=communications,
                funnel_history=funnel_history,
                tasks=tasks,
                metrics=metrics
            )
            
            result = {
                "deal_id": deal_id,
                "deal_name": deal_data.get("name"),
                "manager_id": deal_data.get("responsible_user_id"),
                "current_stage": deal_data.get("status_id"),
                "pipeline_id": deal_data.get("pipeline_id"),
                "budget": deal_data.get("price", 0),
                "created_at": deal_data.get("created_at"),
                "updated_at": deal_data.get("updated_at"),
                "metrics": metrics,
                "communications_summary": {
                    "total_calls": len([c for c in communications if c["type"] == "call"]),
                    "total_notes": len([c for c in communications if c["type"] == "note"]),
                    "last_contact": communications[0]["created_at"] if communications else None
                },
                "funnel_progress": funnel_history,
                "recommendations": recommendations,
                "analysis_timestamp": datetime.utcnow().isoformat()
            }
            
            logger.info(f"Deal analysis completed", deal_id=deal_id)
            return result
            
        except Exception as e:
            logger.error(f"Deal analysis failed", deal_id=deal_id, error=str(e))
            return {"error": str(e)}
    
    async def _get_deal_data(self, deal_id: int) -> Optional[Dict[str, Any]]:
        """Получить данные о сделке"""
        try:
            result = await amocrm_client._make_request("GET", f"leads/{deal_id}")
            return result
        except Exception as e:
            logger.error(f"Failed to get deal data", deal_id=deal_id, error=str(e))
            return None
    
    async def _get_deal_communications(
        self,
        deal_id: int,
        include_calls: bool = True,
        include_notes: bool = True
    ) -> List[Dict[str, Any]]:
        """Получить всю историю коммуникаций по сделке"""
        communications = []
        
        try:
            # Получить примечания (включая звонки)
            if include_notes:
                notes_result = await amocrm_client._make_request(
                    "GET",
                    f"leads/{deal_id}/notes",
                    params={"limit": 250}
                )
                
                notes = notes_result.get("_embedded", {}).get("notes", [])
                
                for note in notes:
                    note_type = note.get("note_type")
                    
                    comm = {
                        "id": note.get("id"),
                        "type": "call" if "call" in note_type else "note",
                        "note_type": note_type,
                        "created_at": note.get("created_at"),
                        "created_by": note.get("created_by"),
                        "params": note.get("params", {})
                    }
                    
                    # Для звонков добавить детали
                    if "call" in note_type:
                        comm["call_details"] = {
                            "duration": note.get("params", {}).get("duration", 0),
                            "phone": note.get("params", {}).get("phone"),
                            "recording_link": note.get("params", {}).get("link"),
                            "result": note.get("params", {}).get("call_result")
                        }
                    
                    communications.append(comm)
            
            # Сортировать по времени (новые первые)
            communications.sort(key=lambda x: x["created_at"], reverse=True)
            
        except Exception as e:
            logger.error(f"Failed to get communications", deal_id=deal_id, error=str(e))
        
        return communications
    
    async def _get_funnel_history(self, deal_id: int) -> List[Dict[str, Any]]:
        """Получить историю движения по воронке"""
        history = []
        
        try:
            # Получить события изменения статуса через Events API
            events_result = await amocrm_client._make_request(
                "GET",
                "events",
                params={
                    "filter[entity]": "lead",
                    "filter[entity_id]": deal_id,
                    "filter[type]": "lead_status_changed",
                    "limit": 100
                }
            )
            
            events = events_result.get("_embedded", {}).get("events", [])
            
            for event in events:
                value_before = event.get("value_before", [{}])[0] if event.get("value_before") else {}
                value_after = event.get("value_after", [{}])[0] if event.get("value_after") else {}
                
                history.append({
                    "event_id": event.get("id"),
                    "timestamp": event.get("created_at"),
                    "changed_by": event.get("created_by"),
                    "from_status": value_before.get("lead_status", {}).get("id"),
                    "to_status": value_after.get("lead_status", {}).get("id"),
                    "from_pipeline": value_before.get("lead_status", {}).get("pipeline_id"),
                    "to_pipeline": value_after.get("lead_status", {}).get("pipeline_id")
                })
            
            # Сортировать по времени
            history.sort(key=lambda x: x["timestamp"])
            
        except Exception as e:
            logger.error(f"Failed to get funnel history", deal_id=deal_id, error=str(e))
        
        return history
    
    async def _get_deal_tasks(self, deal_id: int) -> List[Dict[str, Any]]:
        """Получить задачи по сделке"""
        tasks = []
        
        try:
            tasks_result = await amocrm_client._make_request(
                "GET",
                "tasks",
                params={
                    "filter[entity_type]": "leads",
                    "filter[entity_id]": deal_id,
                    "limit": 100
                }
            )
            
            tasks = tasks_result.get("_embedded", {}).get("tasks", [])
            
        except Exception as e:
            logger.error(f"Failed to get tasks", deal_id=deal_id, error=str(e))
        
        return tasks
    
    def _calculate_deal_metrics(
        self,
        deal_data: Dict[str, Any],
        communications: List[Dict[str, Any]],
        funnel_history: List[Dict[str, Any]],
        tasks: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Рассчитать метрики по сделке"""
        
        now = datetime.utcnow().timestamp()
        created_at = deal_data.get("created_at", now)
        updated_at = deal_data.get("updated_at", now)
        
        # Время в работе
        deal_age_days = (now - created_at) / 86400
        days_since_update = (now - updated_at) / 86400
        
        # Количество касаний
        total_calls = len([c for c in communications if c["type"] == "call"])
        total_notes = len([c for c in communications if c["type"] == "note"])
        
        # Длительность звонков
        total_call_duration = sum([
            c.get("call_details", {}).get("duration", 0)
            for c in communications
            if c["type"] == "call"
        ])
        
        # Среднее время между касаниями
        if len(communications) > 1:
            time_diffs = []
            for i in range(len(communications) - 1):
                diff = communications[i]["created_at"] - communications[i+1]["created_at"]
                time_diffs.append(diff)
            avg_time_between_contacts = sum(time_diffs) / len(time_diffs) / 86400  # в днях
        else:
            avg_time_between_contacts = 0
        
        # Движение по воронке
        funnel_movements = len(funnel_history)
        time_in_current_stage = days_since_update
        
        # Задачи
        completed_tasks = len([t for t in tasks if t.get("is_completed")])
        overdue_tasks = len([t for t in tasks if not t.get("is_completed") and t.get("complete_till", 0) < now])
        
        return {
            "deal_age_days": round(deal_age_days, 1),
            "days_since_last_update": round(days_since_update, 1),
            "total_communications": len(communications),
            "total_calls": total_calls,
            "total_notes": total_notes,
            "total_call_duration_seconds": total_call_duration,
            "avg_time_between_contacts_days": round(avg_time_between_contacts, 1),
            "funnel_movements": funnel_movements,
            "time_in_current_stage_days": round(time_in_current_stage, 1),
            "total_tasks": len(tasks),
            "completed_tasks": completed_tasks,
            "overdue_tasks": overdue_tasks,
            "task_completion_rate": round(completed_tasks / len(tasks) * 100, 1) if tasks else 0
        }
    
    async def analyze_manager_deals(
        self,
        manager_id: int,
        status_filter: Optional[List[int]] = None,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        Анализ всех сделок менеджера
        """
        logger.info(f"Analyzing manager deals", manager_id=manager_id)
        
        try:
            # Получить сделки менеджера
            params = {
                "filter[responsible_user_id]": manager_id,
                "limit": limit
            }
            
            if status_filter:
                params["filter[statuses][]"] = status_filter
            
            deals_result = await amocrm_client._make_request("GET", "leads", params=params)
            deals = deals_result.get("_embedded", {}).get("leads", [])
            
            # Анализировать каждую сделку
            deal_analyses = []
            for deal in deals:
                analysis = await self.analyze_deal_comprehensive(deal["id"])
                deal_analyses.append(analysis)
            
            # Общая статистика
            total_budget = sum([d.get("budget", 0) for d in deal_analyses])
            avg_deal_age = sum([d.get("metrics", {}).get("deal_age_days", 0) for d in deal_analyses]) / len(deal_analyses) if deal_analyses else 0
            
            # Сделки требующие внимания
            attention_needed = [
                d for d in deal_analyses
                if d.get("metrics", {}).get("days_since_last_update", 0) > 3
                or d.get("metrics", {}).get("overdue_tasks", 0) > 0
            ]
            
            return {
                "manager_id": manager_id,
                "total_deals": len(deals),
                "total_budget": total_budget,
                "avg_deal_age_days": round(avg_deal_age, 1),
                "deals_needing_attention": len(attention_needed),
                "deal_analyses": deal_analyses,
                "attention_deals": attention_needed,
                "analysis_timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Manager deals analysis failed", manager_id=manager_id, error=str(e))
            return {"error": str(e)}


# Global instance
deal_analyzer = DealAnalyzer()
