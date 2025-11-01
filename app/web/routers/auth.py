"""Auth Router - Регистрация и авторизация"""
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr
from pathlib import Path
from datetime import datetime, timedelta
import hashlib
import secrets

from ...database.init_db import db_manager
from ...database.models import User
from sqlalchemy import select

router = APIRouter(tags=["auth"])
templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

class RegisterData(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    company_name: str = ""

class LoginData(BaseModel):
    email: EmailStr
    password: str

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def create_session_token() -> str:
    return secrets.token_urlsafe(32)

@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@router.post("/register")
async def register(data: RegisterData):
    async with db_manager.get_session() as session:
        # Check if exists
        result = await session.execute(select(User).where(User.email == data.email))
        if result.scalar_one_or_none():
            raise HTTPException(400, "Email уже зарегистрирован")

        # Create user
        user = User(
            email=data.email,
            password_hash=hash_password(data.password),
            full_name=data.full_name,
            company_name=data.company_name,
            subscription_plan="trial",
            subscription_expires_at=datetime.utcnow() + timedelta(days=14)
        )
        session.add(user)
        await session.commit()

    return {"status": "success", "redirect": "/login"}

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@router.post("/login")
async def login(data: LoginData, response: Response):
    async with db_manager.get_session() as session:
        result = await session.execute(select(User).where(User.email == data.email))
        user = result.scalar_one_or_none()

        if not user or user.password_hash != hash_password(data.password):
            raise HTTPException(401, "Неверный email или пароль")

        if not user.is_active:
            raise HTTPException(403, "Аккаунт деактивирован")

        # Create session
        token = create_session_token()
        response.set_cookie("session_token", token, httponly=True, max_age=86400*30)

    return {"status": "success", "redirect": "/dashboard", "user_id": user.id}

@router.get("/logout")
async def logout(response: Response):
    response.delete_cookie("session_token")
    return RedirectResponse("/login")
