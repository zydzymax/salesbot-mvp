"""
ROP Dashboard Router - Дашборд для руководителя отдела продаж
"""

from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
from pathlib import Path

from ...analytics.deal_prioritizer import deal_prioritizer, DealPriority
from ...database.init_db import db_manager
from ...database.crud import ManagerCRUD

router = APIRouter(prefix="/rop", tags=["rop-dashboard"])

# Setup templates
templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


@router.get("/", response_class=HTMLResponse)
async def rop_dashboard(
    request: Request,
    manager_id: Optional[int] = Query(None, description="Filter by manager")
):
    """
    Главный дашборд РОПа с приоритизацией сделок
    """
    # Получить сводную статистику
    summary = await deal_prioritizer.get_summary_stats()

    # Получить приоритизированные сделки
    deals = await deal_prioritizer.get_prioritized_deals(
        manager_id=manager_id,
        limit=50
    )

    # Получить список менеджеров для фильтра
    managers = []
    async with db_manager.get_session() as session:
        all_managers = await ManagerCRUD.get_all_managers(session, only_active=True)
        managers = [{"id": m.id, "name": m.name} for m in all_managers]

    # Конвертировать enum в строки для шаблона
    for deal in deals:
        if isinstance(deal.get("priority"), DealPriority):
            deal["priority"] = deal["priority"].value

    return templates.TemplateResponse(
        "rop_dashboard.html",
        {
            "request": request,
            "summary": summary,
            "deals": deals,
            "managers": managers,
            "selected_manager_id": manager_id,
            "DealPriority": {
                "CRITICAL": "critical",
                "WARNING": "warning",
                "NORMAL": "normal",
                "HOT": "hot"
            }
        }
    )


@router.get("/api/deals")
async def get_prioritized_deals(
    manager_id: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=200)
):
    """
    API: Получить приоритизированные сделки
    """
    deals = await deal_prioritizer.get_prioritized_deals(
        manager_id=manager_id,
        limit=limit
    )

    # Конвертировать enum
    for deal in deals:
        if isinstance(deal.get("priority"), DealPriority):
            deal["priority"] = deal["priority"].value

    return {"deals": deals, "count": len(deals)}


@router.get("/api/summary")
async def get_summary():
    """
    API: Получить сводную статистику
    """
    summary = await deal_prioritizer.get_summary_stats()
    return summary


@router.get("/api/manager/{manager_id}/deals")
async def get_manager_deals(manager_id: int, limit: int = Query(30, ge=1, le=100)):
    """
    API: Получить сделки конкретного менеджера
    """
    deals = await deal_prioritizer.get_prioritized_deals(
        manager_id=manager_id,
        limit=limit
    )

    for deal in deals:
        if isinstance(deal.get("priority"), DealPriority):
            deal["priority"] = deal["priority"].value

    return {"manager_id": manager_id, "deals": deals, "count": len(deals)}
