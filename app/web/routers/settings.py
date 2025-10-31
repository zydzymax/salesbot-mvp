"""
Settings Router - Управление настройками и мониторингом
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import List, Optional
from pathlib import Path

from ...database.init_db import db_manager
from ...database.models import Manager, AlertSettings
from sqlalchemy import select, update

router = APIRouter(prefix="/settings", tags=["settings"])

# Setup templates
templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


class ManagerMonitoringUpdate(BaseModel):
    """Update monitoring status for managers"""
    manager_ids: List[int]


class AlertSettingsUpdate(BaseModel):
    """Update alert settings"""
    min_quality_score: Optional[int] = None
    min_call_duration: Optional[int] = None
    max_call_duration: Optional[int] = None
    max_response_time_hours: Optional[int] = None
    alert_keywords: Optional[List[str]] = None
    notify_on_low_quality: Optional[bool] = None
    notify_on_missed_commitment: Optional[bool] = None
    notify_on_keywords: Optional[bool] = None
    send_daily_digest: Optional[bool] = None
    digest_time: Optional[str] = None
    working_hours_start: Optional[str] = None
    working_hours_end: Optional[str] = None


@router.get("/", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Страница настроек"""

    async with db_manager.get_session() as session:
        # Получить всех менеджеров
        managers_result = await session.execute(
            select(Manager).where(Manager.is_active == True).order_by(Manager.name)
        )
        managers = managers_result.scalars().all()

        # Получить настройки алертов
        alert_settings_result = await session.execute(
            select(AlertSettings).limit(1)
        )
        alert_settings = alert_settings_result.scalar_one_or_none()

        # Если настроек нет, создать дефолтные
        if not alert_settings:
            alert_settings = AlertSettings(id=1)
            session.add(alert_settings)
            await session.commit()

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "managers": managers,
            "alert_settings": alert_settings
        }
    )


@router.post("/managers/monitoring")
async def update_manager_monitoring(data: ManagerMonitoringUpdate):
    """Обновить список мониторируемых менеджеров"""

    async with db_manager.get_session() as session:
        # Сначала отключить мониторинг для всех
        await session.execute(
            update(Manager).values(is_monitored=False)
        )

        # Включить для выбранных
        if data.manager_ids:
            await session.execute(
                update(Manager)
                .where(Manager.id.in_(data.manager_ids))
                .values(is_monitored=True)
            )

        await session.commit()

    return {"status": "success", "monitored_count": len(data.manager_ids)}


@router.get("/managers")
async def get_managers():
    """Получить список менеджеров с их статусами"""

    async with db_manager.get_session() as session:
        result = await session.execute(
            select(Manager).where(Manager.is_active == True).order_by(Manager.name)
        )
        managers = result.scalars().all()

        return {
            "managers": [
                {
                    "id": m.id,
                    "name": m.name,
                    "is_monitored": m.is_monitored,
                    "email": m.email
                }
                for m in managers
            ]
        }


@router.get("/alerts")
async def get_alert_settings():
    """Получить текущие настройки алертов"""

    async with db_manager.get_session() as session:
        result = await session.execute(select(AlertSettings).limit(1))
        settings = result.scalar_one_or_none()

        if not settings:
            # Создать дефолтные настройки
            settings = AlertSettings(id=1)
            session.add(settings)
            await session.commit()
            await session.refresh(settings)

        return {
            "min_quality_score": settings.min_quality_score,
            "min_call_duration": settings.min_call_duration,
            "max_call_duration": settings.max_call_duration,
            "max_response_time_hours": settings.max_response_time_hours,
            "alert_keywords": settings.alert_keywords or [],
            "notify_on_low_quality": settings.notify_on_low_quality,
            "notify_on_missed_commitment": settings.notify_on_missed_commitment,
            "notify_on_keywords": settings.notify_on_keywords,
            "send_daily_digest": settings.send_daily_digest,
            "digest_time": settings.digest_time,
            "working_hours_start": settings.working_hours_start,
            "working_hours_end": settings.working_hours_end,
        }


@router.post("/alerts")
async def update_alert_settings(data: AlertSettingsUpdate):
    """Обновить настройки алертов"""

    async with db_manager.get_session() as session:
        result = await session.execute(select(AlertSettings).limit(1))
        settings = result.scalar_one_or_none()

        if not settings:
            settings = AlertSettings(id=1)
            session.add(settings)

        # Обновить только переданные поля
        update_data = data.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(settings, field, value)

        await session.commit()
        await session.refresh(settings)

    return {"status": "success", "settings": update_data}
