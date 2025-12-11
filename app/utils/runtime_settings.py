"""
Runtime Settings Manager
Настройки, которые можно менять через админку без перезапуска
Сохраняются в Redis и JSON-файл
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
import structlog
import asyncio

logger = structlog.get_logger("salesbot.runtime_settings")

# Доступные модели OpenAI
AVAILABLE_MODELS = {
    "gpt-4o": {
        "name": "GPT-4o",
        "description": "Оптимальный баланс качества и скорости",
        "cost_per_1k_input": 0.0025,
        "cost_per_1k_output": 0.01,
        "recommended": True
    },
    "gpt-4o-mini": {
        "name": "GPT-4o Mini",
        "description": "Быстрый и экономичный для простых задач",
        "cost_per_1k_input": 0.00015,
        "cost_per_1k_output": 0.0006,
        "recommended": False
    },
    "gpt-4-turbo": {
        "name": "GPT-4 Turbo",
        "description": "Мощная модель с большим контекстом",
        "cost_per_1k_input": 0.01,
        "cost_per_1k_output": 0.03,
        "recommended": False
    },
    "o1": {
        "name": "o1 (Reasoning)",
        "description": "Продвинутый reasoning для сложных задач",
        "cost_per_1k_input": 0.015,
        "cost_per_1k_output": 0.06,
        "recommended": False
    },
    "o1-mini": {
        "name": "o1-mini",
        "description": "Быстрый reasoning",
        "cost_per_1k_input": 0.003,
        "cost_per_1k_output": 0.012,
        "recommended": False
    },
    "gpt-4.5-preview": {
        "name": "GPT-4.5 Preview",
        "description": "Новейшая preview-версия GPT-4.5",
        "cost_per_1k_input": 0.075,
        "cost_per_1k_output": 0.15,
        "recommended": False
    },
    "gpt-5.1": {
        "name": "GPT-5.1",
        "description": "Самая мощная модель OpenAI - максимальное качество анализа",
        "cost_per_1k_input": 0.02,
        "cost_per_1k_output": 0.08,
        "recommended": False,
        "premium": True
    }
}

# Дефолтные настройки
DEFAULT_SETTINGS = {
    "openai_model": "gpt-4o",
    "daily_budget_limit": 15.0,
    "monthly_budget_limit": 150.0,
    "auto_analysis_enabled": True,
    "notifications_enabled": True,
    "quality_threshold_alert": 60,  # Алерт если качество ниже
    "updated_at": None,
    "updated_by": None
}


class RuntimeSettingsManager:
    """Менеджер runtime-настроек с сохранением в файл и Redis"""

    def __init__(self, storage_path: str = "/root/salesbot-mvp/.cache/runtime_settings.json"):
        self.storage_path = Path(storage_path)
        self._settings: Dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self._redis_client = None

        # Ensure storage directory exists
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        # Load settings on init
        self._settings = self._load_from_file()

    def _load_from_file(self) -> Dict[str, Any]:
        """Загрузить настройки из файла"""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, 'r') as f:
                    saved = json.load(f)
                    # Merge with defaults (for new settings)
                    return {**DEFAULT_SETTINGS, **saved}
            except Exception as e:
                logger.error(f"Failed to load settings from file: {e}")

        return DEFAULT_SETTINGS.copy()

    def _save_to_file(self):
        """Сохранить настройки в файл"""
        try:
            with open(self.storage_path, 'w') as f:
                json.dump(self._settings, f, indent=2, default=str)
            logger.info("Settings saved to file")
        except Exception as e:
            logger.error(f"Failed to save settings to file: {e}")

    async def _get_redis(self):
        """Get Redis client"""
        if not self._redis_client:
            try:
                import aioredis
                from ..config import get_settings
                config = get_settings()
                self._redis_client = aioredis.from_url(
                    config.redis_url,
                    decode_responses=True
                )
                await self._redis_client.ping()
            except Exception as e:
                logger.warning(f"Redis not available: {e}")
                self._redis_client = None
        return self._redis_client

    async def get(self, key: str, default: Any = None) -> Any:
        """Получить значение настройки"""
        # Try Redis first for fresh data
        redis = await self._get_redis()
        if redis:
            try:
                value = await redis.hget("runtime_settings", key)
                if value is not None:
                    try:
                        return json.loads(value)
                    except:
                        return value
            except Exception as e:
                logger.warning(f"Redis get failed: {e}")

        # Fallback to local cache
        return self._settings.get(key, default)

    async def set(self, key: str, value: Any, updated_by: str = "system") -> bool:
        """Установить значение настройки"""
        async with self._lock:
            try:
                self._settings[key] = value
                self._settings["updated_at"] = datetime.now().isoformat()
                self._settings["updated_by"] = updated_by

                # Save to file
                self._save_to_file()

                # Save to Redis
                redis = await self._get_redis()
                if redis:
                    try:
                        await redis.hset("runtime_settings", key, json.dumps(value))
                        await redis.hset("runtime_settings", "updated_at", datetime.now().isoformat())
                    except Exception as e:
                        logger.warning(f"Redis set failed: {e}")

                logger.info(f"Setting updated: {key} = {value}", updated_by=updated_by)
                return True

            except Exception as e:
                logger.error(f"Failed to set setting {key}: {e}")
                return False

    async def get_all(self) -> Dict[str, Any]:
        """Получить все настройки"""
        return self._settings.copy()

    async def get_model(self) -> str:
        """Получить текущую модель OpenAI"""
        return await self.get("openai_model", "gpt-4o")

    async def set_model(self, model: str, updated_by: str = "admin") -> bool:
        """Установить модель OpenAI"""
        if model not in AVAILABLE_MODELS:
            logger.error(f"Invalid model: {model}")
            return False

        success = await self.set("openai_model", model, updated_by)

        if success:
            logger.info(f"OpenAI model changed to {model}", updated_by=updated_by)

        return success

    def get_available_models(self) -> Dict[str, Dict]:
        """Получить список доступных моделей"""
        return AVAILABLE_MODELS

    async def get_budget_limits(self) -> Dict[str, float]:
        """Получить лимиты бюджета"""
        return {
            "daily": await self.get("daily_budget_limit", 15.0),
            "monthly": await self.get("monthly_budget_limit", 150.0)
        }

    async def set_budget_limits(
        self,
        daily: Optional[float] = None,
        monthly: Optional[float] = None,
        updated_by: str = "admin"
    ) -> bool:
        """Установить лимиты бюджета"""
        success = True

        if daily is not None:
            success = success and await self.set("daily_budget_limit", daily, updated_by)

        if monthly is not None:
            success = success and await self.set("monthly_budget_limit", monthly, updated_by)

        # Update api_budget manager
        if success:
            from .api_budget import api_budget
            api_budget.set_limits(
                daily=daily or api_budget.daily_limit,
                monthly=monthly or api_budget.monthly_limit
            )

        return success

    async def export_settings(self) -> Dict[str, Any]:
        """Экспорт настроек для API/UI"""
        current_model = await self.get_model()
        budget_limits = await self.get_budget_limits()

        return {
            "current_model": current_model,
            "model_info": AVAILABLE_MODELS.get(current_model, {}),
            "available_models": AVAILABLE_MODELS,
            "budget_limits": budget_limits,
            "auto_analysis_enabled": await self.get("auto_analysis_enabled", True),
            "notifications_enabled": await self.get("notifications_enabled", True),
            "quality_threshold_alert": await self.get("quality_threshold_alert", 60),
            "updated_at": self._settings.get("updated_at"),
            "updated_by": self._settings.get("updated_by")
        }


# Global instance
runtime_settings = RuntimeSettingsManager()


async def get_current_model() -> str:
    """Быстрый доступ к текущей модели"""
    return await runtime_settings.get_model()
