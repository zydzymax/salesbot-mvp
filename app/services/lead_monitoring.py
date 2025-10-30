"""
Lead monitoring service - track unprocessed leads and send alerts
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import structlog

from ..database.init_db import db_manager
from ..amocrm.client import amocrm_client

logger = structlog.get_logger("salesbot.lead_monitoring")


class LeadMonitoringService:
    """Service for monitoring lead processing time and sending alerts"""

    def __init__(self, response_time_minutes: int = 10):
        """
        Initialize lead monitoring service

        Args:
            response_time_minutes: Max allowed time to process a lead (default: 10 minutes)
        """
        self.response_time_minutes = response_time_minutes
        self.alerted_leads = set()  # Track leads we already alerted about

    async def check_unprocessed_leads(self) -> List[Dict[str, Any]]:
        """
        Check for leads that haven't been processed within allowed time

        Returns:
            List of unprocessed leads with details
        """
        try:
            cutoff_time = datetime.utcnow() - timedelta(minutes=self.response_time_minutes)
            cutoff_timestamp = int(cutoff_time.timestamp())

            # Get recent incoming leads from AmoCRM
            filter_params = {
                "filter[created_at][from]": cutoff_timestamp,
            }

            logger.info(
                f"Checking for unprocessed leads",
                cutoff_time=cutoff_time.isoformat(),
                response_time_minutes=self.response_time_minutes
            )

            leads_response = await amocrm_client.get_leads(
                limit=50,
                filter_params=filter_params
            )

            leads = leads_response.get("_embedded", {}).get("leads", [])
            unprocessed_leads = []

            for lead in leads:
                lead_id = str(lead["id"])
                lead_name = lead.get("name", f"Лид #{lead_id}")
                created_at = lead.get("created_at")
                responsible_user_id = lead.get("responsible_user_id")

                if not created_at:
                    continue

                lead_created = datetime.fromtimestamp(created_at)
                age_minutes = (datetime.utcnow() - lead_created).total_seconds() / 60

                # Check if lead has been contacted (has calls or notes)
                has_contact = await self._check_lead_contact(lead_id)

                if not has_contact and age_minutes >= self.response_time_minutes:
                    # Check if we already alerted about this lead
                    if lead_id not in self.alerted_leads:
                        unprocessed_leads.append({
                            "lead_id": lead_id,
                            "lead_name": lead_name,
                            "created_at": lead_created,
                            "age_minutes": int(age_minutes),
                            "responsible_user_id": responsible_user_id,
                            "url": f"https://{amocrm_client.subdomain}.amocrm.ru/leads/detail/{lead_id}"
                        })
                        self.alerted_leads.add(lead_id)

            if unprocessed_leads:
                logger.warning(
                    f"Found unprocessed leads",
                    count=len(unprocessed_leads),
                    lead_ids=[l["lead_id"] for l in unprocessed_leads]
                )
            else:
                logger.info("No unprocessed leads found")

            return unprocessed_leads

        except Exception as e:
            logger.error(f"Error checking unprocessed leads", error=str(e))
            return []

    async def _check_lead_contact(self, lead_id: str) -> bool:
        """
        Check if lead has been contacted (has calls or notes)

        Args:
            lead_id: Lead ID to check

        Returns:
            True if lead has been contacted, False otherwise
        """
        try:
            # Check for notes (calls, emails, etc)
            notes = await amocrm_client.get_lead_notes(
                lead_id=lead_id,
                limit=10
            )

            if notes:
                # Check if there are any contact notes (calls, emails)
                for note in notes:
                    note_type = note.get("note_type")
                    if note_type in ["call_in", "call_out", "mail_message", "sms_message"]:
                        return True

            return False

        except Exception as e:
            logger.warning(f"Error checking lead contact", lead_id=lead_id, error=str(e))
            return False  # Assume not contacted if check fails

    def format_alert_message(self, unprocessed_leads: List[Dict[str, Any]]) -> str:
        """
        Format alert message for Telegram

        Args:
            unprocessed_leads: List of unprocessed leads

        Returns:
            Formatted message text
        """
        if not unprocessed_leads:
            return None

        message_parts = [
            "🚨 <b>АЛЕРТ: Необработанные лиды!</b>\n",
            f"Найдено <b>{len(unprocessed_leads)}</b> лидов без обработки более {self.response_time_minutes} минут:\n"
        ]

        for lead in unprocessed_leads:
            age_minutes = lead["age_minutes"]
            message_parts.append(
                f"\n📋 <b>{lead['lead_name']}</b>\n"
                f"   ⏱ Создан: {age_minutes} мин назад\n"
                f"   🔗 <a href=\"{lead['url']}\">Открыть лид</a>"
            )

        message_parts.append(
            f"\n\n⚠️ <b>Требуется срочная обработка!</b>\n"
            f"Нормативное время обработки: {self.response_time_minutes} минут"
        )

        return "".join(message_parts)

    async def get_manager_chat_id(self, responsible_user_id: int) -> Optional[str]:
        """
        Get Telegram chat ID for responsible manager

        Args:
            responsible_user_id: AmoCRM user ID

        Returns:
            Telegram chat ID or None
        """
        try:
            async with db_manager.get_session() as session:
                from ..database.crud import ManagerCRUD

                manager = await ManagerCRUD.get_manager_by_amocrm_id(
                    session, str(responsible_user_id)
                )

                if manager and manager.telegram_chat_id:
                    return manager.telegram_chat_id

                return None

        except Exception as e:
            logger.error(
                f"Error getting manager chat ID",
                user_id=responsible_user_id,
                error=str(e)
            )
            return None

    def clear_alerted_leads(self):
        """Clear the set of alerted leads (call at end of day)"""
        self.alerted_leads.clear()
        logger.info("Cleared alerted leads cache")


# Global service instance
lead_monitoring_service = LeadMonitoringService(response_time_minutes=10)
