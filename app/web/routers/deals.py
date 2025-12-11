"""
Deals Router - Просмотр сделок с анализом звонков
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from uuid import UUID
from pathlib import Path

from ...database.init_db import db_manager
from ...database.crud import CallCRUD, ManagerCRUD
from ...database.models import Call, Manager
from ...analysis.chat_analyzer import chat_analyzer

router = APIRouter(prefix="/deals", tags=["deals"])

# Setup templates
templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


@router.get("/", response_class=HTMLResponse)
async def deals_list(request: Request):
    """Список сделок со звонками, сгруппированных по менеджерам"""

    async with db_manager.get_session() as session:
        from sqlalchemy import select, func
        from collections import defaultdict

        # Получаем все звонки с группировкой по сделкам
        stmt = select(
            Call.amocrm_lead_id,
            Call.manager_id,
            func.count(Call.id).label('calls_count'),
            func.max(Call.created_at).label('last_call_date'),
            func.avg(Call.quality_score).label('avg_quality')
        ).where(
            Call.amocrm_lead_id.isnot(None)
        ).group_by(
            Call.amocrm_lead_id,
            Call.manager_id
        ).order_by(
            func.max(Call.created_at).desc()
        )

        result = await session.execute(stmt)
        deals = result.all()

        # Группируем сделки по менеджерам
        managers_deals = defaultdict(list)

        # Получаем названия сделок из AmoCRM пачкой
        from ...amocrm.client import amocrm_client
        lead_ids = list(set([deal.amocrm_lead_id for deal in deals]))

        # Получаем сделки пачками по 50
        leads_data = {}
        for i in range(0, len(lead_ids), 50):
            batch = lead_ids[i:i+50]
            try:
                response = await amocrm_client.get_leads(
                    limit=50,
                    filter_params={"filter[id][]": batch}
                )
                leads = response.get("_embedded", {}).get("leads", [])
                for lead in leads:
                    leads_data[str(lead["id"])] = lead.get("name", f"Сделка #{lead['id']}")
            except:
                # Если не удалось получить названия, используем ID
                for lead_id in batch:
                    leads_data[lead_id] = f"Сделка #{lead_id}"

        for deal in deals:
            manager = await ManagerCRUD.get_manager(session, deal.manager_id)

            if manager and manager.is_active:
                deal_data = {
                    'lead_id': deal.amocrm_lead_id,
                    'lead_name': leads_data.get(deal.amocrm_lead_id, f"Сделка #{deal.amocrm_lead_id}"),
                    'calls_count': deal.calls_count,
                    'last_call_date': deal.last_call_date,
                    'avg_quality': round(deal.avg_quality, 1) if deal.avg_quality else 0,
                }

                managers_deals[manager.name].append(deal_data)

    return templates.TemplateResponse(
        "deals_list.html",
        {
            "request": request,
            "managers_deals": dict(managers_deals)
        }
    )


@router.get("/{lead_id}", response_class=HTMLResponse)
async def deal_detail(request: Request, lead_id: str):
    """Детальный просмотр сделки с профессиональным анализом"""

    from ...amocrm.client import amocrm_client
    from ...services.deal_analysis import deal_analysis_service

    async with db_manager.get_session() as session:
        from sqlalchemy import select

        # Получаем все звонки по сделке
        stmt = select(Call).where(
            Call.amocrm_lead_id == lead_id
        ).order_by(
            Call.created_at.desc()
        )

        result = await session.execute(stmt)
        calls = list(result.scalars().all())

        if not calls:
            raise HTTPException(status_code=404, detail="Сделка не найдена")

        # Получаем менеджера
        manager = await ManagerCRUD.get_manager(session, calls[0].manager_id)

        # Получаем название сделки из AmoCRM
        lead_name = f"Сделка #{lead_id}"
        try:
            response = await amocrm_client.get_leads(
                limit=1,
                filter_params={"filter[id][]": [lead_id]}
            )
            leads = response.get("_embedded", {}).get("leads", [])
            if leads:
                lead_name = leads[0].get("name", lead_name)
        except:
            pass

        # Статистика
        total_calls = len(calls)
        transcribed_calls = [c for c in calls if c.transcription_text]
        analyzed_calls = [c for c in calls if c.quality_score is not None]

        avg_quality = sum(c.quality_score for c in analyzed_calls) / len(analyzed_calls) if analyzed_calls else 0
        avg_duration = sum(c.duration_seconds or 0 for c in calls) / len(calls) if calls else 0

        # ПРОФЕССИОНАЛЬНЫЙ АНАЛИЗ СДЕЛКИ
        deal_analysis = None
        if transcribed_calls:
            deal_analysis = await deal_analysis_service.analyze_deal(
                calls=calls,
                lead_name=lead_name,
                manager_name=manager.name if manager else 'Неизвестно'
            )

    return templates.TemplateResponse(
        "deal_detail.html",
        {
            "request": request,
            "lead_id": lead_id,
            "lead_name": lead_name,
            "manager_name": manager.name if manager else 'Неизвестно',
            "total_calls": total_calls,
            "transcribed_calls": len(transcribed_calls),
            "analyzed_calls": len(analyzed_calls),
            "avg_quality": round(avg_quality, 1),
            "avg_duration": round(avg_duration, 1),
            "calls": calls,
            "deal_analysis": deal_analysis  # Профессиональный анализ
        }
    )


@router.get("/{lead_id}/chat-analysis")
async def analyze_deal_chat(lead_id: str) -> Dict[str, Any]:
    """
    Анализ переписки по сделке

    Получает все сообщения (SMS, WhatsApp, email, чаты) из AmoCRM
    и анализирует качество коммуникации менеджера.
    """
    try:
        result = await chat_analyzer.analyze_deal_messages(
            lead_id=lead_id,
            include_calls=False  # Только переписка, без звонков
        )

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{lead_id}/chat-analysis")
async def analyze_custom_chat(
    lead_id: str,
    messages: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Анализ произвольной переписки

    Body: [
        {"text": "Текст сообщения", "direction": "in/out", "timestamp": 1234567890, "channel": "whatsapp"},
        ...
    ]
    """
    from ...amocrm.client import amocrm_client

    try:
        # Получить контекст сделки
        deal_context = None
        try:
            lead = await amocrm_client.get_lead(lead_id)
            if lead:
                deal_context = {
                    "budget": lead.get("price"),
                    "stage": lead.get("status_id"),
                    "product": lead.get("name")
                }
        except:
            pass

        result = await chat_analyzer.analyze_conversation(
            messages=messages,
            deal_context=deal_context
        )

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{lead_id}/calls/{call_id}/sentiment")
async def get_call_sentiment_dynamics(lead_id: str, call_id: str) -> Dict[str, Any]:
    """
    Получить анализ эмоциональной динамики звонка

    Детальный анализ изменения эмоций по ходу разговора:
    - Timeline эмоций клиента и менеджера
    - Ключевые изменения настроения
    - Поворотные точки
    - Рекомендации по эмоциональному интеллекту
    """
    from ...analysis.sentiment_analyzer import sentiment_dynamics_analyzer

    async with db_manager.get_session() as session:
        from sqlalchemy import select

        # Найти звонок
        stmt = select(Call).where(
            Call.amocrm_lead_id == lead_id,
            Call.amocrm_call_id == call_id
        )
        result = await session.execute(stmt)
        call = result.scalar_one_or_none()

        if not call:
            # Попробуем найти по UUID
            try:
                from uuid import UUID
                call_uuid = UUID(call_id)
                stmt = select(Call).where(Call.id == call_uuid)
                result = await session.execute(stmt)
                call = result.scalar_one_or_none()
            except:
                pass

        if not call:
            raise HTTPException(status_code=404, detail="Звонок не найден")

        if not call.transcription_text:
            raise HTTPException(
                status_code=400,
                detail="Транскрипция звонка отсутствует"
            )

        # Анализ эмоциональной динамики
        analysis = await sentiment_dynamics_analyzer.analyze_sentiment_dynamics(
            transcription=call.transcription_text,
            call_duration_seconds=call.duration_seconds
        )

        if not analysis:
            raise HTTPException(
                status_code=500,
                detail="Не удалось проанализировать эмоции"
            )

        return {
            "success": True,
            "call_id": str(call.id),
            "lead_id": lead_id,
            "duration_seconds": call.duration_seconds,
            "sentiment_dynamics": analysis.to_dict()
        }


@router.get("/{lead_id}/sentiment-summary")
async def get_deal_sentiment_summary(lead_id: str) -> Dict[str, Any]:
    """
    Получить сводку по эмоциям всех звонков по сделке
    """
    from ...analysis.sentiment_analyzer import sentiment_dynamics_analyzer

    async with db_manager.get_session() as session:
        from sqlalchemy import select

        # Получить все звонки по сделке
        stmt = select(Call).where(
            Call.amocrm_lead_id == lead_id,
            Call.transcription_text.isnot(None)
        ).order_by(Call.created_at.desc())

        result = await session.execute(stmt)
        calls = list(result.scalars().all())

        if not calls:
            return {
                "success": False,
                "error": "Нет звонков с транскрипцией",
                "calls_analyzed": 0
            }

        # Анализируем последние 5 звонков
        summaries = []
        for call in calls[:5]:
            summary = await sentiment_dynamics_analyzer.get_emotion_summary(
                call.transcription_text
            )
            summaries.append({
                "call_id": str(call.id),
                "call_date": call.created_at.isoformat() if call.created_at else None,
                "duration": call.duration_seconds,
                **summary
            })

        # Агрегированные метрики
        avg_rapport = sum(s.get("rapport_score", 50) for s in summaries) / len(summaries)

        # Определить общий тренд
        trends = [s.get("trend") for s in summaries]
        if trends.count("improving") > len(trends) // 2:
            overall_trend = "improving"
        elif trends.count("declining") > len(trends) // 2:
            overall_trend = "declining"
        else:
            overall_trend = "stable"

        return {
            "success": True,
            "calls_analyzed": len(summaries),
            "call_summaries": summaries,
            "aggregate": {
                "avg_rapport_score": round(avg_rapport, 1),
                "overall_trend": overall_trend,
                "latest_client_sentiment": summaries[0].get("client_sentiment") if summaries else None
            }
        }


@router.get("/{lead_id}/suggest-tasks")
async def suggest_tasks_for_deal(lead_id: str) -> Dict[str, Any]:
    """
    Предложить задачи на основе анализа сделки

    Анализирует последний звонок и рекомендации, предлагает задачи
    без автоматического создания в AmoCRM
    """
    from ...services.task_creator import ai_task_creator

    async with db_manager.get_session() as session:
        from sqlalchemy import select

        # Получить последний проанализированный звонок
        stmt = select(Call).where(
            Call.amocrm_lead_id == lead_id,
            Call.analysis_result.isnot(None)
        ).order_by(Call.created_at.desc()).limit(1)

        result = await session.execute(stmt)
        call = result.scalar_one_or_none()

        if not call or not call.analysis_result:
            return {
                "success": False,
                "error": "Нет проанализированных звонков",
                "tasks": []
            }

        # Получить предложения задач
        suggested_tasks = await ai_task_creator.suggest_tasks(
            lead_id=lead_id,
            analysis_result=call.analysis_result
        )

        return {
            "success": True,
            "tasks": suggested_tasks,
            "source_call_id": str(call.id)
        }


@router.post("/{lead_id}/create-tasks")
async def create_tasks_for_deal(
    lead_id: str,
    task_indices: List[int] = None
) -> Dict[str, Any]:
    """
    Создать задачи в AmoCRM из рекомендаций

    Args:
        lead_id: ID сделки
        task_indices: Индексы задач для создания (если None - все)
    """
    from ...services.task_creator import ai_task_creator

    async with db_manager.get_session() as session:
        from sqlalchemy import select

        # Получить последний проанализированный звонок
        stmt = select(Call).where(
            Call.amocrm_lead_id == lead_id,
            Call.analysis_result.isnot(None)
        ).order_by(Call.created_at.desc()).limit(1)

        result = await session.execute(stmt)
        call = result.scalar_one_or_none()

        if not call:
            raise HTTPException(status_code=404, detail="Нет проанализированных звонков")

        if not call.manager_id:
            raise HTTPException(status_code=400, detail="Не указан менеджер для звонка")

        # Создать задачи
        created = await ai_task_creator.create_tasks_from_analysis(
            lead_id=lead_id,
            manager_id=call.manager_id,
            analysis_result=call.analysis_result,
            source="web_ui",
            auto_create=True
        )

        successful = [c for c in created if c.success]
        failed = [c for c in created if not c.success]

        return {
            "success": len(successful) > 0,
            "created_count": len(successful),
            "failed_count": len(failed),
            "tasks": [
                {
                    "title": c.task.title,
                    "type": c.task.task_type.value,
                    "deadline_days": c.task.deadline_days,
                    "success": c.success,
                    "error": c.error
                }
                for c in created
            ]
        }


@router.get("/{lead_id}/commitments")
async def get_deal_commitments(lead_id: str) -> Dict[str, Any]:
    """
    Получить обязательства по сделке

    Извлекает и анализирует все обязательства (обещания) из звонков:
    - Что клиент обещал сделать
    - Что менеджер обещал сделать
    - Сроки и статусы выполнения
    """
    from ...services.commitment_tracker import commitment_tracker

    try:
        summary = await commitment_tracker.get_deal_commitments(
            lead_id=lead_id,
            include_completed=False
        )

        return {
            "success": True,
            "lead_id": lead_id,
            "total_commitments": summary.total_commitments,
            "pending_count": summary.pending_count,
            "overdue_count": summary.overdue_count,
            "completed_count": summary.completed_count,
            "health_score": summary.health_score,
            "next_deadline": summary.next_deadline.isoformat() if summary.next_deadline else None,
            "client_commitments": summary.client_commitments,
            "manager_commitments": summary.manager_commitments
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "client_commitments": [],
            "manager_commitments": []
        }
