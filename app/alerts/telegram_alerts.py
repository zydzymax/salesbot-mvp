"""
Telegram Alert System
Отправляет уведомления администраторам о важных событиях
"""

from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pytz
import structlog
import httpx

from ..config import get_settings
from ..database.init_db import db_manager
from ..database.models import Commitment
from ..analytics.manager_dashboard import manager_dashboard

logger = structlog.get_logger("salesbot.alerts")


class TelegramAlertSystem:
    """Система алертов в Telegram"""

    def __init__(self):
        self.settings = get_settings()
        self.moscow_tz = pytz.timezone('Europe/Moscow')

        # ID чатов администраторов (можно загрузить из БД или конфига)
        self.admin_chat_ids = self._load_admin_chat_ids()

    def _load_admin_chat_ids(self) -> List[str]:
        """Загрузить ID чатов администраторов"""
        import json

        admin_ids_str = self.settings.telegram_admin_chat_ids if hasattr(self.settings, 'telegram_admin_chat_ids') else None

        if not admin_ids_str:
            return []

        # Parse JSON string to list
        try:
            if isinstance(admin_ids_str, str):
                admin_ids = json.loads(admin_ids_str)
                return admin_ids if isinstance(admin_ids, list) else [admin_ids]
            elif isinstance(admin_ids_str, list):
                return admin_ids_str
            else:
                return []
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse telegram_admin_chat_ids: {admin_ids_str}")
            return []

    def is_working_hours(self) -> bool:
        """Проверка рабочего времени (9:00-18:00 МСК)"""
        now_moscow = datetime.now(self.moscow_tz)
        hour = now_moscow.hour

        # Рабочие часы: 9:00 - 18:00
        return 9 <= hour < 18 and now_moscow.weekday() < 5  # Пн-Пт

    async def send_telegram_message(self, chat_id: str, message: str, parse_mode: str = "HTML"):
        """Отправить сообщение в Telegram"""

        if not self.settings.telegram_bot_token:
            logger.warning("Telegram bot token not configured")
            return False

        try:
            url = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage"

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json={
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": parse_mode
                })

                response.raise_for_status()
                logger.info("Telegram message sent", chat_id=chat_id)
                return True

        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}", chat_id=chat_id)
            return False

    async def check_overdue_commitments(self):
        """Проверить просроченные обещания и отправить алерты"""

        logger.info("Checking overdue commitments")

        try:
            async with db_manager.get_session() as session:
                from sqlalchemy import select, and_

                # Найти просроченные обещания за последние 24 часа
                yesterday = datetime.utcnow() - timedelta(hours=24)

                stmt = select(Commitment).where(
                    and_(
                        Commitment.is_fulfilled == False,
                        Commitment.is_overdue == False,  # Еще не помечены как просроченные
                        Commitment.deadline < datetime.utcnow(),
                        Commitment.deadline > yesterday  # Только новые просрочки
                    )
                )

                result = await session.execute(stmt)
                overdue = list(result.scalars().all())

                if not overdue:
                    logger.info("No new overdue commitments")
                    return

                # Пометить как просроченные
                for commitment in overdue:
                    commitment.is_overdue = True

                await session.commit()

                # Группировать по менеджерам
                by_manager = {}
                for commitment in overdue:
                    manager_id = commitment.manager_id
                    if manager_id not in by_manager:
                        by_manager[manager_id] = []
                    by_manager[manager_id].append(commitment)

                # Отправить алерты администраторам
                message = self._format_overdue_alert(by_manager, overdue)
                await self._send_to_admins(message)

                logger.info(f"Sent overdue commitments alert", count=len(overdue))

        except Exception as e:
            logger.error(f"Failed to check overdue commitments: {e}")

    async def check_unprocessed_leads(self):
        """Проверить необработанные лиды (не обработаны в течение 10 минут)"""

        # Только в рабочее время
        if not self.is_working_hours():
            logger.debug("Outside working hours, skipping lead check")
            return

        logger.info("Checking unprocessed leads")

        try:
            from ..services.lead_monitoring import lead_monitoring_service

            # Получить список необработанных лидов
            unprocessed_leads = await lead_monitoring_service.check_unprocessed_leads()

            if not unprocessed_leads:
                logger.info("No unprocessed leads found")
                return

            # Форматировать и отправить алерт
            message = lead_monitoring_service.format_alert_message(unprocessed_leads)

            if message:
                await self._send_to_admins(message)
                logger.info(f"Sent unprocessed leads alert", count=len(unprocessed_leads))

                # Также отправить персональные алерты ответственным менеджерам
                await self._send_manager_alerts(unprocessed_leads)

        except Exception as e:
            logger.error(f"Failed to check unprocessed leads: {e}")

    async def send_daily_summary(self):
        """Отправить ежедневную сводку"""

        try:
            # Получить отчет за день
            report = await manager_dashboard.generate_daily_report()

            message = f"""
📊 <b>Ежедневный Отчет</b>

📅 Дата: {report['date']}
👥 Команда: {report['team_size']} менеджеров
📞 Всего звонков: {report['total_calls']}
⭐️ Средняя оценка: {report['avg_quality_score']}/100

🏆 <b>Топ-3 Менеджера:</b>
"""

            for i, performer in enumerate(report['top_performers'], 1):
                medal = ['🥇', '🥈', '🥉'][i-1]
                message += f"{medal} {performer['name']} - {performer['score']}/100\n"

            if report['high_priority_alerts']:
                message += f"\n🚨 <b>Критические Алерты: {len(report['high_priority_alerts'])}</b>\n"
                for alert in report['high_priority_alerts'][:3]:
                    message += f"• {alert['manager_name']}: {alert['message']}\n"

            await self._send_to_admins(message)

            logger.info("Sent daily summary")

        except Exception as e:
            logger.error(f"Failed to send daily summary: {e}")

    def _format_overdue_alert(self, by_manager: Dict, all_overdue: List) -> str:
        """Форматировать алерт о просроченных обещаниях"""

        message = f"""
🚨 <b>ПРОСРОЧЕННЫЕ ОБЕЩАНИЯ</b>

Обнаружено просроченных обещаний: <b>{len(all_overdue)}</b>

"""

        for manager_id, commitments in list(by_manager.items())[:5]:  # Топ-5 менеджеров
            # Получить имя менеджера из первого обещания
            manager_name = commitments[0].manager.name if commitments[0].manager else f"Менеджер #{manager_id}"

            message += f"👤 <b>Менеджер: {manager_name}</b> | Просрочено: {len(commitments)}\n\n"

            for commitment in commitments[:3]:  # Показать первые 3
                hours_overdue = int((datetime.utcnow() - commitment.deadline).total_seconds() / 3600)

                # Добавляем ID сделки если есть
                lead_info = f"<code>#{commitment.call.amocrm_lead_id}</code>" if commitment.call and commitment.call.amocrm_lead_id else "Сделка не указана"

                message += f"📋 Сделка: {lead_info}\n"
                message += f"   ⚠️ {commitment.commitment_text} ({hours_overdue}ч назад)\n\n"

            if len(commitments) > 3:
                message += f"   ... и ещё {len(commitments) - 3}\n"

            message += "\n"

        message += "📌 <b>Требуется вмешательство!</b>"

        return message

    def _format_unprocessed_leads_alert(self, unprocessed: List) -> str:
        """Форматировать алерт о необработанных лидах"""

        message = f"""
⚠️ <b>НЕОБРАБОТАННЫЕ ЛИДЫ</b>

Пропущено звонков за последние 15 минут: <b>{len(unprocessed)}</b>

"""

        for call in unprocessed[:5]:
            time_ago = int((datetime.utcnow() - call.created_at).total_seconds() / 60)
            manager_name = call.manager.name if call.manager else "Неизвестен"
            lead_id = f"<code>#{call.amocrm_lead_id}</code>" if call.amocrm_lead_id else "ID не указан"

            message += f"📋 Сделка: {lead_id}\n"
            message += f"👤 Менеджер: <b>{manager_name}</b>\n"
            message += f"📞 {call.client_phone or 'Номер скрыт'}\n"
            message += f"⏰ {time_ago} мин назад\n\n"

        message += "📌 <b>Требуется обработка!</b>"

        return message

    async def send_critical_deal_alert(self, lead_id: str, manager_name: str, risk_type: str, description: str):
        """Отправить алерт о критическом риске сделки"""

        message = f"""
🚨 <b>КРИТИЧЕСКИЙ РИСК</b>

📋 <b>Сделка:</b> <code>#{lead_id}</code>
👤 <b>Менеджер:</b> {manager_name}

⚠️ <b>Риск:</b> {risk_type}

📝 {description}

━━━━━━━━━━━━━━━
🔎 <b>Для поиска:</b>
• AmoCRM: Скопируйте <code>#{lead_id}</code>
• Дашборд: https://app.justbusiness.lol/admin/deals/{lead_id}

📌 <b>Требуется немедленное вмешательство!</b>
"""

        await self._send_to_admins(message)
        logger.info(f"Sent critical deal alert", lead_id=lead_id, risk_type=risk_type)

    async def _send_to_admins(self, message: str):
        """Отправить сообщение всем администраторам"""

        if not self.admin_chat_ids:
            logger.warning("No admin chat IDs configured")
            return

        for chat_id in self.admin_chat_ids:
            await self.send_telegram_message(chat_id, message)

    async def _send_manager_alerts(self, unprocessed_leads: List[Dict]):
        """Отправить персональные алерты ответственным менеджерам"""

        from ..services.lead_monitoring import lead_monitoring_service

        # Группировать лиды по ответственным менеджерам
        by_manager = {}
        for lead in unprocessed_leads:
            manager_id = lead.get("responsible_user_id")
            if manager_id:
                if manager_id not in by_manager:
                    by_manager[manager_id] = []
                by_manager[manager_id].append(lead)

        # Отправить персональные уведомления
        for manager_id, leads in by_manager.items():
            chat_id = await lead_monitoring_service.get_manager_chat_id(manager_id)

            if not chat_id:
                logger.debug(f"No Telegram chat ID for manager", manager_id=manager_id)
                continue

            # Форматировать персональное сообщение
            message_parts = [
                "⚠️ <b>У вас есть необработанные лиды!</b>\n",
                f"Найдено <b>{len(leads)}</b> лидов без обработки:\n"
            ]

            for lead in leads:
                age_minutes = lead["age_minutes"]
                message_parts.append(
                    f"\n📋 <b>{lead['lead_name']}</b>\n"
                    f"   ⏱ Создан: {age_minutes} мин назад\n"
                    f"   🔗 <a href=\"{lead['url']}\">Открыть лид</a>"
                )

            message_parts.append(
                "\n\n💡 <b>Требуется обработка!</b>\n"
                "Обработайте лиды как можно скорее."
            )

            message = "".join(message_parts)
            await self.send_telegram_message(chat_id, message)

            logger.info(f"Sent personal alert to manager", manager_id=manager_id, leads_count=len(leads))


# Global instance
telegram_alerts = TelegramAlertSystem()
