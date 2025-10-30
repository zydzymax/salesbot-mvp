"""
Deal Monitoring Worker
Periodically analyzes all active deals and sends coaching recommendations
"""

import asyncio
from typing import List, Dict, Any
from datetime import datetime, timedelta
import structlog

from ..config import get_settings
from ..database.init_db import db_manager
from ..database.crud import ManagerCRUD
from ..analysis.deal_analyzer import deal_analyzer
from ..bot.coaching_formatter import coaching_formatter
from ..bot.telegram_bot import send_message
from ..amocrm.client import amocrm_client

logger = structlog.get_logger("salesbot.tasks.deal_monitor")


class DealMonitor:
    """Monitor deals and send coaching recommendations"""
    
    def __init__(self):
        self.settings = get_settings()
        self.is_running = False
    
    async def start_monitoring(self, interval_hours: int = 24):
        """
        Запустить мониторинг сделок
        """
        logger.info("Starting deal monitoring", interval_hours=interval_hours)
        self.is_running = True
        
        while self.is_running:
            try:
                await self.analyze_all_deals()
                
                # Ждать до следующего запуска
                await asyncio.sleep(interval_hours * 3600)
                
            except Exception as e:
                logger.error(f"Deal monitoring error", error=str(e))
                await asyncio.sleep(3600)  # Повторить через час при ошибке
    
    def stop_monitoring(self):
        """Остановить мониторинг"""
        logger.info("Stopping deal monitoring")
        self.is_running = False
    
    async def analyze_all_deals(self):
        """
        Проанализировать все активные сделки
        """
        logger.info("Analyzing all active deals")
        
        try:
            # Получить всех менеджеров
            async with db_manager.get_session() as session:
                managers = await ManagerCRUD.get_active_managers(session)
            
            if not managers:
                logger.warning("No managers found")
                return
            
            # Анализировать сделки каждого менеджера
            for manager in managers:
                try:
                    await self.analyze_manager_deals(manager)
                except Exception as e:
                    logger.error(
                        f"Failed to analyze manager deals",
                        manager_id=manager.id,
                        error=str(e)
                    )
            
            logger.info("All deals analyzed successfully")
            
        except Exception as e:
            logger.error(f"Failed to analyze all deals", error=str(e))
    
    async def analyze_manager_deals(self, manager):
        """
        Проанализировать сделки конкретного менеджера
        """
        logger.info(f"Analyzing deals for manager", manager_id=manager.id)
        
        # Проверить что у менеджера есть Telegram
        if not manager.telegram_chat_id:
            logger.info(f"Manager has no Telegram, skipping", manager_id=manager.id)
            return
        
        # Получить сделки менеджера (только активные)
        analysis = await deal_analyzer.analyze_manager_deals(
            manager_id=manager.amocrm_user_id,
            limit=50
        )
        
        if "error" in analysis:
            logger.error(f"Analysis failed", manager_id=manager.id)
            return
        
        # Отправить общий отчёт
        summary_message = coaching_formatter.format_deals_summary(
            analysis,
            manager_name=manager.name
        )
        
        await send_message(
            chat_id=manager.telegram_chat_id,
            text=summary_message
        )
        
        # Отправить детальный анализ проблемных сделок
        attention_deals = analysis.get("attention_deals", [])
        
        for deal_analysis in attention_deals[:3]:  # Топ 3 проблемных
            priority = deal_analysis.get("recommendations", {}).get("priority")
            
            # Отправлять детали только по high priority
            if priority == "high":
                detail_message = coaching_formatter.format_deal_analysis(
                    deal_analysis,
                    manager_name=manager.name
                )
                
                await send_message(
                    chat_id=manager.telegram_chat_id,
                    text=detail_message
                )
                
                # Пауза между сообщениями
                await asyncio.sleep(2)
        
        logger.info(f"Manager analysis sent", manager_id=manager.id)
    
    async def analyze_single_deal(self, deal_id: int, notify: bool = True):
        """
        Проанализировать одну сделку и отправить рекомендации
        """
        logger.info(f"Analyzing single deal", deal_id=deal_id)
        
        try:
            # Получить данные о сделке
            deal_data = await amocrm_client._make_request("GET", f"leads/{deal_id}")
            
            if not deal_data:
                logger.error(f"Deal not found", deal_id=deal_id)
                return None
            
            # Анализировать сделку
            analysis = await deal_analyzer.analyze_deal_comprehensive(deal_id)
            
            if "error" in analysis:
                logger.error(f"Deal analysis failed", deal_id=deal_id)
                return None
            
            # Если нужно отправить уведомление
            if notify:
                manager_id = deal_data.get("responsible_user_id")
                
                # Найти менеджера в базе
                async with db_manager.get_session() as session:
                    manager = await ManagerCRUD.get_manager_by_amocrm_id(
                        session,
                        manager_id
                    )
                
                if manager and manager.telegram_chat_id:
                    message = coaching_formatter.format_deal_analysis(
                        analysis,
                        manager_name=manager.name
                    )
                    
                    await send_message(
                        chat_id=manager.telegram_chat_id,
                        text=message
                    )
                    
                    logger.info(f"Deal analysis sent to manager", deal_id=deal_id)
            
            return analysis
            
        except Exception as e:
            logger.error(f"Single deal analysis failed", deal_id=deal_id, error=str(e))
            return None
    
    async def check_stale_deals(self, days_threshold: int = 3):
        """
        Проверить застоявшиеся сделки (без активности N дней)
        """
        logger.info(f"Checking stale deals", days_threshold=days_threshold)
        
        try:
            # Получить всех менеджеров
            async with db_manager.get_session() as session:
                managers = await ManagerCRUD.get_active_managers(session)
            
            for manager in managers:
                if not manager.telegram_chat_id:
                    continue
                
                # Получить сделки менеджера
                try:
                    deals_result = await amocrm_client._make_request(
                        "GET",
                        "leads",
                        params={
                            "filter[responsible_user_id]": manager.amocrm_user_id,
                            "limit": 50
                        }
                    )
                    
                    deals = deals_result.get("_embedded", {}).get("leads", [])
                    
                    # Проверить каждую сделку
                    for deal in deals:
                        updated_at = deal.get("updated_at", 0)
                        days_idle = (datetime.utcnow().timestamp() - updated_at) / 86400
                        
                        if days_idle > days_threshold:
                            # Отправить алерт
                            alert_message = coaching_formatter.format_quick_alert(
                                deal_name=deal.get("name", "Без названия"),
                                issue=f"Нет активности {int(days_idle)} дней",
                                action="Свяжитесь с клиентом сегодня",
                                urgency="high"
                            )
                            
                            await send_message(
                                chat_id=manager.telegram_chat_id,
                                text=alert_message
                            )
                            
                            logger.info(
                                f"Stale deal alert sent",
                                deal_id=deal.get("id"),
                                days_idle=days_idle
                            )
                
                except Exception as e:
                    logger.error(
                        f"Failed to check stale deals for manager",
                        manager_id=manager.id,
                        error=str(e)
                    )
            
        except Exception as e:
            logger.error(f"Stale deals check failed", error=str(e))


# Global instance
deal_monitor = DealMonitor()
