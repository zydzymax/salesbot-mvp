"""
Task Scheduler for Periodic Jobs
Запускает периодические задачи без Celery/Redis
"""

import asyncio
from datetime import datetime, time, timedelta
from typing import Callable, Optional
import structlog

from ..config import get_settings
from ..alerts.telegram_alerts import telegram_alerts
from ..analysis.commitment_tracker import commitment_tracker

logger = structlog.get_logger("salesbot.scheduler")


class TaskScheduler:
    """Планировщик периодических задач"""

    def __init__(self):
        self.settings = get_settings()
        self.running = False
        self.tasks = []

    async def start(self):
        """Запустить планировщик"""

        logger.info("Starting task scheduler")
        self.running = True

        # Запустить все периодические задачи
        self.tasks = [
            asyncio.create_task(self._run_periodic_task(
                "check_overdue_commitments",
                telegram_alerts.check_overdue_commitments,
                interval_minutes=60  # Каждый час
            )),
            asyncio.create_task(self._run_periodic_task(
                "check_unprocessed_leads",
                telegram_alerts.check_unprocessed_leads,
                interval_minutes=5  # Каждые 5 минут - мониторинг необработанных лидов
            )),
            asyncio.create_task(self._run_periodic_task(
                "send_commitment_reminders",
                commitment_tracker.send_commitment_reminders,
                interval_minutes=30  # Каждые 30 минут
            )),
            asyncio.create_task(self._run_daily_task(
                "daily_summary",
                telegram_alerts.send_daily_summary,
                run_time=time(hour=18, minute=0)  # 18:00 каждый день
            )),
        ]

        logger.info(f"Scheduler started with {len(self.tasks)} tasks")

    async def stop(self):
        """Остановить планировщик"""

        logger.info("Stopping task scheduler")
        self.running = False

        # Отменить все задачи
        for task in self.tasks:
            task.cancel()

        # Дождаться завершения
        await asyncio.gather(*self.tasks, return_exceptions=True)

        logger.info("Scheduler stopped")

    async def _run_periodic_task(
        self,
        name: str,
        func: Callable,
        interval_minutes: int
    ):
        """Запустить периодическую задачу"""

        logger.info(f"Started periodic task: {name}", interval_minutes=interval_minutes)

        # Wait a bit before first run to ensure app is fully started
        await asyncio.sleep(10)

        while self.running:
            try:
                logger.debug(f"Running task: {name}")
                await func()

                # Ждать следующего запуска
                await asyncio.sleep(interval_minutes * 60)

            except asyncio.CancelledError:
                logger.info(f"Task cancelled: {name}")
                break

            except Exception as e:
                logger.error(f"Task failed: {name}", error=str(e))
                # Подождать перед повтором
                await asyncio.sleep(60)

    async def _run_daily_task(
        self,
        name: str,
        func: Callable,
        run_time: time
    ):
        """Запустить ежедневную задачу в определенное время"""

        logger.info(f"Started daily task: {name}", run_time=run_time.strftime('%H:%M'))

        while self.running:
            try:
                # Вычислить время до следующего запуска
                now = datetime.now()
                target = datetime.combine(now.date(), run_time)

                # Если время уже прошло сегодня, планируем на завтра
                if now.time() > run_time:
                    target = datetime.combine(
                        now.date() + timedelta(days=1),
                        run_time
                    )

                seconds_until_target = (target - now).total_seconds()

                logger.debug(
                    f"Daily task {name} scheduled",
                    next_run=target.strftime('%Y-%m-%d %H:%M'),
                    seconds_until=seconds_until_target
                )

                # Ждать до времени запуска
                await asyncio.sleep(seconds_until_target)

                # Запустить задачу
                logger.info(f"Running daily task: {name}")
                await func()

            except asyncio.CancelledError:
                logger.info(f"Daily task cancelled: {name}")
                break

            except Exception as e:
                logger.error(f"Daily task failed: {name}", error=str(e))
                # Подождать 1 час перед повтором
                await asyncio.sleep(3600)


# Global instance
task_scheduler = TaskScheduler()
