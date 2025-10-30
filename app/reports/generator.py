"""
Report generation engine
Creates various types of reports with statistics and analytics
"""

from datetime import datetime, timedelta, date
from typing import Dict, Any, List, Optional
import json

import structlog

from ..database.init_db import db_manager
from ..database.crud import CallCRUD, ManagerCRUD
from ..database.models import AnalysisStatus
from ..utils.helpers import format_duration, calculate_call_score

logger = structlog.get_logger("salesbot.reports.generator")


class ReportGenerator:
    """Generate various types of reports"""
    
    def __init__(self):
        pass
    
    async def generate_daily_report(
        self,
        manager_id: Optional[int] = None,
        report_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """Generate daily report for manager or all managers"""
        
        if report_date is None:
            report_date = datetime.now().date()
        
        logger.info(f"Generating daily report", manager_id=manager_id, date=report_date)
        
        # Date range for the day
        date_from = datetime.combine(report_date, datetime.min.time())
        date_to = date_from + timedelta(days=1)
        
        async with db_manager.get_session() as session:
            if manager_id:
                # Single manager report
                manager = await ManagerCRUD.get_manager_by_amocrm_id(session, str(manager_id))
                if not manager:
                    return {"error": "Manager not found"}
                
                calls = await CallCRUD.get_manager_calls(
                    session, manager_id, date_from, date_to
                )
                
                report_data = await self._calculate_manager_stats(calls, manager)
                report_data["manager_name"] = manager.name
                
            else:
                # All managers report
                managers = await ManagerCRUD.get_active_managers(session)
                all_calls = []
                
                for manager in managers:
                    manager_calls = await CallCRUD.get_manager_calls(
                        session, manager.id, date_from, date_to
                    )
                    all_calls.extend(manager_calls)
                
                report_data = await self._calculate_team_stats(all_calls, managers)
            
            report_data.update({
                "report_type": "daily",
                "date": report_date.isoformat(),
                "date_formatted": report_date.strftime("%d.%m.%Y"),
                "generated_at": datetime.utcnow().isoformat()
            })
            
            return report_data
    
    async def generate_weekly_report(
        self,
        manager_id: Optional[int] = None,
        week_start: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Generate weekly report"""
        
        if week_start is None:
            # Start of current week (Monday)
            today = datetime.now()
            week_start = today - timedelta(days=today.weekday())
            week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        
        week_end = week_start + timedelta(days=7)
        
        logger.info(f"Generating weekly report", manager_id=manager_id, week_start=week_start)
        
        async with db_manager.get_session() as session:
            if manager_id:
                # Single manager weekly report
                calls = await CallCRUD.get_manager_calls(
                    session, manager_id, week_start, week_end
                )
                
                # Get daily breakdown
                daily_stats = []
                for i in range(7):
                    day_start = week_start + timedelta(days=i)
                    day_end = day_start + timedelta(days=1)
                    
                    day_calls = [
                        call for call in calls 
                        if day_start <= call.created_at < day_end
                    ]
                    
                    daily_stats.append({
                        "date": day_start.strftime("%d.%m"),
                        "weekday": day_start.strftime("%a"),
                        "calls": len(day_calls),
                        "analyzed": sum(1 for call in day_calls if call.analysis_result),
                        "avg_score": self._calculate_average_score(day_calls)
                    })
                
                report_data = await self._calculate_manager_stats(calls)
                report_data["daily_stats"] = daily_stats
                
            else:
                # Team weekly report
                managers = await ManagerCRUD.get_active_managers(session)
                manager_stats = []
                
                for manager in managers:
                    manager_calls = await CallCRUD.get_manager_calls(
                        session, manager.id, week_start, week_end
                    )
                    
                    manager_data = await self._calculate_manager_stats(manager_calls, manager)
                    manager_data["manager_name"] = manager.name
                    manager_stats.append(manager_data)
                
                # Sort by performance
                manager_stats.sort(key=lambda x: x.get("average_score", 0), reverse=True)
                
                report_data = {
                    "managers": manager_stats,
                    "team_summary": await self._calculate_team_summary(manager_stats)
                }
            
            report_data.update({
                "report_type": "weekly",
                "week_start": week_start.date().isoformat(),
                "week_end": (week_end - timedelta(days=1)).date().isoformat(),
                "week_start_formatted": week_start.strftime("%d.%m.%Y"),
                "week_end_formatted": (week_end - timedelta(days=1)).strftime("%d.%m.%Y"),
                "generated_at": datetime.utcnow().isoformat()
            })
            
            return report_data
    
    async def generate_manager_performance_report(
        self,
        manager_id: int,
        period_days: int = 30
    ) -> Dict[str, Any]:
        """Generate detailed manager performance report"""
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=period_days)
        
        logger.info(f"Generating performance report", manager_id=manager_id, period=period_days)
        
        async with db_manager.get_session() as session:
            manager = await ManagerCRUD.get_manager_by_amocrm_id(session, str(manager_id))
            if not manager:
                return {"error": "Manager not found"}
            
            calls = await CallCRUD.get_manager_calls(
                session, manager_id, start_date, end_date
            )
            
            # Detailed analysis
            analyzed_calls = [call for call in calls if call.analysis_result]
            
            performance_data = {
                "manager_name": manager.name,
                "period_days": period_days,
                "total_calls": len(calls),
                "analyzed_calls": len(analyzed_calls),
                "analysis_coverage": len(analyzed_calls) / len(calls) * 100 if calls else 0,
                
                # Performance metrics
                "average_score": self._calculate_average_score(analyzed_calls),
                "score_trend": await self._calculate_score_trend(analyzed_calls),
                "best_calls": await self._get_best_calls(analyzed_calls, limit=5),
                "worst_calls": await self._get_worst_calls(analyzed_calls, limit=3),
                
                # Skill breakdown
                "skill_scores": await self._calculate_skill_scores(analyzed_calls),
                "improvement_areas": await self._identify_improvement_areas(analyzed_calls),
                "strengths": await self._identify_strengths(analyzed_calls),
                
                # Activity patterns
                "daily_activity": await self._calculate_daily_activity(calls),
                "call_duration_stats": await self._calculate_duration_stats(calls),
            }
            
            return performance_data
    
    async def _calculate_manager_stats(
        self,
        calls: List[Any],
        manager: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Calculate statistics for a manager's calls"""
        
        total_calls = len(calls)
        analyzed_calls = [call for call in calls if call.analysis_result]
        
        if not analyzed_calls:
            return {
                "total_calls": total_calls,
                "analyzed_calls": 0,
                "average_score": 0,
                "top_score": 0,
                "bottom_score": 0,
                "total_duration": 0,
                "avg_duration": 0
            }
        
        scores = [
            call.analysis_result.get("overall_score", 0) 
            for call in analyzed_calls
        ]
        
        durations = [
            call.duration_seconds or 0 
            for call in calls if call.duration_seconds
        ]
        
        return {
            "total_calls": total_calls,
            "analyzed_calls": len(analyzed_calls),
            "average_score": sum(scores) / len(scores) if scores else 0,
            "top_score": max(scores) if scores else 0,
            "bottom_score": min(scores) if scores else 0,
            "total_duration": sum(durations),
            "avg_duration": sum(durations) / len(durations) if durations else 0,
            "top_calls": await self._get_best_calls(analyzed_calls, limit=3),
            "problem_calls": await self._get_worst_calls(analyzed_calls, limit=2),
            "common_strengths": await self._get_common_strengths(analyzed_calls),
            "common_weaknesses": await self._get_common_weaknesses(analyzed_calls)
        }
    
    async def _calculate_team_stats(
        self,
        all_calls: List[Any],
        managers: List[Any]
    ) -> Dict[str, Any]:
        """Calculate team-wide statistics"""
        
        team_stats = await self._calculate_manager_stats(all_calls)
        
        # Add team-specific metrics
        team_stats.update({
            "active_managers": len(managers),
            "calls_per_manager": len(all_calls) / len(managers) if managers else 0,
            "top_performers": await self._get_top_performers(all_calls, managers),
            "team_trends": await self._calculate_team_trends(all_calls)
        })
        
        return team_stats
    
    def _calculate_average_score(self, calls: List[Any]) -> float:
        """Calculate average score from calls"""
        if not calls:
            return 0.0
        
        scores = [
            call.analysis_result.get("overall_score", 0)
            for call in calls if call.analysis_result
        ]
        
        return sum(scores) / len(scores) if scores else 0.0
    
    async def _calculate_score_trend(self, calls: List[Any]) -> List[Dict[str, Any]]:
        """Calculate score trend over time"""
        if not calls:
            return []
        
        # Sort calls by date
        sorted_calls = sorted(calls, key=lambda x: x.created_at)
        
        # Group by day and calculate daily averages
        daily_scores = {}
        for call in sorted_calls:
            if not call.analysis_result:
                continue
                
            day = call.created_at.date()
            score = call.analysis_result.get("overall_score", 0)
            
            if day not in daily_scores:
                daily_scores[day] = []
            daily_scores[day].append(score)
        
        # Calculate daily averages
        trend_data = []
        for day, scores in sorted(daily_scores.items()):
            trend_data.append({
                "date": day.isoformat(),
                "average_score": sum(scores) / len(scores),
                "calls_count": len(scores)
            })
        
        return trend_data
    
    async def _get_best_calls(self, calls: List[Any], limit: int = 5) -> List[Dict[str, Any]]:
        """Get best performing calls"""
        if not calls:
            return []
        
        # Filter and sort by score
        scored_calls = [
            call for call in calls 
            if call.analysis_result and call.analysis_result.get("overall_score", 0) > 0
        ]
        
        scored_calls.sort(
            key=lambda x: x.analysis_result.get("overall_score", 0),
            reverse=True
        )
        
        best_calls = []
        for call in scored_calls[:limit]:
            best_calls.append({
                "call_id": call.amocrm_call_id,
                "client_phone": call.client_phone or "Неизвестен",
                "score": call.analysis_result.get("overall_score", 0),
                "date": call.created_at.strftime("%d.%m %H:%M"),
                "duration": format_duration(call.duration_seconds or 0),
                "summary": call.analysis_result.get("summary", "")[:100] + "..."
            })
        
        return best_calls
    
    async def _get_worst_calls(self, calls: List[Any], limit: int = 3) -> List[Dict[str, Any]]:
        """Get worst performing calls"""
        if not calls:
            return []
        
        # Filter and sort by score (ascending)
        scored_calls = [
            call for call in calls 
            if call.analysis_result and call.analysis_result.get("overall_score", 0) > 0
        ]
        
        scored_calls.sort(
            key=lambda x: x.analysis_result.get("overall_score", 0)
        )
        
        worst_calls = []
        for call in scored_calls[:limit]:
            worst_calls.append({
                "call_id": call.amocrm_call_id,
                "client_phone": call.client_phone or "Неизвестен",
                "score": call.analysis_result.get("overall_score", 0),
                "date": call.created_at.strftime("%d.%m %H:%M"),
                "issues": call.analysis_result.get("weaknesses", [])[:2]
            })
        
        return worst_calls
    
    async def _calculate_skill_scores(self, calls: List[Any]) -> Dict[str, float]:
        """Calculate average scores by skill category"""
        if not calls:
            return {}
        
        skill_totals = {}
        skill_counts = {}
        
        for call in calls:
            if not call.analysis_result or "scores" not in call.analysis_result:
                continue
            
            scores = call.analysis_result["scores"]
            for skill, score in scores.items():
                if skill not in skill_totals:
                    skill_totals[skill] = 0
                    skill_counts[skill] = 0
                
                skill_totals[skill] += score
                skill_counts[skill] += 1
        
        # Calculate averages
        skill_averages = {}
        for skill in skill_totals:
            skill_averages[skill] = skill_totals[skill] / skill_counts[skill]
        
        return skill_averages
    
    async def _identify_improvement_areas(self, calls: List[Any]) -> List[str]:
        """Identify common improvement areas"""
        if not calls:
            return []
        
        # Count weakness mentions
        weakness_counts = {}
        
        for call in calls:
            if not call.analysis_result:
                continue
            
            weaknesses = call.analysis_result.get("weaknesses", [])
            for weakness in weaknesses:
                weakness_counts[weakness] = weakness_counts.get(weakness, 0) + 1
        
        # Sort by frequency
        sorted_weaknesses = sorted(
            weakness_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        return [weakness for weakness, count in sorted_weaknesses[:5]]
    
    async def _identify_strengths(self, calls: List[Any]) -> List[str]:
        """Identify common strengths"""
        if not calls:
            return []
        
        # Count strength mentions
        strength_counts = {}
        
        for call in calls:
            if not call.analysis_result:
                continue
            
            strengths = call.analysis_result.get("strengths", [])
            for strength in strengths:
                strength_counts[strength] = strength_counts.get(strength, 0) + 1
        
        # Sort by frequency
        sorted_strengths = sorted(
            strength_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        return [strength for strength, count in sorted_strengths[:5]]
    
    async def _calculate_daily_activity(self, calls: List[Any]) -> Dict[str, int]:
        """Calculate calls by hour of day"""
        hourly_counts = {str(i): 0 for i in range(24)}
        
        for call in calls:
            hour = call.created_at.hour
            hourly_counts[str(hour)] += 1
        
        return hourly_counts
    
    async def _calculate_duration_stats(self, calls: List[Any]) -> Dict[str, Any]:
        """Calculate call duration statistics"""
        if not calls:
            return {"average": 0, "total": 0, "shortest": 0, "longest": 0}
        
        durations = [call.duration_seconds or 0 for call in calls if call.duration_seconds]
        
        if not durations:
            return {"average": 0, "total": 0, "shortest": 0, "longest": 0}
        
        return {
            "average": sum(durations) / len(durations),
            "total": sum(durations),
            "shortest": min(durations),
            "longest": max(durations),
            "median": sorted(durations)[len(durations) // 2]
        }
    
    async def _get_common_strengths(self, calls: List[Any]) -> List[str]:
        """Get most common strengths across calls"""
        return await self._identify_strengths(calls)
    
    async def _get_common_weaknesses(self, calls: List[Any]) -> List[str]:
        """Get most common weaknesses across calls"""
        return await self._identify_improvement_areas(calls)
    
    async def _get_top_performers(
        self,
        all_calls: List[Any],
        managers: List[Any]
    ) -> List[Dict[str, Any]]:
        """Get top performing managers"""
        manager_performance = []
        
        for manager in managers:
            manager_calls = [
                call for call in all_calls 
                if call.manager_id == manager.id
            ]
            
            avg_score = self._calculate_average_score(manager_calls)
            
            manager_performance.append({
                "name": manager.name,
                "calls": len(manager_calls),
                "average_score": avg_score
            })
        
        # Sort by average score
        manager_performance.sort(key=lambda x: x["average_score"], reverse=True)
        
        return manager_performance[:5]
    
    async def _calculate_team_trends(self, calls: List[Any]) -> Dict[str, Any]:
        """Calculate team performance trends"""
        if not calls:
            return {"trend": "stable", "change": 0}
        
        # Simple trend calculation (last 7 days vs previous 7 days)
        now = datetime.now()
        week_ago = now - timedelta(days=7)
        two_weeks_ago = now - timedelta(days=14)
        
        recent_calls = [
            call for call in calls 
            if call.created_at >= week_ago and call.analysis_result
        ]
        
        previous_calls = [
            call for call in calls 
            if two_weeks_ago <= call.created_at < week_ago and call.analysis_result
        ]
        
        recent_avg = self._calculate_average_score(recent_calls)
        previous_avg = self._calculate_average_score(previous_calls)
        
        change = recent_avg - previous_avg
        
        if change > 2:
            trend = "improving"
        elif change < -2:
            trend = "declining"
        else:
            trend = "stable"
        
        return {
            "trend": trend,
            "change": round(change, 1),
            "recent_average": round(recent_avg, 1),
            "previous_average": round(previous_avg, 1)
        }
    
    async def _calculate_team_summary(self, manager_stats: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate team summary from manager statistics"""
        if not manager_stats:
            return {}
        
        total_calls = sum(stat.get("total_calls", 0) for stat in manager_stats)
        total_analyzed = sum(stat.get("analyzed_calls", 0) for stat in manager_stats)
        
        avg_scores = [
            stat.get("average_score", 0) 
            for stat in manager_stats 
            if stat.get("average_score", 0) > 0
        ]
        
        return {
            "total_calls": total_calls,
            "total_analyzed": total_analyzed,
            "team_average": sum(avg_scores) / len(avg_scores) if avg_scores else 0,
            "best_performer": manager_stats[0]["manager_name"] if manager_stats else None,
            "calls_per_manager": total_calls / len(manager_stats) if manager_stats else 0
        }