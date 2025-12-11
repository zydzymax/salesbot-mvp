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
