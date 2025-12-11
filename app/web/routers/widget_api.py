"""
Widget API Router - Backend endpoints for AmoCRM widget
Sales Whisper РОП - AI analysis for sales managers
"""

from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Header, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import structlog

from ...database.init_db import db_manager
from ...database.crud import CallCRUD, ManagerCRUD
from ...database.models import Call, Manager
from ...config import get_settings
from ...analytics.deal_prioritizer import deal_prioritizer, DealPriority
from ...services.commitment_tracker import commitment_tracker
from ...services.task_creator import ai_task_creator

logger = structlog.get_logger("salesbot.widget_api")

router = APIRouter(prefix="/widget", tags=["widget"])


# Request/Response models
class CreateTaskRequest(BaseModel):
    text: str
    deadline_days: int = 1


class AnalyzeRequest(BaseModel):
    force: bool = False


# API Key validation
async def verify_api_key(x_api_key: str = Header(None)):
    """Verify widget API key"""
    settings = get_settings()

    # In production, use proper API key validation
    # For now, accept any non-empty key or configured key
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key required")

    # You can add more sophisticated key validation here
    # For example, check against database of valid keys

    return x_api_key


@router.get("/health")
async def widget_health_check(api_key: str = Depends(verify_api_key)):
    """Health check endpoint for widget connection test"""
    return {
        "status": "ok",
        "service": "Sales Whisper РОП",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/lead/{lead_id}/analysis")
async def get_lead_analysis(
    lead_id: str,
    api_key: str = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Get comprehensive analysis for a lead/deal
    Returns: quality score, priority, recommendations, calls, commitments
    """
    try:
        async with db_manager.get_session() as session:
            from sqlalchemy import select, func

            # Get all calls for this lead
            stmt = select(Call).where(
                Call.amocrm_lead_id == lead_id
            ).order_by(Call.created_at.desc())

            result = await session.execute(stmt)
            calls = list(result.scalars().all())

            if not calls:
                return {
                    "success": True,
                    "lead_id": lead_id,
                    "quality_score": 0,
                    "priority": "normal",
                    "sentiment": "neutral",
                    "calls": [],
                    "analysis": None,
                    "recommendations": [],
                    "commitments": [],
                    "last_updated": None
                }

            # Calculate average quality score
            scored_calls = [c for c in calls if c.quality_score is not None]
            avg_quality = sum(c.quality_score for c in scored_calls) / len(scored_calls) if scored_calls else 0

            # Get priority from deal prioritizer
            priority_result = await deal_prioritizer.get_deal_priority(lead_id)
            priority = priority_result.get("priority", DealPriority.NORMAL)
            if isinstance(priority, DealPriority):
                priority = priority.value

            # Get latest analysis
            latest_analyzed = next((c for c in calls if c.analysis_result), None)
            analysis = latest_analyzed.analysis_result if latest_analyzed else None

            # Get sentiment from latest call
            sentiment = "neutral"
            if analysis:
                sentiment = analysis.get("client_sentiment", "neutral")

            # Format calls for widget
            formatted_calls = []
            for call in calls[:5]:  # Last 5 calls
                formatted_calls.append({
                    "id": str(call.id),
                    "amocrm_call_id": call.amocrm_call_id,
                    "quality_score": call.quality_score or 0,
                    "duration": _format_duration(call.duration_seconds),
                    "created_at": call.created_at.strftime("%d.%m.%Y %H:%M") if call.created_at else "",
                    "sentiment": call.analysis_result.get("client_sentiment", "neutral") if call.analysis_result else "neutral",
                    "has_transcription": bool(call.transcription_text)
                })

            # Get recommendations from analysis
            recommendations = []
            if analysis:
                raw_recs = analysis.get("recommendations", [])
                for i, rec in enumerate(raw_recs[:5]):
                    if isinstance(rec, str):
                        recommendations.append({
                            "title": rec,
                            "description": "",
                            "can_create_task": True,
                            "task_text": rec,
                            "deadline_days": 1 if i == 0 else 3
                        })
                    elif isinstance(rec, dict):
                        recommendations.append({
                            "title": rec.get("title", rec.get("action", "")),
                            "description": rec.get("description", ""),
                            "can_create_task": True,
                            "task_text": rec.get("title", rec.get("action", "")),
                            "deadline_days": rec.get("deadline_days", 1)
                        })

            # Get commitments
            commitments_data = []
            try:
                commitment_summary = await commitment_tracker.get_deal_commitments(lead_id)
                for c in commitment_summary.client_commitments[:3]:
                    commitments_data.append({
                        "owner": "client",
                        "description": c.get("description", ""),
                        "deadline": c.get("deadline_text", ""),
                        "is_overdue": c.get("status") == "overdue"
                    })
                for c in commitment_summary.manager_commitments[:3]:
                    commitments_data.append({
                        "owner": "manager",
                        "description": c.get("description", ""),
                        "deadline": c.get("deadline_text", ""),
                        "is_overdue": c.get("status") == "overdue"
                    })
            except Exception as e:
                logger.warning(f"Failed to get commitments: {e}")

            return {
                "success": True,
                "lead_id": lead_id,
                "quality_score": round(avg_quality),
                "priority": priority,
                "sentiment": sentiment,
                "calls": formatted_calls,
                "analysis": {
                    "summary": analysis.get("summary", "") if analysis else "",
                    "next_best_action": analysis.get("next_best_action", "") if analysis else "",
                    "strengths": analysis.get("strengths", []) if analysis else [],
                    "weaknesses": analysis.get("weaknesses", []) if analysis else []
                } if analysis else None,
                "recommendations": recommendations,
                "commitments": commitments_data,
                "last_updated": calls[0].updated_at.strftime("%d.%m.%Y %H:%M") if calls[0].updated_at else ""
            }

    except Exception as e:
        logger.error(f"Failed to get lead analysis: {e}", lead_id=lead_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/lead/{lead_id}/analyze")
async def trigger_lead_analysis(
    lead_id: str,
    request: AnalyzeRequest = None,
    api_key: str = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Trigger new analysis for a lead"""
    try:
        from ...tasks.queue import task_queue
        from ...tasks.workers import AnalyzeCallTask

        async with db_manager.get_session() as session:
            from sqlalchemy import select

            # Get latest call with transcription
            stmt = select(Call).where(
                Call.amocrm_lead_id == lead_id,
                Call.transcription_text.isnot(None)
            ).order_by(Call.created_at.desc()).limit(1)

            result = await session.execute(stmt)
            call = result.scalar_one_or_none()

            if not call:
                raise HTTPException(
                    status_code=404,
                    detail="No transcribed calls found for this lead"
                )

            # Queue analysis task
            analysis_task = AnalyzeCallTask(str(call.id))
            task_id = await task_queue.add_task(analysis_task.execute, priority=1)

            return {
                "success": True,
                "message": "Analysis queued",
                "task_id": task_id,
                "call_id": str(call.id)
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to trigger analysis: {e}", lead_id=lead_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/lead/{lead_id}/create-task")
async def create_task_from_widget(
    lead_id: str,
    request: CreateTaskRequest,
    api_key: str = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Create a task in AmoCRM from widget"""
    try:
        from ...amocrm.client import amocrm_client

        async with db_manager.get_session() as session:
            from sqlalchemy import select

            # Get manager for this lead from latest call
            stmt = select(Call).where(
                Call.amocrm_lead_id == lead_id
            ).order_by(Call.created_at.desc()).limit(1)

            result = await session.execute(stmt)
            call = result.scalar_one_or_none()

            if not call or not call.manager_id:
                raise HTTPException(status_code=404, detail="Manager not found for this lead")

            # Get manager's AmoCRM user ID
            manager = await ManagerCRUD.get_manager(session, call.manager_id)
            if not manager or not manager.amocrm_user_id:
                raise HTTPException(status_code=404, detail="Manager AmoCRM ID not found")

            # Calculate deadline
            deadline = datetime.now() + timedelta(days=request.deadline_days)
            deadline = deadline.replace(hour=18, minute=0, second=0)

            # Create task in AmoCRM
            task_text = f"📋 {request.text}\n\n🤖 Создано через Sales Whisper"

            success = await amocrm_client.add_task(
                responsible_user_id=manager.amocrm_user_id,
                text=task_text,
                complete_till=deadline,
                entity_id=lead_id,
                entity_type="leads"
            )

            if success:
                return {
                    "success": True,
                    "message": "Task created successfully"
                }
            else:
                raise HTTPException(status_code=500, detail="Failed to create task in AmoCRM")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create task: {e}", lead_id=lead_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/call/{call_id}/details")
async def get_call_details(
    call_id: str,
    api_key: str = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Get detailed call information for modal"""
    try:
        async with db_manager.get_session() as session:
            # Try UUID first, then AmoCRM ID
            call = None
            try:
                call_uuid = UUID(call_id)
                call = await CallCRUD.get_call_by_id(session, str(call_uuid))
            except ValueError:
                call = await CallCRUD.get_call_by_amocrm_id(session, call_id)

            if not call:
                raise HTTPException(status_code=404, detail="Call not found")

            analysis = call.analysis_result or {}

            # Build sentiment timeline from analysis if available
            sentiment_timeline = []
            if "sentiment_timeline" in analysis:
                sentiment_timeline = analysis["sentiment_timeline"]
            elif call.transcription_text:
                # Generate simple timeline
                lines = call.transcription_text.split('\n')
                chunk_size = max(1, len(lines) // 10)
                for i in range(0, len(lines), chunk_size):
                    sentiment_timeline.append({
                        "sentiment": "neutral",
                        "intensity": 50
                    })

            # Get scores
            scores = analysis.get("scores", {})

            # Get objections
            objections = analysis.get("objections", [])

            return {
                "success": True,
                "call": {
                    "id": str(call.id),
                    "amocrm_call_id": call.amocrm_call_id,
                    "duration": _format_duration(call.duration_seconds),
                    "created_at": call.created_at.strftime("%d.%m.%Y %H:%M") if call.created_at else ""
                },
                "transcription": call.transcription_text or "",
                "analysis": {
                    "summary": analysis.get("summary", ""),
                    "overall_score": analysis.get("overall_score", 0),
                    "strengths": analysis.get("strengths", []),
                    "weaknesses": analysis.get("weaknesses", [])
                },
                "scores": scores,
                "recommendations": analysis.get("recommendations", []),
                "objections": objections,
                "sentiment_timeline": sentiment_timeline
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get call details: {e}", call_id=call_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/contact/{contact_id}/history")
async def get_contact_history(
    contact_id: str,
    api_key: str = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Get call history for a contact"""
    try:
        async with db_manager.get_session() as session:
            from sqlalchemy import select, func

            # Get calls by contact (phone)
            # In real implementation, you'd look up contact's phone and match
            # For now, return aggregated data

            return {
                "success": True,
                "contact_id": contact_id,
                "total_calls": 0,
                "avg_quality": 0,
                "sentiment_history": [],
                "key_topics": []
            }

    except Exception as e:
        logger.error(f"Failed to get contact history: {e}", contact_id=contact_id)
        raise HTTPException(status_code=500, detail=str(e))


def _format_duration(seconds: Optional[int]) -> str:
    """Format duration in human readable format"""
    if not seconds:
        return "0:00"

    minutes = seconds // 60
    secs = seconds % 60

    if minutes >= 60:
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours}:{mins:02d}:{secs:02d}"

    return f"{minutes}:{secs:02d}"
