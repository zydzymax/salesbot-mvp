"""
Admin Dashboard Web Interface
Отображает метрики и аналитику по менеджерам
"""

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

from ...analytics.manager_dashboard import manager_dashboard
from ...database.init_db import db_manager
from ...database.crud import ManagerCRUD

router = APIRouter(prefix="/admin", tags=["admin"])

# Путь к шаблонам
templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


# Простая authentication (в продакшене использовать OAuth/JWT)
async def verify_admin(request: Request):
    """Проверка прав администратора"""
    # TODO: Реализовать проверку токена/сессии
    # Пока для демо - всегда True
    return True


@router.get("/", response_class=HTMLResponse)
async def admin_dashboard_page(
    request: Request,
    period: int = 7,
    is_admin: bool = Depends(verify_admin)
):
    """Главная страница админ-панели - список менеджеров со статистикой"""

    try:
        # Получить статистику всех менеджеров из AmoCRM + БД
        from ...services.manager_stats import manager_stats_service

        managers_stats = await manager_stats_service.get_all_managers_stats()

        # Общая статистика команды
        total_deals_in_progress = sum(m['deals_in_progress'] for m in managers_stats)
        total_deals_completed = sum(m['deals_completed_all_time'] for m in managers_stats)
        total_revenue = sum(m['revenue_all_time'] for m in managers_stats)
        total_calls_with_transcription = sum(m['calls_with_transcription'] for m in managers_stats)

        # Средняя оценка качества по команде
        quality_scores = [m['avg_quality_score'] for m in managers_stats if m['avg_quality_score'] > 0]
        avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0

        return templates.TemplateResponse("managers_list.html", {
            "request": request,
            "managers": managers_stats,
            "team_size": len(managers_stats),
            "total_deals_in_progress": total_deals_in_progress,
            "total_deals_completed": total_deals_completed,
            "total_revenue": total_revenue,
            "total_calls_with_transcription": total_calls_with_transcription,
            "avg_quality": round(avg_quality, 1),
            "now": datetime.now()
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/manager/{manager_id}", response_class=HTMLResponse)
async def manager_detail_page(
    request: Request,
    manager_id: int,
    period: int = 7,
    is_admin: bool = Depends(verify_admin)
):
    """Детальная страница менеджера со всеми его сделками"""

    try:
        from ...services.manager_stats import manager_stats_service

        # Получить менеджера из БД
        async with db_manager.get_session() as session:
            manager = await ManagerCRUD.get_manager(session, manager_id)

            if not manager:
                raise HTTPException(status_code=404, detail="Менеджер не найден")

        # Получить статистику менеджера
        manager_stats = await manager_stats_service.get_manager_stats(
            int(manager.amocrm_user_id),
            manager.name
        )

        # Получить все сделки менеджера
        deals = await manager_stats_service.get_manager_deals(
            int(manager.amocrm_user_id),
            include_closed=False  # Показываем только активные сделки
        )

        # Получить KPI для дополнительной информации
        kpi = await manager_dashboard.get_manager_kpi(manager_id, period)

        return templates.TemplateResponse("manager_detail.html", {
            "request": request,
            "manager": manager,
            "manager_stats": manager_stats,
            "deals": deals,
            "kpi": kpi if 'error' not in kpi else None,
            "period": period,
            "now": datetime.now()
        })

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/refresh-data")
async def refresh_dashboard_data(
    period: int = 7,
    is_admin: bool = Depends(verify_admin)
):
    """API для обновления данных дашборда (AJAX)"""

    try:
        team_comparison = await manager_dashboard.get_team_comparison(period_days=period)
        alerts = await manager_dashboard.get_alerts()

        return {
            "team_comparison": team_comparison,
            "alerts": alerts,
            "updated_at": datetime.now().isoformat()
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
