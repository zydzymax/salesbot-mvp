"""Dashboard Router - Личный кабинет клиента"""
from fastapi import APIRouter, Request, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

router = APIRouter(tags=["dashboard"])
templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, session_token: str = Cookie(None)):
    if not session_token:
        return RedirectResponse("/login")

    # Mock user data (в продакшене - из БД по токену)
    user = {
        "full_name": "Демо Пользователь",
        "email": "demo@example.com",
        "company_name": "Компания ООО",
        "subscription_plan": "trial",
        "subscription_expires": "14.11.2025",
        "calls_analyzed": 127,
        "avg_quality": 78,
        "managers_count": 3
    }

    return templates.TemplateResponse("dashboard.html", {"request": request, "user": user})
