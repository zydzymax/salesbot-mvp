"""
API Budget Protection System
Tracks OpenAI API costs and prevents budget overruns
"""

import json
from datetime import datetime, date
from typing import Dict, Any, Optional
from pathlib import Path
import structlog
import asyncio

logger = structlog.get_logger("salesbot.api_budget")

# Cost per 1K tokens (as of Dec 2024)
MODEL_COSTS = {
    # GPT-5 models (latest)
    "gpt-5": {"input": 0.01, "output": 0.03},
    "gpt-5-turbo": {"input": 0.005, "output": 0.015},
    "o1": {"input": 0.015, "output": 0.06},
    "o1-mini": {"input": 0.003, "output": 0.012},
    # GPT-4 models
    "gpt-4": {"input": 0.03, "output": 0.06},
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    # Legacy
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
}

# Default limits - higher for quality models
DEFAULT_DAILY_LIMIT_USD = 15.0  # $15 per day
DEFAULT_MONTHLY_LIMIT_USD = 150.0  # $150 per month
DEFAULT_PER_REQUEST_LIMIT_USD = 0.50  # $0.50 per request


class APIBudgetManager:
    """Manages API budget and prevents overruns"""

    def __init__(
        self,
        daily_limit: float = DEFAULT_DAILY_LIMIT_USD,
        monthly_limit: float = DEFAULT_MONTHLY_LIMIT_USD,
        per_request_limit: float = DEFAULT_PER_REQUEST_LIMIT_USD,
        storage_path: str = "/root/salesbot-mvp/.cache/api_budget.json"
    ):
        self.daily_limit = daily_limit
        self.monthly_limit = monthly_limit
        self.per_request_limit = per_request_limit
        self.storage_path = Path(storage_path)
        self._lock = asyncio.Lock()

        # Ensure storage directory exists
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing data
        self._data = self._load_data()

    def _load_data(self) -> Dict[str, Any]:
        """Load budget data from file"""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load budget data: {e}")

        return {
            "daily_costs": {},
            "monthly_costs": {},
            "total_requests": 0,
            "total_cost": 0.0,
            "last_reset": datetime.now().isoformat()
        }

    def _save_data(self):
        """Save budget data to file"""
        try:
            with open(self.storage_path, 'w') as f:
                json.dump(self._data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save budget data: {e}")

    def _get_today_key(self) -> str:
        return date.today().isoformat()

    def _get_month_key(self) -> str:
        return date.today().strftime("%Y-%m")

    def get_daily_cost(self) -> float:
        """Get today's total cost"""
        return self._data["daily_costs"].get(self._get_today_key(), 0.0)

    def get_monthly_cost(self) -> float:
        """Get this month's total cost"""
        return self._data["monthly_costs"].get(self._get_month_key(), 0.0)

    def can_make_request(self, estimated_cost: float = 0.0) -> tuple[bool, str]:
        """
        Check if a request can be made within budget
        Returns (allowed, reason)
        """
        daily_cost = self.get_daily_cost()
        monthly_cost = self.get_monthly_cost()

        # Check per-request limit
        if estimated_cost > self.per_request_limit:
            return False, f"Request cost ${estimated_cost:.4f} exceeds per-request limit ${self.per_request_limit:.2f}"

        # Check daily limit
        if daily_cost + estimated_cost > self.daily_limit:
            return False, f"Daily limit reached: ${daily_cost:.2f}/${self.daily_limit:.2f}"

        # Check monthly limit
        if monthly_cost + estimated_cost > self.monthly_limit:
            return False, f"Monthly limit reached: ${monthly_cost:.2f}/${self.monthly_limit:.2f}"

        return True, "OK"

    def estimate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int = 500  # Default estimate
    ) -> float:
        """Estimate cost for a request"""
        costs = MODEL_COSTS.get(model, MODEL_COSTS["gpt-4o-mini"])

        input_cost = (input_tokens / 1000) * costs["input"]
        output_cost = (output_tokens / 1000) * costs["output"]

        return input_cost + output_cost

    async def record_request(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        request_type: str = "analysis"
    ) -> float:
        """Record a completed request and its cost"""
        async with self._lock:
            cost = self.estimate_cost(model, input_tokens, output_tokens)

            today_key = self._get_today_key()
            month_key = self._get_month_key()

            # Update daily cost
            self._data["daily_costs"][today_key] = (
                self._data["daily_costs"].get(today_key, 0.0) + cost
            )

            # Update monthly cost
            self._data["monthly_costs"][month_key] = (
                self._data["monthly_costs"].get(month_key, 0.0) + cost
            )

            # Update totals
            self._data["total_requests"] += 1
            self._data["total_cost"] += cost

            # Save
            self._save_data()

            logger.info(
                "API request recorded",
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=f"${cost:.4f}",
                daily_total=f"${self.get_daily_cost():.2f}",
                request_type=request_type
            )

            return cost

    def get_budget_status(self) -> Dict[str, Any]:
        """Get current budget status"""
        daily_cost = self.get_daily_cost()
        monthly_cost = self.get_monthly_cost()

        return {
            "daily": {
                "spent": daily_cost,
                "limit": self.daily_limit,
                "remaining": max(0, self.daily_limit - daily_cost),
                "percent_used": (daily_cost / self.daily_limit * 100) if self.daily_limit > 0 else 0
            },
            "monthly": {
                "spent": monthly_cost,
                "limit": self.monthly_limit,
                "remaining": max(0, self.monthly_limit - monthly_cost),
                "percent_used": (monthly_cost / self.monthly_limit * 100) if self.monthly_limit > 0 else 0
            },
            "total_requests": self._data["total_requests"],
            "total_spent": self._data["total_cost"]
        }

    def reset_daily_limit(self):
        """Manually reset daily limit (for testing)"""
        self._data["daily_costs"][self._get_today_key()] = 0.0
        self._save_data()
        logger.info("Daily budget reset")

    def set_limits(
        self,
        daily: Optional[float] = None,
        monthly: Optional[float] = None,
        per_request: Optional[float] = None
    ):
        """Update budget limits"""
        if daily is not None:
            self.daily_limit = daily
        if monthly is not None:
            self.monthly_limit = monthly
        if per_request is not None:
            self.per_request_limit = per_request

        logger.info(
            "Budget limits updated",
            daily=self.daily_limit,
            monthly=self.monthly_limit,
            per_request=self.per_request_limit
        )


# Global instance
api_budget = APIBudgetManager()


def check_budget(estimated_cost: float = 0.1) -> bool:
    """
    Quick check if budget allows a request.
    Use as decorator or guard.
    """
    allowed, reason = api_budget.can_make_request(estimated_cost)
    if not allowed:
        logger.warning(f"Budget check failed: {reason}")
    return allowed


async def safe_openai_call(func, *args, **kwargs):
    """
    Wrapper for OpenAI calls with budget protection.
    Raises BudgetExceededError if limit reached.
    """
    # Estimate cost (rough)
    estimated = 0.05  # $0.05 per call estimate

    allowed, reason = api_budget.can_make_request(estimated)
    if not allowed:
        raise BudgetExceededError(reason)

    return await func(*args, **kwargs)


class BudgetExceededError(Exception):
    """Raised when API budget is exceeded"""
    pass
